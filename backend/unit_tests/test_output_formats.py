"""Output-format eligibility (Markdown for everyone, OpenUI from 200,000 tokens).

Pure: the threshold is a product rule, so the boundary is pinned explicitly.
"""

import pytest

from app.services.agent_capabilities import capabilities_for
from app.services.output_formats import (
    DEFAULT_OUTPUT_FORMAT,
    OPENUI_MIN_CONTEXT_WINDOW,
    UnsupportedOutputFormat,
    get_supported_output_formats,
    require_supported,
)

BOTH = ["markdown", "openui"]
MARKDOWN = ["markdown"]


class TestEligibility:
    def test_threshold_is_the_product_rule(self):
        assert OPENUI_MIN_CONTEXT_WINDOW == 200_000
        assert DEFAULT_OUTPUT_FORMAT == "markdown"

    @pytest.mark.parametrize(
        "window,expected",
        [
            (32_000, MARKDOWN),
            (128_000, MARKDOWN),
            (199_999, MARKDOWN),
            (200_000, BOTH),
            (200_001, BOTH),
            (256_000, BOTH),
            (1_000_000, BOTH),
        ],
    )
    def test_boundary(self, window, expected):
        assert get_supported_output_formats(window) == expected

    @pytest.mark.parametrize(
        "bad",
        [None, 0, -1, -200_000, True, 200_000.0, "200000", float("nan"), [], {}],
    )
    def test_unknown_or_invalid_windows_get_markdown_only(self, bad):
        assert get_supported_output_formats(bad) == MARKDOWN

    def test_markdown_is_always_first_and_the_default(self):
        assert get_supported_output_formats(1_000_000)[0] == DEFAULT_OUTPUT_FORMAT

    def test_returns_a_fresh_list(self):
        get_supported_output_formats(200_000).append("x")
        assert get_supported_output_formats(200_000) == BOTH


class TestRequireSupported:
    def test_accepts_a_supported_format(self):
        require_supported("openui", 200_000)
        require_supported("markdown", None)

    def test_rejects_openui_below_the_threshold(self):
        with pytest.raises(UnsupportedOutputFormat) as caught:
            require_supported("openui", 199_999)
        assert "200,000" in str(caught.value)
        assert "199,999" in str(caught.value)

    def test_rejects_openui_when_the_window_is_unknown(self):
        with pytest.raises(UnsupportedOutputFormat):
            require_supported("openui", None)

    def test_rejects_unknown_formats(self):
        with pytest.raises(UnsupportedOutputFormat):
            require_supported("html", 1_000_000)


class TestCapabilitiesExposure:
    def test_capabilities_carry_formats_and_window(self):
        caps = capabilities_for("openai", "m", profile={}, context_window=256_000)
        assert caps.output_formats == BOTH
        assert caps.context_window == 256_000
        assert caps.as_dict()["output_formats"] == BOTH
        assert caps.as_dict()["context_window"] == 256_000

    def test_capabilities_without_a_window_are_markdown_only(self):
        caps = capabilities_for("openai", "m", profile={})
        assert caps.output_formats == MARKDOWN
        assert caps.context_window is None
