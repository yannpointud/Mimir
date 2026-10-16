"""
Tests unitaires pour le service email.

Ce module teste les fonctionnalités d'envoi d'emails pour les escalations
et notifications du système Mimir.
"""

import pytest
from unittest.mock import patch, AsyncMock

from backend.src.email_service.smtp_client import EmailService


class TestEmailServiceInit:
    """Tests pour l'initialisation du service email."""

    @patch("backend.src.email_service.smtp_client.settings")
    def test_init_with_full_config(self, mock_settings):
        """Test d'initialisation avec configuration complète."""
        mock_settings.smtp_host = "smtp.example.com"
        mock_settings.smtp_port = 587
        mock_settings.smtp_user = "user@example.com"
        mock_settings.smtp_password = "password"
        mock_settings.smtp_use_tls = True
        mock_settings.escalation_email = "support@example.com"

        service = EmailService()

        assert service.smtp_host == "smtp.example.com"
        assert service.smtp_port == 587
        assert service.smtp_user == "user@example.com"
        assert service.smtp_password == "password"
        assert service.smtp_use_tls is True
        assert service.escalation_email == "support@example.com"
        assert service.from_email == "user@example.com"

    @patch("backend.src.email_service.smtp_client.settings")
    def test_init_with_incomplete_config(self, mock_settings):
        """Test d'initialisation avec configuration incomplète."""
        mock_settings.smtp_host = None
        mock_settings.smtp_port = 587
        mock_settings.smtp_user = "user@example.com"
        mock_settings.smtp_password = "password"
        mock_settings.smtp_use_tls = True
        mock_settings.escalation_email = "support@example.com"

        with patch("backend.src.email_service.smtp_client.logger") as mock_logger:
            EmailService()
            mock_logger.warning.assert_called_once()


class TestEmailServiceConfiguration:
    """Tests pour la configuration du service email."""

    @pytest.fixture
    def configured_email_service(self):
        """Service email configuré."""
        with patch("backend.src.email_service.smtp_client.settings") as mock_settings:
            mock_settings.smtp_host = "smtp.example.com"
            mock_settings.smtp_port = 587
            mock_settings.smtp_user = "user@example.com"
            mock_settings.smtp_password = "password"
            mock_settings.smtp_use_tls = True
            mock_settings.escalation_email = "support@example.com"
            return EmailService()

    @pytest.fixture
    def unconfigured_email_service(self):
        """Service email non configuré."""
        with patch("backend.src.email_service.smtp_client.settings") as mock_settings:
            mock_settings.smtp_host = None
            mock_settings.smtp_port = 587
            mock_settings.smtp_user = "user@example.com"
            mock_settings.smtp_password = "password"
            mock_settings.smtp_use_tls = True
            mock_settings.escalation_email = "support@example.com"
            return EmailService()

    def test_is_configured_true(self, configured_email_service):
        """Test de vérification de configuration valide."""
        assert configured_email_service._is_configured() is True

    def test_is_configured_false_missing_host(self, unconfigured_email_service):
        """Test avec host manquant."""
        assert unconfigured_email_service._is_configured() is False

    def test_is_configured_false_missing_user(self):
        """Test avec utilisateur manquant."""
        with patch("backend.src.email_service.smtp_client.settings") as mock_settings:
            mock_settings.smtp_host = "smtp.example.com"
            mock_settings.smtp_port = 587
            mock_settings.smtp_user = None
            mock_settings.smtp_password = "password"
            mock_settings.smtp_use_tls = True
            mock_settings.escalation_email = "support@example.com"
            service = EmailService()
            assert service._is_configured() is False

    def test_is_configured_false_missing_escalation_email(self):
        """Test avec email d'escalation manquant."""
        with patch("backend.src.email_service.smtp_client.settings") as mock_settings:
            mock_settings.smtp_host = "smtp.example.com"
            mock_settings.smtp_port = 587
            mock_settings.smtp_user = "user@example.com"
            mock_settings.smtp_password = "password"
            mock_settings.smtp_use_tls = True
            mock_settings.escalation_email = None
            service = EmailService()
            assert service._is_configured() is False


