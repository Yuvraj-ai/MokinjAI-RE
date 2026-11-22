"""Which reply formats a model may be asked to generate.

Markdown is available to every model. OpenUI needs a context window of at least
`OPENUI_MIN_CONTEXT_WINDOW` tokens. That number is a product rule, not a measure
of how well a model writes OpenUI, so a large window does not guarantee valid
output and the renderer must still cope with bad replies.

The window is the value stored on the LLM profile: the model-card figure for
known models, or the user's own figure for a custom endpoint (ADR-001). Names of
models are never consulted. This module is the only place the threshold lives;
the frontend reads the resulting list from the agent's capabilities.
"""

from typing import Any

MARKDOWN = "markdown"
OPENUI = "openui"

DEFAULT_OUTPUT_FORMAT = MARKDOWN
OPENUI_MIN_CONTEXT_WINDOW = 200_000

ALL_OUTPUT_FORMATS = (MARKDOWN, OPENUI)


class UnsupportedOutputFormat(ValueError):
    """The requested format is unknown, or the model is not eligible for it."""


def _usable_window(context_window: Any) -> int | None:
    # bool is an int subclass; floats and strings are not a stored window.
    if isinstance(context_window, bool) or not isinstance(context_window, int):
        return None
    return context_window if context_window > 0 else None


def get_supported_output_formats(context_window: Any) -> list[str]:
    """Formats offered for a model with this context window (Markdown first)."""
    window = _usable_window(context_window)
    if window is not None and window >= OPENUI_MIN_CONTEXT_WINDOW:
        return [MARKDOWN, OPENUI]
    return [MARKDOWN]


def require_supported(output_format: str, context_window: Any) -> None:
    """Raise `UnsupportedOutputFormat` unless this model may use the format."""
    if output_format not in ALL_OUTPUT_FORMATS:
        raise UnsupportedOutputFormat(f"Unknown output format {output_format!r}.")
    if output_format in get_supported_output_formats(context_window):
        return
    window = _usable_window(context_window)
    have = f"{window:,}" if window is not None else "unknown"
    raise UnsupportedOutputFormat(
        f"{output_format} output needs a context window of at least "
        f"{OPENUI_MIN_CONTEXT_WINDOW:,} tokens. This model has {have}."
    )
