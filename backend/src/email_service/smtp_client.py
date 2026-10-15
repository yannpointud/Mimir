"""
SMTP client for sending escalation emails.

This module provides asynchronous email sending capabilities for
escalating user conversations to human support agents.
"""

from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from email.utils import formatdate
from typing import Any
from datetime import datetime
import logging
import aiosmtplib
from jinja2 import Template, TemplateError

from src.config import settings

logger = logging.getLogger(__name__)


class EmailService:
    """Handles email sending for escalation and notifications."""

    def __init__(self):
        """Initialize email service with SMTP configuration."""
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
        """
        Send escalation email to support team.

        Args:
            user_question: The question that triggered escalation
            chat_history: Recent chat conversation history
            user_info: Optional user information (IP, session, etc.)
            context_sources: Sources used to answer the question

        Returns:
            bool: True if email sent successfully
        """
        try:
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

        except (TemplateError, TypeError, KeyError, AttributeError, ValueError) as e:
            # Rendering failure on unexpected chat history or user info values
            logger.error(f"Error sending escalation email: {e}")
            return False

    async def send_notification_email(
        self, to_email: str, subject: str, message: str, is_html: bool = False
    ) -> bool:
        """
        Send a general notification email.

        Args:
            to_email: Recipient email address
            subject: Email subject
            message: Email message content
            is_html: Whether message is HTML formatted

        Returns:
            bool: True if sent successfully
        """
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
        """
        Internal method to send email via SMTP.

        Args:
            to_emails: List of recipient email addresses
            subject: Email subject
            text_content: Plain text content
            html_content: HTML content
            attachments: Optional list of attachments

        Returns:
            bool: True if sent successfully
        """
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

        except (aiosmtplib.SMTPException, OSError, TimeoutError, ValueError, TypeError) as e:
            # SMTP protocol or network failure, or a header/body MIME rejects
            logger.error(f"SMTP send error: {e}")
            return False

    def _add_attachment(self, message: MIMEMultipart, attachment: dict[str, Any]):
        """
        Add attachment to email message.

        Args:
            message: The email message object
            attachment: Attachment info dict with 'filename', 'content', 'mime_type'
        """
        try:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(attachment["content"])
            encoders.encode_base64(part)
            part.add_header(
                "Content-Disposition", f"attachment; filename= {attachment['filename']}"
            )
            message.attach(part)
        except (KeyError, TypeError, ValueError) as e:
            logger.error(f"Error adding attachment: {e}")

    def _generate_escalation_html(
        self,
        user_question: str,
        chat_history: list[dict[str, Any]],
        user_info: dict[str, Any] | None,
        context_sources: list[str] | None,
    ) -> str:
        """Generate HTML content for escalation email."""
        template_str = """
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <title>Mimir Chat Escalation</title>
            <style>
                body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
                .header { background-color: #f4f4f4; padding: 20px; border-radius: 5px; }
                .section { margin: 20px 0; }
                .question { background-color: #e8f4fd; padding: 15px; border-radius: 5px; }
                .history { background-color: #f9f9f9; padding: 15px; border-radius: 5px; }
                .sources { background-color: #fff3cd; padding: 15px; border-radius: 5px; }
                .user-info { background-color: #f8f9fa; padding: 15px; border-radius: 5px; }
                .message { margin: 10px 0; padding: 10px; border-left: 3px solid #ddd; }
                .user-message { border-left-color: #007bff; }
                .assistant-message { border-left-color: #28a745; }
                ul { padding-left: 20px; }
            </style>
        </head>
        <body>
            <div class="header">
                <h2>🔔 Mimir Chat Escalation</h2>
                <p><strong>Time:</strong> {{ timestamp }}</p>
                <p><strong>Status:</strong> User requested human assistance</p>
            </div>

            <div class="section">
                <h3>❓ Current Question</h3>
                <div class="question">
                    <p><strong>Question:</strong> {{ user_question }}</p>
                </div>
            </div>

            {% if chat_history %}
            <div class="section">
                <h3>💬 Recent Chat History</h3>
                <div class="history">
                    {% for message in chat_history[-5:] %}
                    <div class="message {{ 'user-message' if message.type == 'user' else 'assistant-message' }}">
                        <strong>{{ message.type|title }}:</strong> {{ message.content[:200] }}
                        {% if message.content|length > 200 %}...{% endif %}
                    </div>
                    {% endfor %}
                </div>
            </div>
            {% endif %}

            {% if context_sources %}
            <div class="section">
                <h3>📚 Reference Sources</h3>
                <div class="sources">
                    <p>The following documents were used as context:</p>
                    <ul>
                    {% for source in context_sources %}
                        <li>{{ source }}</li>
                    {% endfor %}
                    </ul>
                </div>
            </div>
            {% endif %}

            {% if user_info %}
            <div class="section">
                <h3>👤 User Information</h3>
                <div class="user-info">
                    {% for key, value in user_info.items() %}
                    <p><strong>{{ key|title }}:</strong> {{ value }}</p>
                    {% endfor %}
                </div>
            </div>
            {% endif %}

            <div class="section">
                <h3>📝 Next Steps</h3>
                <ul>
                    <li>Review the user's question and chat history</li>
                    <li>Check the reference sources for relevant information</li>
                    <li>Provide a personalized response to the user</li>
                    <li>Consider updating the documentation if needed</li>
                </ul>
            </div>

            <div class="section">
                <p><em>This escalation was automatically generated by Mimir chatbot system.</em></p>
            </div>
        </body>
        </html>
        """

        template = Template(template_str)
        return template.render(
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
        """Generate plain text content for escalation email."""
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
        """Check if email service is properly configured."""
        return bool(self.smtp_host and self.smtp_user and self.escalation_email)

    def get_configuration_status(self) -> dict[str, Any]:
        """
        Get email service configuration status.

        Returns:
            dict: Configuration status information
        """
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