class TestSendEscalationEmail:
    """Tests pour l'envoi d'emails d'escalation."""

    @pytest.fixture
    def email_service(self):
        """Service email configuré."""
        with patch("backend.src.email_service.smtp_client.settings") as mock_settings:
            mock_settings.smtp_host = "smtp.example.com"
            mock_settings.smtp_port = 587
            mock_settings.smtp_user = "user@example.com"
            mock_settings.smtp_password = "password"
            mock_settings.smtp_use_tls = True
            mock_settings.escalation_email = "support@example.com"
            return EmailService()

    @pytest.mark.asyncio
    async def test_send_escalation_email_success(self, email_service):
        """Test d'envoi d'escalation réussi."""
        with patch.object(email_service, "_send_email", return_value=True) as mock_send:
            result = await email_service.send_escalation_email(
                user_question="How do I reset my password?",
                chat_history=[
                    {"type": "user", "content": "I forgot my password"},
                    {"type": "assistant", "content": "I can help you with that..."},
                ],
                user_info={"ip": "192.168.1.1", "session": "abc123"},
                context_sources=["user_manual.pdf", "faq.md"],
            )

            assert result is True
            mock_send.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_escalation_email_not_configured(self):
        """Test d'envoi avec service non configuré."""
        with patch("backend.src.email_service.smtp_client.settings") as mock_settings:
            mock_settings.smtp_host = None
            mock_settings.smtp_port = 587
            mock_settings.smtp_user = None
            mock_settings.smtp_password = "password"
            mock_settings.smtp_use_tls = True
            mock_settings.escalation_email = None

            service = EmailService()
            result = await service.send_escalation_email(
                user_question="How do I reset my password?", chat_history=[]
            )

            assert result is False

    @pytest.mark.asyncio
    async def test_send_escalation_email_send_failure(self, email_service):
        """Test d'échec d'envoi."""
        with patch.object(email_service, "_send_email", return_value=False) as mock_send:
            result = await email_service.send_escalation_email(
                user_question="How do I reset my password?", chat_history=[]
            )

            assert result is False
            mock_send.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_escalation_email_exception(self, email_service):
        """Test de gestion d'exception."""
        with patch.object(email_service, "_send_email", side_effect=Exception("SMTP Error")):
            result = await email_service.send_escalation_email(
                user_question="How do I reset my password?", chat_history=[]
            )

            assert result is False

    @pytest.mark.asyncio
    async def test_send_escalation_email_minimal_args(self, email_service):
        """Test avec arguments minimaux."""
        with patch.object(email_service, "_send_email", return_value=True) as mock_send:
            result = await email_service.send_escalation_email(
                user_question="Help me", chat_history=[]
            )

            assert result is True
            mock_send.assert_called_once()


class TestSendEmail:
    """Tests pour la méthode _send_email."""

    @pytest.fixture
    def email_service(self):
        """Fixture pour EmailService configuré."""
        with patch("backend.src.email_service.smtp_client.settings") as mock_settings:
            mock_settings.smtp_host = "smtp.example.com"
            mock_settings.smtp_port = 587
            mock_settings.smtp_user = "user@example.com"
            mock_settings.smtp_password = "password"
            mock_settings.smtp_use_tls = True
            mock_settings.escalation_email = "support@example.com"
            return EmailService()

    @pytest.mark.asyncio
    async def test_send_email_success(self, email_service):
        """Test d'envoi d'email réussi."""
        with patch("backend.src.email_service.smtp_client.aiosmtplib.SMTP") as mock_smtp_class:
            mock_smtp = AsyncMock()
            mock_smtp_class.return_value = mock_smtp

            result = await email_service._send_email(
                to_emails=["recipient@example.com"],
                subject="Test Subject",
                html_content="<html>Test</html>",
                text_content="Test text",
            )

            assert result is True
            mock_smtp.connect.assert_called_once()
            mock_smtp.login.assert_called_once()
            mock_smtp.send_message.assert_called_once()
            mock_smtp.quit.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_email_multiple_recipients(self, email_service):
        """Test d'envoi à plusieurs destinataires."""
        with patch("backend.src.email_service.smtp_client.aiosmtplib.SMTP") as mock_smtp_class:
            mock_smtp = AsyncMock()
            mock_smtp_class.return_value = mock_smtp

            result = await email_service._send_email(
                to_emails=["recipient1@example.com", "recipient2@example.com"],
                subject="Test Subject",
                html_content="<html>Test</html>",
                text_content="Test text",
            )

            assert result is True
            mock_smtp.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_email_exception(self, email_service):
        """Test de gestion d'exception."""
        with patch("backend.src.email_service.smtp_client.aiosmtplib.SMTP") as mock_smtp_class:
            mock_smtp_class.side_effect = Exception("Connection failed")

            result = await email_service._send_email(
                to_emails=["recipient@example.com"],
                subject="Test Subject",
                text_content="Test text",
            )

            assert result is False

    @pytest.mark.asyncio
    async def test_send_email_with_attachments(self, email_service):
        """Test d'envoi avec pièces jointes."""
        attachments = [
            {"filename": "document.pdf", "content": b"PDF content", "mime_type": "application/pdf"}
        ]

        with patch("backend.src.email_service.smtp_client.aiosmtplib.SMTP") as mock_smtp_class:
            mock_smtp = AsyncMock()
            mock_smtp_class.return_value = mock_smtp

            result = await email_service._send_email(
                to_emails=["recipient@example.com"],
                subject="Test Subject with Attachment",
                text_content="Test text",
                attachments=attachments,
            )

            assert result is True
            mock_smtp.send_message.assert_called_once()


