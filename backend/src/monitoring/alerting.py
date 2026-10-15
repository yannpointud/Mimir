"""
Fingerprinted SMTP error alerting.

An in-process ``logging.Handler`` subclass that captures ERROR+ records from the
existing ``app_logger``, groups them by a fingerprint of (exception type, module,
function, line), deduplicates repeats within a throttle window, and schedules
exactly one grouped SMTP alert per fingerprint per window via the existing
``email_service`` client. No external service, no log-file re-parsing.
"""

import asyncio
import hashlib
import logging
import time

from src.config import settings

logger = logging.getLogger(__name__)


class FingerprintAlertHandler(logging.Handler):
    """Captures ERROR+ records, deduplicates by fingerprint, and schedules
    exactly one grouped SMTP alert per fingerprint per throttle window.

    Fingerprint = sha256(exception type + module + function + line)[:16].
    Two different error MESSAGES at the same call site with the same exception
    type collapse to the same fingerprint (intentional: alerts are grouped by
    *where/what*, not by message text).
    """

    def __init__(self, throttle_seconds: int, level=logging.ERROR):
        super().__init__(level=level)
        self._throttle_seconds = throttle_seconds
        # Last time (epoch seconds) an alert was sent per fingerprint.
        self._last_sent: dict[str, float] = {}
        # Occurrence counter per fingerprint since the last sent alert.
        self._counts: dict[str, int] = {}
        # Strong references to in-flight send tasks. asyncio only holds a WEAK
        # reference to a task from create_task(), so without this an alert
        # coroutine can be garbage-collected mid-flight before it sends. Each
        # task removes itself on completion (see emit()).
        self._pending_tasks: set = set()

    def _fingerprint(self, record: logging.LogRecord) -> str:
        """Hash the call site + exception type into a short stable fingerprint."""
        exc_type = (
            record.exc_info[0].__name__ if record.exc_info and record.exc_info[0] else "Error"
        )
        raw = f"{exc_type}:{record.module}:{record.funcName}:{record.lineno}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def _should_alert(self, fingerprint: str, now: float) -> bool:
        """Pure, synchronous throttle decision (deterministically unit-testable).

        Increments the occurrence counter for the fingerprint. Returns False when
        a previous alert for the same fingerprint is still within the throttle
        window (deduped); otherwise records ``now`` as the last-sent time and
        returns True.
        """
        self._counts[fingerprint] = self._counts.get(fingerprint, 0) + 1

        last = self._last_sent.get(fingerprint, 0)
        if now - last < self._throttle_seconds:
            return False  # deduped: already alerted for this fingerprint this window

        self._last_sent[fingerprint] = now
        return True

    def emit(self, record: logging.LogRecord) -> None:
        """Non-blocking: decide via the pure throttle, then fire-and-forget the send.

        ``emit`` is called from the logging call site (potentially a hot request
        path), so it must never perform blocking smtplib I/O inline.
        """
        fp = self._fingerprint(record)
        now = time.time()

        if not self._should_alert(fp, now):
            return

        # Snapshot the occurrence count for this window and reset it.
        occurrences = self._counts[fp]
        self._counts[fp] = 0

        try:
            loop = asyncio.get_running_loop()
            # Keep a strong reference until the task finishes so it cannot be
            # garbage-collected mid-send (asyncio holds only a weak ref).
            task = loop.create_task(self._send_alert(fp, record, occurrences))
            self._pending_tasks.add(task)
            task.add_done_callback(self._pending_tasks.discard)
        except RuntimeError:
            # No running event loop (e.g. sync worker thread) -- log and skip;
            # never risk blocking the caller on smtplib I/O.
            logger.warning("FingerprintAlertHandler: no event loop, dropped alert for %s", fp)

    async def _send_alert(
        self, fingerprint: str, record: logging.LogRecord, occurrences: int
    ) -> None:
        """Send one grouped alert. Body carries only non-sensitive fields."""
        # Local import to avoid an import cycle at module load time.
        from src.email_service.smtp_client import email_service

        subject = (
            f"Mimir error alert [{fingerprint}] {record.module}.{record.funcName}:{record.lineno}"
        )
        # Body limited to message + location + fingerprint + occurrence count.
        # No traceback, no request payload, no settings/secret interpolation
        # (information disclosure).
        message = (
            f"Fingerprint: {fingerprint}\n"
            f"Location: {record.module}.{record.funcName}:{record.lineno}\n"
            f"Occurrences this window: {occurrences}\n"
            f"Message: {record.getMessage()}\n"
        )
        try:
            await email_service.send_notification_email(
                to_email=email_service.escalation_email,
                subject=subject,
                message=message,
            )
        except Exception as e:
            # Follow the existing try-except-log convention; an alert failure
            # must never propagate back into the logging subsystem.
            logger.error(f"Failed to send fingerprinted error alert {fingerprint}: {e}")


def setup_alerting() -> None:
    """Attach a single FingerprintAlertHandler to the existing app_logger.

    No-op when alerting is disabled or the email service is not configured.
    Idempotent: guards against double-registration so repeated calls (e.g. on a
    reloading dev server) do not attach a second handler.
    """
    # Local import to avoid an import cycle at module load time.
    from src.email_service.smtp_client import email_service
    from src.monitoring.logger import app_logger

    if not settings.alerting_enabled:
        logger.info("Error alerting disabled (settings.alerting_enabled is False)")
        return

    if not email_service.get_configuration_status()["configured"]:
        logger.info("Error alerting disabled: email service is not configured")
        return

    # Guard against double-registration.
    if any(isinstance(h, FingerprintAlertHandler) for h in app_logger.handlers):
        return

    handler = FingerprintAlertHandler(throttle_seconds=settings.alert_throttle_seconds)
    app_logger.addHandler(handler)
    logger.info(
        "Error alerting enabled (throttle window: %ss)",
        settings.alert_throttle_seconds,
    )
