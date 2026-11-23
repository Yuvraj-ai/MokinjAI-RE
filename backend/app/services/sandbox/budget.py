"""How much sandbox memory this process has handed out, per workspace.

The tier in `backends.py` sizes one container. This module bounds the sum, so a
workspace cannot start runs until the host is out of memory: forty 95 MiB runs would
otherwise each ask for 2 GB.

A run that does not fit waits in a bounded first-come-first-served queue
(`SlotRequest`) instead of failing at once.

shortcut: the budget is per process, so two workers can each admit 4 GB; move it to
Redis when the backend runs with more than one worker.
"""

import asyncio
import math
import threading
import time
from collections import deque
from typing import Any, AsyncIterator, Literal

from app.services import agent_resilience as _limits

# One workspace's in-flight sandboxes. Chosen so a single 2 GB run plus two 1 GB runs
# still fits on a small host while a burst of large runs is refused rather than OOM.
WORKSPACE_LIMIT_MB = 4096

# A client is never told to retry sooner than this.
MIN_RETRY_AFTER_S = 5

_lock = threading.Lock()
_used: dict[str, int] = {}
# Runs waiting for memory, oldest first, per workspace. Guarded by `_lock`.
_queues: dict[str, "deque[SlotRequest]"] = {}


class SandboxBusy(Exception):
    """The workspace has no sandbox capacity and waiting is over (or not allowed)."""

    def __init__(self, retry_after_s: int, reason: Literal["queue_full", "timeout"]):
        self.retry_after_s = retry_after_s
        self.reason = reason
        super().__init__(f"The sandbox is busy. Try again in about {retry_after_s} seconds.")


def reserve(workspace_id: str, mb: int) -> bool:
    """Admit `mb` more megabytes for this workspace, or refuse without changing state."""
    with _lock:
        used = _used.get(workspace_id, 0)
        if used + mb > WORKSPACE_LIMIT_MB:
            return False
        _used[workspace_id] = used + mb
        return True


def release(workspace_id: str, mb: int) -> None:
    """Give `mb` back and admit waiters that now fit. Releasing more than was
    reserved cannot drive the count negative."""
    with _lock:
        remaining = _used.get(workspace_id, 0) - mb
        if remaining > 0:
            _used[workspace_id] = remaining
        else:
            _used.pop(workspace_id, None)
        _admit_waiters(workspace_id)


def used_mb(workspace_id: str) -> int:
    """The workspace's current reservation, for tests and diagnostics."""
    with _lock:
        return _used.get(workspace_id, 0)


def waiting(workspace_id: str) -> int:
    """How many runs are queued for this workspace, for tests and diagnostics."""
    with _lock:
        return len(_queues.get(workspace_id, ()))


def reset() -> None:
    """Drop every reservation and waiter. Test-only: a leaked reservation would
    otherwise outlive the test that made it."""
    with _lock:
        _used.clear()
        _queues.clear()


def _notify(request: "SlotRequest") -> None:
    """Wake a waiter; safe from any thread."""
    loop = request._loop
    if loop is None:
        return
    try:
        loop.call_soon_threadsafe(request._wake.set)
    except RuntimeError:  # its loop is closed; nobody is listening
        pass


def _admit_waiters(workspace_id: str) -> None:
    """Hand memory to waiters strictly in arrival order. Caller holds `_lock`.

    Only the head is considered: a small later run must not overtake a large earlier
    one, or the large one could starve.
    """
    queue = _queues.get(workspace_id)
    if not queue:
        return
    while queue:
        head = queue[0]
        used = _used.get(workspace_id, 0)
        if used + head.mb > WORKSPACE_LIMIT_MB:
            break
        _used[workspace_id] = used + head.mb
        queue.popleft()
        head._granted = True
    if not queue:
        _queues.pop(workspace_id, None)
    # Everyone queued here may have a new position, and the granted ones proceed.
    for waiter in _waiters_all.get(workspace_id, ()):
        _notify(waiter)


# Every request currently inside `wait()` for a workspace (queued or just granted),
# so a grant can wake the request that received it. Guarded by `_lock`.
_waiters_all: dict[str, set["SlotRequest"]] = {}


