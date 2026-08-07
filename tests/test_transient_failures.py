from __future__ import annotations

import pytest

from takopi.utils.transient_failures import (
    TransientFailure,
    classify_transient_failure,
    format_transient_failure,
)

# The exact observed OmniRoute 503 capacity failure blob.
# This is an OmniRoute routing-application response surfaced through agent CLIs
# (observed via both grok and omp); it is not engine-specific.
OMNIROUTE_503_BLOB = (
    'Internal error: { "message": "API error (status 503 Service Unavailable): '
    'Chat admission capacity is temporarily unavailable. Retry shortly.", '
    '"http_status": 503, "promptUsage": {"inputTokens": 356912}}'
)


# --- classify_transient_failure: transient cases ---
def test_classify_observed_omniroute_503_blob() -> None:
    failure = classify_transient_failure(OMNIROUTE_503_BLOB)
    assert failure is not None
    assert failure.http_status == 503
    # Substantive reason retained; no raw JSON, no duplicate retry advice.
    assert "Chat admission capacity is temporarily unavailable" in failure.message
    assert "Internal error" not in failure.message
    assert "{" not in failure.message
    assert "Retry shortly" not in failure.message


def test_classify_429_rate_limit() -> None:
    failure = classify_transient_failure("HTTP 429: rate limit exceeded")
    assert failure is not None
    assert failure.http_status == 429


def test_classify_overload_phrase() -> None:
    failure = classify_transient_failure("The server is overloaded")
    assert failure is not None
    assert failure.http_status is None


def test_classify_whitespace_and_newlines() -> None:
    failure = classify_transient_failure(
        'Internal\n  error:  {"message": "temporarily\nunavailable", '
        '"http_status": 503}'
    )
    assert failure is not None
    assert failure.http_status == 503
    assert "\n" not in failure.message


def test_classify_malformed_json_falls_back_to_text() -> None:
    # Malformed JSON after the prefix must not raise; classify the raw text.
    failure = classify_transient_failure(
        "Internal error: {not valid json temporarily unavailable"
    )
    assert failure is not None
    assert "temporarily unavailable" in failure.message


def test_classify_phrase_only_no_status() -> None:
    failure = classify_transient_failure("try again later")
    assert failure is not None
    assert failure.http_status is None


def test_classify_status_in_text_without_json() -> None:
    failure = classify_transient_failure("upstream returned status 503")
    assert failure is not None
    assert failure.http_status == 503


def test_classify_empty_message_falls_back_to_default() -> None:
    failure = classify_transient_failure(
        'Internal error: {"http_status": 503, "message": "   "}'
    )
    assert failure is not None
    assert failure.http_status == 503
    assert failure.message  # non-empty default


# --- classify_transient_failure: non-transient cases ---


@pytest.mark.parametrize(
    "text",
    [
        "Couldn't start session: auth failed",
        "HTTP 401 unauthorized",
        "invalid request: bad parameter",
        "cancelled by user",
        "operation timed out",
        "process exited with code 1",
        "please retry the operation later with a credit card",
        "bare retry word",
        "",
        "   ",
    ],
)
def test_classify_non_transient_returns_none(text: str) -> None:
    assert classify_transient_failure(text) is None


# --- format_transient_failure ---


def test_format_with_http_status() -> None:
    failure = TransientFailure(http_status=503, message="Capacity is full.")
    formatted = format_transient_failure("grok", failure)
    assert formatted == (
        "grok upstream is temporarily unavailable (HTTP 503): "
        "Capacity is full. Try again in a few minutes."
    )


def test_format_without_http_status() -> None:
    failure = TransientFailure(http_status=None, message="Overloaded.")
    formatted = format_transient_failure("codex", failure)
    assert "HTTP" not in formatted
    assert formatted == (
        "codex upstream is temporarily unavailable: "
        "Overloaded. Try again in a few minutes."
    )


def test_format_observed_blob_end_to_end() -> None:
    failure = classify_transient_failure(OMNIROUTE_503_BLOB)
    assert failure is not None
    formatted = format_transient_failure("grok", failure)
    assert formatted.startswith("grok upstream is temporarily unavailable (HTTP 503): ")
    assert formatted.endswith(" Try again in a few minutes.")
    assert "{" not in formatted
    assert "Internal error" not in formatted
    assert "Retry shortly" not in formatted


def test_classify_omp_bare_503_prefix() -> None:
    """OMP stream errors start with a bare ``503`` prefix (no http/status keyword)."""
    failure = classify_transient_failure(
        "503 Chat admission capacity is temporarily unavailable. Retry shortly."
    )
    assert failure is not None
    assert failure.http_status == 503
    assert "Chat admission capacity is temporarily unavailable" in failure.message


def test_classify_omp_bare_429_prefix() -> None:
    """Bare ``429`` prefix is also recognized (rate-limit)."""
    failure = classify_transient_failure("429 Rate limit exceeded. Try again later.")
    assert failure is not None
    assert failure.http_status == 429


def test_classify_omp_repeated_reason_deduped() -> None:
    """OMP terminal errors duplicate the capacity reason with suffixes."""
    failure = classify_transient_failure(
        "503 Chat admission capacity is temporarily unavailable. "
        "Retry shortly. retry-after-ms=2000\n"
        "Chat admission capacity is temporarily unavailable. "
        "Retry shortly. (type=server_error param=chat_admission_busy)"
    )
    assert failure is not None
    assert failure.http_status == 503
    # No duplicate reason text
    reason = "Chat admission capacity is temporarily unavailable"
    assert failure.message.count(reason) == 1
    # No retry directive or provider suffix
    assert "retry-after-ms" not in failure.message.lower()
    assert "type=server_error" not in failure.message.lower()


def test_format_omp_bare_503_clean() -> None:
    """OMP bare-503 error formats cleanly with HTTP 503 and no leakage."""
    failure = classify_transient_failure(
        "503 Chat admission capacity is temporarily unavailable. "
        "Retry shortly. retry-after-ms=2000\n"
        "Chat admission capacity is temporarily unavailable. "
        "Retry shortly. (type=server_error param=chat_admission_busy)"
    )
    assert failure is not None
    formatted = format_transient_failure("omp", failure)
    assert formatted.startswith("omp upstream is temporarily unavailable (HTTP 503): ")
    assert formatted.endswith(" Try again in a few minutes.")
    assert "{" not in formatted
    assert "retry-after-ms" not in formatted.lower()
    assert "Internal error" not in formatted
    assert "type=server_error" not in formatted
    assert "rc=" not in formatted
    reason = "Chat admission capacity is temporarily unavailable"
    assert formatted.count(reason) == 1