class TestContentGeneration:
    """Tests pour la génération de contenu d'email."""

    @pytest.fixture
    def email_service(self):
        """Service email configuré."""
        with patch("backend.src.email_service.smtp_client.settings") as mock_settings:
            mock_settings.smtp_host = "smtp.example.com"
            mock_settings.smtp_port = 587
            mock_settings.smtp_user = "user@example.com"
            mock_settings.smtp_password = "password"
            mock_settings.smtp_use_tls = True
            mock_settings.escalation_email = "support@example.com"
            return EmailService()

    def test_generate_escalation_html(self, email_service):
        """Test de génération HTML."""
        html = email_service._generate_escalation_html(
            user_question="How do I reset my password?",
            chat_history=[
                {"type": "user", "content": "I forgot my password"},
                {"type": "assistant", "content": "I can help you with that..."},
            ],
            user_info={"ip": "192.168.1.1"},
            context_sources=["user_manual.pdf"],
        )

        assert "How do I reset my password?" in html
        assert "I forgot my password" in html
        assert "user_manual.pdf" in html
        assert "192.168.1.1" in html
        assert "<html>" in html

    def test_generate_escalation_text(self, email_service):
        """Test de génération texte."""
        text = email_service._generate_escalation_text(
            user_question="How do I reset my password?",
            chat_history=[
                {"type": "user", "content": "I forgot my password"},
                {"type": "assistant", "content": "I can help you with that..."},
            ],
            user_info={"ip": "192.168.1.1"},
            context_sources=["user_manual.pdf"],
        )

        assert "How do I reset my password?" in text
        assert "I forgot my password" in text
        assert "user_manual.pdf" in text
        assert "192.168.1.1" in text
        assert "MIMIR CHAT ESCALATION" in text

    def test_generate_escalation_html_minimal(self, email_service):
        """Test de génération HTML avec données minimales."""
        html = email_service._generate_escalation_html(
            user_question="Help me", chat_history=[], user_info=None, context_sources=None
        )

        assert "Help me" in html
        assert "<html>" in html

    def test_generate_escalation_text_minimal(self, email_service):
        """Test de génération texte avec données minimales."""
        text = email_service._generate_escalation_text(
            user_question="Help me", chat_history=[], user_info=None, context_sources=None
        )

        assert "Help me" in text
        assert "MIMIR CHAT ESCALATION" in text

    def test_format_chat_history_html(self, email_service):
        """Test de formatage de l'historique en HTML."""
        chat_history = [
            {"type": "user", "content": "First message"},
            {"type": "assistant", "content": "Response message"},
            {"type": "user", "content": "Follow-up question"},
        ]

        html = email_service._generate_escalation_html(
            user_question="Question",
            chat_history=chat_history,
            user_info=None,
            context_sources=None,
        )

        assert "First message" in html
        assert "Response message" in html
        assert "Follow-up question" in html

    def test_format_chat_history_text(self, email_service):
        """Test de formatage de l'historique en texte."""
        chat_history = [
            {"type": "user", "content": "First message"},
            {"type": "assistant", "content": "Response message"},
            {"type": "user", "content": "Follow-up question"},
        ]

        text = email_service._generate_escalation_text(
            user_question="Question",
            chat_history=chat_history,
            user_info=None,
            context_sources=None,
        )

        assert "First message" in text
        assert "Response message" in text
        assert "Follow-up question" in text

    def test_format_chat_history_empty(self, email_service):
        """Test avec historique vide."""
        html = email_service._generate_escalation_html(
            user_question="Question", chat_history=[], user_info=None, context_sources=None
        )

        text = email_service._generate_escalation_text(
            user_question="Question", chat_history=[], user_info=None, context_sources=None
        )

        assert "Question" in html
        assert "Question" in text


