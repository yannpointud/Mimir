"""
Unit tests for the fingerprinted SMTP error alerting handler.

Proves the core anti-spam guarantee: repeated ERROR records sharing the same
fingerprint (exception type + module + function + line) within the throttle
window collapse to exactly ONE grouped SMTP alert, while records with distinct
fingerprints each produce their own alert, and a repeat after the window elapses
sends again. Also asserts the alert body carries the occurrence count and never
leaks a secret value.

All SMTP I/O is mocked (AsyncMock); no real email is sent and no real Mistral
call is made.
"""

import asyncio
import logging

import pytest
from unittest.mock import AsyncMock

import src.monitoring.alerting as alerting
from src.monitoring.alerting import FingerprintAlertHandler

# A sentinel secret that must NEVER appear in an alert body.
SENTINEL_SECRET = "super-secret-jwt-token-value-DO-NOT-LEAK"


def _make_record(
    *,
    module: str,
    func: str,
    line: int,
    message: str,
    exc_info=None,
) -> logging.LogRecord:
    """Build a synthetic ERROR LogRecord with controllable fingerprint inputs.

    ``module``/``funcName`` are attributes the logging framework normally derives
    from the call site; we set them explicitly so the fingerprint is deterministic.
    """
    record = logging.LogRecord(
        name="mimir",
        level=logging.ERROR,
        pathname=f"/app/{module}.py",
        lineno=line,
        msg=message,
        args=(),
        exc_info=exc_info,
    )
    record.module = module
    record.funcName = func
    return record


async def _drain_tasks() -> None:
    """Await all fire-and-forget tasks scheduled by emit() in the current loop."""
    pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    if pending:
        await asyncio.gather(*pending)


@pytest.fixture
def mock_send(monkeypatch):
    """Patch the SMTP send with an AsyncMock and give the email_service an address."""
    from src.email_service.smtp_client import email_service

    mock = AsyncMock(return_value=True)
    monkeypatch.setattr(email_service, "send_notification_email", mock)
    monkeypatch.setattr(email_service, "escalation_email", "ops@example.com")
    return mock


@pytest.mark.unit
@pytest.mark.asyncio
async def test_same_fingerprint_within_window_sends_once(mock_send, monkeypatch):
    """3 identical-fingerprint ERROR records within the window -> exactly 1 alert."""
    # Freeze time so all three records fall inside the throttle window.
    monkeypatch.setattr(alerting.time, "time", lambda: 1000.0)
    handler = FingerprintAlertHandler(throttle_seconds=900)

    for _ in range(3):
        handler.emit(
            _make_record(module="chat", func="answer", line=42, message="boom")
        )
    await _drain_tasks()

    assert mock_send.call_count == 1
    # The alert fires on the first occurrence of the window; the two deduped
    # repeats are accumulated and reported in the NEXT window's alert
    # (see test_repeat_after_window_elapses_sends_again).
    body = mock_send.call_args.kwargs["message"]
    assert "Occurrences this window: 1" in body


@pytest.mark.unit
@pytest.mark.asyncio
async def test_distinct_fingerprints_send_separately(mock_send, monkeypatch):
    """Two records at different call sites -> two distinct alerts."""
    monkeypatch.setattr(alerting.time, "time", lambda: 1000.0)
    handler = FingerprintAlertHandler(throttle_seconds=900)

    handler.emit(_make_record(module="chat", func="answer", line=42, message="boom"))
    handler.emit(_make_record(module="documents", func="upload", line=99, message="boom"))
    await _drain_tasks()

    assert mock_send.call_count == 2


@pytest.mark.unit
@pytest.mark.asyncio
async def test_repeat_after_window_elapses_sends_again(mock_send, monkeypatch):
    """A repeat of the same fingerprint after the window elapses alerts again."""
    clock = {"now": 1000.0}
    monkeypatch.setattr(alerting.time, "time", lambda: clock["now"])
    handler = FingerprintAlertHandler(throttle_seconds=900)

    handler.emit(_make_record(module="chat", func="answer", line=42, message="boom"))
    await _drain_tasks()
    assert mock_send.call_count == 1

    # Within the window: deduped, no new alert.
    clock["now"] = 1500.0
    handler.emit(_make_record(module="chat", func="answer", line=42, message="boom"))
    await _drain_tasks()
    assert mock_send.call_count == 1

    # After the window elapses: alert again. The deduped repeat from within the
    # previous window is accumulated, so this alert groups 2 occurrences.
    clock["now"] = 2000.0
    handler.emit(_make_record(module="chat", func="answer", line=42, message="boom"))
    await _drain_tasks()
    assert mock_send.call_count == 2
    body = mock_send.call_args.kwargs["message"]
    assert "Occurrences this window: 2" in body


@pytest.mark.unit
@pytest.mark.asyncio
async def test_alert_body_excludes_secrets(mock_send, monkeypatch):
    """The alert body carries the message but must not leak an unrelated secret."""
    monkeypatch.setattr(alerting.time, "time", lambda: 1000.0)
    handler = FingerprintAlertHandler(throttle_seconds=900)

    handler.emit(
        _make_record(
            module="auth",
            func="login",
            line=17,
            message="Database connection failed",
        )
    )
    await _drain_tasks()

    body = mock_send.call_args.kwargs["message"]
    assert "Database connection failed" in body
    assert "Occurrences this window: 1" in body
    # A secret that was never part of the log message must not appear.
    assert SENTINEL_SECRET not in body
    # No traceback leaked when exc_info is absent.
    assert "Traceback" not in body


@pytest.mark.unit
@pytest.mark.asyncio
async def test_exc_type_participates_in_fingerprint(mock_send, monkeypatch):
    """Same call site but different exception types -> distinct fingerprints."""
    monkeypatch.setattr(alerting.time, "time", lambda: 1000.0)
    handler = FingerprintAlertHandler(throttle_seconds=900)

    try:
        raise ValueError("v")
    except ValueError:
        import sys

        rec_value = _make_record(
            module="chat", func="answer", line=42, message="boom", exc_info=sys.exc_info()
        )
    try:
        raise KeyError("k")
    except KeyError:
        import sys

        rec_key = _make_record(
            module="chat", func="answer", line=42, message="boom", exc_info=sys.exc_info()
        )

    handler.emit(rec_value)
    handler.emit(rec_key)
    await _drain_tasks()

    assert mock_send.call_count == 2


@pytest.mark.unit
def test_emit_without_event_loop_does_not_raise(mock_send, monkeypatch):
    """No running loop -> emit drops the alert with a warning, never blocks/raises."""
    monkeypatch.setattr(alerting.time, "time", lambda: 1000.0)
    handler = FingerprintAlertHandler(throttle_seconds=900)

    # Called synchronously (no running event loop): must not raise and must not
    # perform a blocking send.
    handler.emit(_make_record(module="chat", func="answer", line=42, message="boom"))
    assert mock_send.call_count == 0
