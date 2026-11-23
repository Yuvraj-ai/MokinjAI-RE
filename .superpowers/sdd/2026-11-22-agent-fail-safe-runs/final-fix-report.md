# Final-fix report

## Fix 1: SandboxBusy cleanup
`stream_turn` gains keyword `session_created_by_turn` (default False). The `except SandboxBusy` branch now calls the new `_discard_refused_turn`, which opens a short DB session and deletes the turn's user message and, when `session_created_by_turn` is true, the ChatSession. `/v1/chat` (`routers/public.py`, streaming and buffered) passes `not body.conversation_id`. Playground sessions are created by the client beforehand, so they are never dropped.

## Fix 2: connector timeout not retried
`ToolTimeoutError(Exception)` in `agent_resilience.py`; `is_transient` returns False for it. `connector_runtime.with_timeout` catches `asyncio.TimeoutError` and raises it `from` the original, naming the tool and the limit. It reaches the model through `ToolErrorMiddleware` and counts toward the failure limit.

## Fix 3: card redaction
The `on_tool_error` card text goes through `short_message`.

## Fix 4: docs
`project-status.md` wording changed; `product.md` and `project-status.md` document the 2-minute held connection (clients need a longer read timeout), the cleanup on refusal, and no retry on connector timeouts.

## Tests (new file `backend/unit_tests/test_final_fixes.py`, 5 tests)
Each failed before the fix. Covers: `is_transient(ToolTimeoutError)` False; a connector tool over a patched ceiling runs once and the model gets an error; busy refusal then retry yields exactly one user message; busy on a new session leaves no ChatSession; card redacts `user:secret@`.

Suite: 1262 passed, 13 skipped, 22 deselected (baseline 1257, +5).

## Notes
No router-level test exercises the `session_created_by_turn` wiring in `public.py`; it is covered at `stream_turn` level only.