class TestNotificationEmail:
    """Tests pour l'envoi d'emails de notification."""

    @pytest.fixture
    def email_service(self):
        """Service email configuré."""
        with patch("backend.src.email_service.smtp_client.settings") as mock_settings:
            mock_settings.smtp_host = "smtp.example.com"
            mock_settings.smtp_port = 587
            mock_settings.smtp_user = "user@example.com"
            mock_settings.smtp_password = "password"
            mock_settings.smtp_use_tls = True
            mock_settings.escalation_email = "support@example.com"
            return EmailService()

    @pytest.mark.asyncio
    async def test_send_notification_email(self, email_service):
        """Test d'envoi de notification."""
        with patch.object(email_service, "_send_email", return_value=True) as mock_send:
            result = await email_service.send_notification_email(
                to_email="admin@example.com",
                subject="System Alert",
                message="System is running normally",
                is_html=False,
            )

            assert result is True
            mock_send.assert_called_once_with(
                to_emails=["admin@example.com"],
                subject="System Alert",
                text_content="System is running normally",
            )

    @pytest.mark.asyncio
    async def test_send_notification_email_not_configured(self):
        """Test avec service non configuré."""
        with patch("backend.src.email_service.smtp_client.settings") as mock_settings:
            mock_settings.smtp_host = None
            mock_settings.smtp_port = 587
            mock_settings.smtp_user = None
            mock_settings.smtp_password = "password"
            mock_settings.smtp_use_tls = True
            mock_settings.escalation_email = None

            service = EmailService()
            result = await service.send_notification_email(
                to_email="admin@example.com",
                subject="System Alert",
                message="System is running normally",
            )

            assert result is False

    @pytest.mark.asyncio
    async def test_send_system_health_alert(self, email_service):
        """Test d'alerte de santé système."""
        with patch.object(email_service, "_send_email", return_value=True) as mock_send:
            result = await email_service.send_notification_email(
                to_email="admin@example.com",
                subject="System Health Alert",
                message="<h1>System Status: Critical</h1>",
                is_html=True,
            )

            assert result is True
            mock_send.assert_called_once_with(
                to_emails=["admin@example.com"],
                subject="System Health Alert",
                html_content="<h1>System Status: Critical</h1>",
            )

    @pytest.mark.asyncio
    async def test_send_ingestion_report(self, email_service):
        """Test de rapport d'ingestion."""
        with patch.object(email_service, "_send_email", return_value=True) as mock_send:
            report_content = "Documents processed: 150\nErrors: 0\nTime: 2 minutes"

            result = await email_service.send_notification_email(
                to_email="admin@example.com",
                subject="Daily Ingestion Report",
                message=report_content,
                is_html=False,
            )

            assert result is True
            mock_send.assert_called_once()


class TestIntegration:
    """Tests d'intégration."""

    @pytest.fixture
    def email_service(self):
        """Service email configuré."""
        with patch("backend.src.email_service.smtp_client.settings") as mock_settings:
            mock_settings.smtp_host = "smtp.example.com"
            mock_settings.smtp_port = 587
            mock_settings.smtp_user = "user@example.com"
            mock_settings.smtp_password = "password"
            mock_settings.smtp_use_tls = True
            mock_settings.escalation_email = "support@example.com"
            return EmailService()

    @pytest.mark.asyncio
    async def test_full_escalation_workflow(self, email_service):
        """Test du workflow complet d'escalation."""
        with patch.object(email_service, "_send_email", return_value=True) as mock_send:
            # Données de test complètes
            user_question = "I can't access my account after password reset"
            chat_history = [
                {"type": "user", "content": "My password reset isn't working"},
                {
                    "type": "assistant",
                    "content": "Let me help you with that. Can you check your email?",
                },
                {"type": "user", "content": "I checked, no email received"},
                {"type": "assistant", "content": "Let me escalate this to our support team"},
            ]
            user_info = {
                "ip": "192.168.1.100",
                "session_id": "sess_12345",
                "user_agent": "Mozilla/5.0...",
            }
            context_sources = [
                "password_reset_guide.pdf",
                "troubleshooting_faq.md",
                "account_recovery.html",
            ]

            # Exécuter l'escalation
            result = await email_service.send_escalation_email(
                user_question=user_question,
                chat_history=chat_history,
                user_info=user_info,
                context_sources=context_sources,
            )

            # Vérifications
            assert result is True
            mock_send.assert_called_once()

            # Vérifier les arguments de l'appel
            call_args = mock_send.call_args
            assert call_args[1]["to_emails"] == ["support@example.com"]
            assert "Escalation" in call_args[1]["subject"]
            assert user_question in call_args[1]["html_content"]
            assert user_question in call_args[1]["text_content"]

    def test_configuration_validation_workflow(self, email_service):
        """Test du workflow de validation de configuration."""
        # Vérifier le statut de configuration
        status = email_service.get_configuration_status()

        assert status["configured"] is True
        assert status["smtp_host"] is True
        assert status["smtp_user"] is True
        assert status["escalation_email"] is True
        assert status["smtp_port"] == 587
        assert status["smtp_use_tls"] is True