class SlotRequest:
    """One run's claim on `mb` megabytes of a workspace's sandbox budget.

    `async for position in request.wait()` returns once the memory is reserved,
    yielding the 1-based queue position each time it changes (nothing is yielded when
    capacity is free). `release()` is idempotent and also removes a still-queued
    request, so teardown is the same whether the run finished, failed or was stopped.
    """

    def __init__(
        self,
        workspace_id: str,
        mb: int,
        *,
        max_wait_s: float | None = None,
        max_waiters: int | None = None,
    ):
        self.workspace_id = workspace_id
        self.mb = mb
        self.max_wait_s = _limits.SANDBOX_QUEUE_MAX_WAIT_S if max_wait_s is None else max_wait_s
        self.max_waiters = (
            _limits.SANDBOX_QUEUE_MAX_WAITERS if max_waiters is None else max_waiters
        )
        self._granted = False
        self._deadline = 0.0
        self._wake = asyncio.Event()
        self._loop: asyncio.AbstractEventLoop | None = None

    async def __aenter__(self) -> "SlotRequest":
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        self.release()

    @property
    def holds_memory(self) -> bool:
        return self._granted

    def release(self) -> None:
        """Give the memory back, or leave the queue if still waiting. Idempotent."""
        with _lock:
            registered = _waiters_all.get(self.workspace_id)
            if registered is not None:
                registered.discard(self)
                if not registered:
                    _waiters_all.pop(self.workspace_id, None)
            if self._granted:
                self._granted = False
                held = True
            else:
                held = False
                queue = _queues.get(self.workspace_id)
                if queue is not None and self in queue:
                    queue.remove(self)
                    if not queue:
                        _queues.pop(self.workspace_id, None)
                    # Those behind moved up, and the new head may fit.
                    _admit_waiters(self.workspace_id)
        if held:
            release(self.workspace_id, self.mb)

    def _retry_after_s(self, queue: Any) -> int:
        """Remaining wait of the head waiter, rounded up (a slot is likely to free
        about then), never below the minimum."""
        if queue:
            remaining = queue[0]._deadline - time.monotonic()
            return max(MIN_RETRY_AFTER_S, math.ceil(remaining))
        return MIN_RETRY_AFTER_S

    async def wait(self) -> AsyncIterator[int]:
        self._loop = asyncio.get_running_loop()
        with _lock:
            queue = _queues.get(self.workspace_id)
            # Join behind existing waiters even if we would fit: no queue-jumping.
            if not queue and _used.get(self.workspace_id, 0) + self.mb <= WORKSPACE_LIMIT_MB:
                _used[self.workspace_id] = _used.get(self.workspace_id, 0) + self.mb
                self._granted = True
                return
            if len(queue or ()) >= self.max_waiters:
                raise SandboxBusy(self._retry_after_s(queue), "queue_full")
            self._deadline = time.monotonic() + self.max_wait_s
            _queues.setdefault(self.workspace_id, deque()).append(self)
            _waiters_all.setdefault(self.workspace_id, set()).add(self)
        last: int | None = None
        try:
            while True:
                with _lock:
                    if self._granted:
                        return
                    queue = _queues.get(self.workspace_id)
                    position = list(queue).index(self) + 1 if queue and self in queue else None
                    self._wake.clear()
                if position is None:
                    raise SandboxBusy(MIN_RETRY_AFTER_S, "timeout")
                if position != last:
                    last = position
                    yield position
                    continue  # state may have changed while the consumer ran
                remaining = self._deadline - time.monotonic()
                if remaining <= 0:
                    raise SandboxBusy(self._timeout_retry_after(), "timeout")
                try:
                    await asyncio.wait_for(self._wake.wait(), remaining)
                except asyncio.TimeoutError:
                    with _lock:
                        if self._granted:
                            return
                    raise SandboxBusy(self._timeout_retry_after(), "timeout") from None
        except BaseException:
            # Timeout, cancellation, or the consumer closing the generator: leave the
            # queue (or give back a grant that arrived too late) and never keep memory.
            self.release()
            raise

    def _timeout_retry_after(self) -> int:
        with _lock:
            queue = _queues.get(self.workspace_id)
            return self._retry_after_s([w for w in (queue or ()) if w is not self])
