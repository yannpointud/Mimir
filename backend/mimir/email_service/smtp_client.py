"""
SMTP client for sending escalation emails.

This module provides asynchronous email sending capabilities for
escalating user conversations to human support agents.
"""

import logging
from datetime import datetime
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate
from typing import Any

import aiosmtplib
from jinja2 import Environment, PackageLoader, select_autoescape

from mimir.config import settings

logger = logging.getLogger(__name__)

# Autoescaping: questions and chat history come from anonymous users and must
# never inject markup into the email read by the support team.
_TEMPLATES = Environment(
    loader=PackageLoader("mimir.email_service"), autoescape=select_autoescape(["html"])
)


class EmailService:
    """Handles email sending for escalation and notifications."""

    def __init__(self) -> None:
        self.smtp_host = settings.smtp_host
        self.smtp_port = settings.smtp_port
        self.smtp_user = settings.smtp_user
        self.smtp_password = settings.smtp_password
        self.smtp_use_tls = settings.smtp_use_tls
        self.escalation_email = settings.escalation_email
        self.from_email = settings.smtp_user

        # Validate configuration
        if not all([self.smtp_host, self.smtp_user, self.escalation_email]):
            logger.warning("Email service not fully configured - some features will be disabled")

    async def send_escalation_email(
        self,
        user_question: str,
        chat_history: list[dict[str, Any]],
        user_info: dict[str, Any] | None = None,
        context_sources: list[str] | None = None,
    ) -> bool:
        """Send escalation email to support team."""
        if not self._is_configured():
            logger.error("Email service not configured for escalation")
            return False

        # Generate email content
        subject = f"Mimir Chat Escalation - {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        html_content = self._generate_escalation_html(
            user_question, chat_history, user_info, context_sources
        )
        text_content = self._generate_escalation_text(
            user_question, chat_history, user_info, context_sources
        )

        # Send email
        success = await self._send_email(
            to_emails=[self.escalation_email],
            subject=subject,
            html_content=html_content,
            text_content=text_content,
        )

        if success:
            logger.info(f"Escalation email sent successfully to {self.escalation_email}")
        else:
            logger.error("Failed to send escalation email")

        return success

    async def send_notification_email(
        self, to_email: str, subject: str, message: str, is_html: bool = False
    ) -> bool:
        """Send a general notification email."""
        if not self._is_configured():
            logger.error("Email service not configured")
            return False

        if is_html:
            success = await self._send_email(
                to_emails=[to_email], subject=subject, html_content=message
            )
        else:
            success = await self._send_email(
                to_emails=[to_email], subject=subject, text_content=message
            )

        if success:
            logger.info(f"Notification email sent to {to_email}")

        return success

    async def _send_email(
        self,
        to_emails: list[str],
        subject: str,
        text_content: str | None = None,
        html_content: str | None = None,
        attachments: list[dict[str, Any]] | None = None,
    ) -> bool:
        """Internal method to send email via SMTP."""
        try:
            # Create message
            message = MIMEMultipart("alternative")
            message["From"] = self.from_email
            message["To"] = ", ".join(to_emails)
            message["Subject"] = subject
            message["Date"] = formatdate(localtime=True)

            # Add text content
            if text_content:
                text_part = MIMEText(text_content, "plain", "utf-8")
                message.attach(text_part)

            # Add HTML content
            if html_content:
                html_part = MIMEText(html_content, "html", "utf-8")
                message.attach(html_part)

            # Add attachments
            if attachments:
                for attachment in attachments:
                    self._add_attachment(message, attachment)

            # Send email using aiosmtplib for async operation
            smtp_client = aiosmtplib.SMTP(
                hostname=self.smtp_host, port=self.smtp_port, use_tls=self.smtp_use_tls
            )

            await smtp_client.connect()

            if self.smtp_user and self.smtp_password:
                await smtp_client.login(self.smtp_user, self.smtp_password)

            await smtp_client.send_message(message)
            await smtp_client.quit()

            return True

        except (aiosmtplib.SMTPException, OSError, TimeoutError) as e:
            logger.error(f"SMTP send error: {e}")
            return False

    def _add_attachment(self, message: MIMEMultipart, attachment: dict[str, Any]) -> None:
        """Add an attachment (dict with 'filename', 'content', 'mime_type') to the message."""
        part = MIMEBase("application", "octet-stream")
        part.set_payload(attachment["content"])
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f"attachment; filename= {attachment['filename']}")
        message.attach(part)

    def _generate_escalation_html(
        self,
        user_question: str,
        chat_history: list[dict[str, Any]],
        user_info: dict[str, Any] | None,
        context_sources: list[str] | None,
    ) -> str:
        return _TEMPLATES.get_template("escalation.html").render(
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            user_question=user_question,
            chat_history=chat_history,
            context_sources=context_sources,
            user_info=user_info,
        )

    def _generate_escalation_text(
        self,
        user_question: str,
        chat_history: list[dict[str, Any]],
        user_info: dict[str, Any] | None,
        context_sources: list[str] | None,
    ) -> str:
        content = []
        content.append("MIMIR CHAT ESCALATION")
        content.append("=" * 50)
        content.append(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        content.append("Status: User requested human assistance")
        content.append("")

        content.append("CURRENT QUESTION:")
        content.append("-" * 20)
        content.append(user_question)
        content.append("")

        if chat_history:
            content.append("RECENT CHAT HISTORY:")
            content.append("-" * 20)
            for message in chat_history[-5:]:
                content.append(
                    f"{message.get('type', 'unknown').upper()}: {message.get('content', '')[:200]}"
                )
            content.append("")

        if context_sources:
            content.append("REFERENCE SOURCES:")
            content.append("-" * 20)
            for source in context_sources:
                content.append(f"- {source}")
            content.append("")

        if user_info:
            content.append("USER INFORMATION:")
            content.append("-" * 20)
            for key, value in user_info.items():
                content.append(f"{key.upper()}: {value}")
            content.append("")

        content.append("NEXT STEPS:")
        content.append("-" * 20)
        content.append("1. Review the user's question and chat history")
        content.append("2. Check the reference sources for relevant information")
        content.append("3. Provide a personalized response to the user")
        content.append("4. Consider updating the documentation if needed")
        content.append("")

        content.append("This escalation was automatically generated by Mimir chatbot system.")

        return "\n".join(content)

    def _is_configured(self) -> bool:
        return bool(self.smtp_host and self.smtp_user and self.escalation_email)

    def get_configuration_status(self) -> dict[str, Any]:
        """Get email service configuration status."""
        return {
            "configured": self._is_configured(),
            "smtp_host": bool(self.smtp_host),
            "smtp_user": bool(self.smtp_user),
            "escalation_email": bool(self.escalation_email),
            "smtp_port": self.smtp_port,
            "smtp_use_tls": self.smtp_use_tls,
        }


# Global email service instance
email_service = EmailService()
