"""
Tests unitaires pour le module auth/jwt_handler.py

Ces tests couvrent la gestion des tokens JWT et le hashage de mots de passe.
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
from freezegun import freeze_time
from jose import jwt
from backend.src.auth.jwt_handler import JWTHandler


class TestJWTHandlerInit:
    """Tests pour l'initialisation de JWTHandler."""

    def test_init_with_valid_config(self):
        """Test d'initialisation avec une configuration valide."""
        with patch('backend.src.auth.jwt_handler.settings') as mock_settings:
            mock_settings.jwt_secret_key = "a" * 32
            mock_settings.jwt_algorithm = "HS256"
            mock_settings.jwt_expiration_hours = 24

            handler = JWTHandler()

            assert handler.secret_key == "a" * 32
            assert handler.algorithm == "HS256"
            assert handler.expiration_hours == 24
            assert handler.pwd_context is not None

    def test_init_with_short_secret_key(self):
        """Test d'initialisation avec une clé secrète trop courte."""
        with patch('backend.src.auth.jwt_handler.settings') as mock_settings:
            mock_settings.jwt_secret_key = "short"
            mock_settings.jwt_algorithm = "HS256"
            mock_settings.jwt_expiration_hours = 24

            with pytest.raises(ValueError, match="JWT secret key must be at least 32 characters long"):
                JWTHandler()

    def test_init_with_empty_secret_key(self):
        """Test d'initialisation avec une clé secrète vide."""
        with patch('backend.src.auth.jwt_handler.settings') as mock_settings:
            mock_settings.jwt_secret_key = ""
            mock_settings.jwt_algorithm = "HS256"
            mock_settings.jwt_expiration_hours = 24

            with pytest.raises(ValueError, match="JWT secret key must be at least 32 characters long"):
                JWTHandler()


class TestCreateAccessToken:
    """Tests pour la création de tokens d'accès JWT."""

    @pytest.fixture
    def jwt_handler(self):
        """Fixture pour JWTHandler avec configuration valide."""
        with patch('backend.src.auth.jwt_handler.settings') as mock_settings:
            mock_settings.jwt_secret_key = "a" * 32
            mock_settings.jwt_algorithm = "HS256"
            mock_settings.jwt_expiration_hours = 24
            return JWTHandler()

    @freeze_time("2023-01-01 12:00:00")
    def test_create_token_with_default_expiration(self, jwt_handler):
        """Test de création de token avec expiration par défaut."""
        data = {"user_id": 123, "username": "testuser"}

        token = jwt_handler.create_access_token(data)

        assert isinstance(token, str)
        assert len(token) > 0

        # Décoder le token pour vérifier son contenu
        payload = jwt.decode(token, jwt_handler.secret_key, algorithms=[jwt_handler.algorithm])
        assert payload["user_id"] == 123
        assert payload["username"] == "testuser"
        assert payload["type"] == "access"
        assert "exp" in payload
        assert "iat" in payload

    @freeze_time("2023-01-01 12:00:00")
    def test_create_token_with_custom_expiration(self, jwt_handler):
        """Test de création de token avec expiration personnalisée."""
        data = {"user_id": 123}
        custom_expiration = timedelta(hours=1)

        token = jwt_handler.create_access_token(data, expires_delta=custom_expiration)

        payload = jwt.decode(token, jwt_handler.secret_key, algorithms=[jwt_handler.algorithm])
        expected_exp = datetime.utcnow() + custom_expiration
        actual_exp = datetime.utcfromtimestamp(payload["exp"])

        # Vérifier que l'expiration est correcte (avec une tolérance de quelques secondes)
        assert abs((actual_exp - expected_exp).total_seconds()) < 5

    def test_create_token_with_empty_data(self, jwt_handler):
        """Test de création de token avec des données vides."""
        token = jwt_handler.create_access_token({})

        payload = jwt.decode(token, jwt_handler.secret_key, algorithms=[jwt_handler.algorithm])
        assert payload["type"] == "access"
        assert "exp" in payload
        assert "iat" in payload

    @patch('backend.src.auth.jwt_handler.jwt.encode')
    def test_create_token_encoding_error(self, mock_encode, jwt_handler):
        """Test de gestion d'erreur lors de l'encodage du token."""
        mock_encode.side_effect = Exception("Encoding failed")

        with pytest.raises(Exception, match="Encoding failed"):
            jwt_handler.create_access_token({"user_id": 123})


class TestVerifyToken:
    """Tests pour la vérification de tokens JWT."""

    @pytest.fixture
    def jwt_handler(self):
        """Fixture pour JWTHandler avec configuration valide."""
        with patch('backend.src.auth.jwt_handler.settings') as mock_settings:
            mock_settings.jwt_secret_key = "a" * 32
            mock_settings.jwt_algorithm = "HS256"
            mock_settings.jwt_expiration_hours = 24
            return JWTHandler()

    def test_verify_valid_token(self, jwt_handler):
        """Test de vérification d'un token valide."""
        data = {"user_id": 123, "username": "testuser"}
        token = jwt_handler.create_access_token(data)

        payload = jwt_handler.verify_token(token)

        assert payload is not None
        assert payload["user_id"] == 123
        assert payload["username"] == "testuser"
        assert payload["type"] == "access"

    def test_verify_invalid_signature(self, jwt_handler):
        """Test de vérification avec signature invalide."""
        # Créer un token avec une clé différente
        fake_secret = "b" * 32
        data = {"user_id": 123, "type": "access"}
        fake_token = jwt.encode(data, fake_secret, algorithm="HS256")

        payload = jwt_handler.verify_token(fake_token)

        assert payload is None

    def test_verify_expired_token(self, jwt_handler):
        """Test de vérification d'un token expiré."""
        with freeze_time("2023-01-01 12:00:00"):
            data = {"user_id": 123}
            token = jwt_handler.create_access_token(data, expires_delta=timedelta(seconds=1))

        # Avancer le temps pour faire expirer le token
        with freeze_time("2023-01-01 12:01:00"):
            payload = jwt_handler.verify_token(token)
            assert payload is None

    def test_verify_invalid_token_type(self, jwt_handler):
        """Test de vérification avec type de token invalide."""
        data = {"user_id": 123, "type": "refresh"}
        token = jwt.encode(data, jwt_handler.secret_key, algorithm=jwt_handler.algorithm)

        payload = jwt_handler.verify_token(token)

        assert payload is None

    def test_verify_malformed_token(self, jwt_handler):
        """Test de vérification d'un token malformé."""
        malformed_token = "invalid.token.format"

        payload = jwt_handler.verify_token(malformed_token)

        assert payload is None

    def test_verify_token_without_type(self, jwt_handler):
        """Test de vérification d'un token sans type."""
        data = {"user_id": 123}
        token = jwt.encode(data, jwt_handler.secret_key, algorithm=jwt_handler.algorithm)

        payload = jwt_handler.verify_token(token)

        assert payload is None

    @patch('backend.src.auth.jwt_handler.jwt.decode')
    def test_verify_token_unexpected_error(self, mock_decode, jwt_handler):
        """Test de gestion d'erreur inattendue lors de la vérification."""
        mock_decode.side_effect = Exception("Unexpected error")

        payload = jwt_handler.verify_token("some_token")

        assert payload is None


class TestPasswordOperations:
    """Tests pour les opérations de mot de passe."""

    @pytest.fixture
    def jwt_handler(self):
        """Fixture pour JWTHandler avec configuration valide."""
        with patch('backend.src.auth.jwt_handler.settings') as mock_settings:
            mock_settings.jwt_secret_key = "a" * 32
            mock_settings.jwt_algorithm = "HS256"
            mock_settings.jwt_expiration_hours = 24
            return JWTHandler()

    def test_hash_password_valid(self, jwt_handler):
        """Test de hashage d'un mot de passe valide."""
        password = "testpassword123"

        hashed = jwt_handler.hash_password(password)

        assert isinstance(hashed, str)
        assert len(hashed) > 0
        assert hashed != password  # Le hash ne doit pas être le mot de passe en clair
        assert hashed.startswith("$2b$")  # Format bcrypt

    def test_hash_password_empty(self, jwt_handler):
        """Test de hashage d'un mot de passe vide."""
        with pytest.raises(ValueError, match="Password cannot be empty"):
            jwt_handler.hash_password("")

    def test_hash_password_none(self, jwt_handler):
        """Test de hashage d'un mot de passe None."""
        with pytest.raises(ValueError, match="Password cannot be empty"):
            jwt_handler.hash_password(None)

    def test_verify_password_valid(self, jwt_handler):
        """Test de vérification d'un mot de passe valide."""
        password = "testpassword123"
        hashed = jwt_handler.hash_password(password)

        is_valid = jwt_handler.verify_password(password, hashed)

        assert is_valid is True

    def test_verify_password_invalid(self, jwt_handler):
        """Test de vérification d'un mot de passe invalide."""
        password = "testpassword123"
        wrong_password = "wrongpassword"
        hashed = jwt_handler.hash_password(password)

        is_valid = jwt_handler.verify_password(wrong_password, hashed)

        assert is_valid is False

    def test_verify_password_empty_plain(self, jwt_handler):
        """Test de vérification avec mot de passe en clair vide."""
        hashed = jwt_handler.hash_password("testpassword")

        is_valid = jwt_handler.verify_password("", hashed)

        assert is_valid is False

    def test_verify_password_empty_hash(self, jwt_handler):
        """Test de vérification avec hash vide."""
        is_valid = jwt_handler.verify_password("password", "")

        assert is_valid is False

    def test_verify_password_none_values(self, jwt_handler):
        """Test de vérification avec valeurs None."""
        assert jwt_handler.verify_password(None, "hash") is False
        assert jwt_handler.verify_password("password", None) is False
        assert jwt_handler.verify_password(None, None) is False

    @patch('backend.src.auth.jwt_handler.CryptContext.verify')
    def test_verify_password_exception(self, mock_verify, jwt_handler):
        """Test de gestion d'exception lors de la vérification."""
        mock_verify.side_effect = Exception("Verification failed")

        is_valid = jwt_handler.verify_password("password", "hash")

        assert is_valid is False


class TestGetTokenExpiry:
    """Tests pour l'extraction de la date d'expiration des tokens."""

    @pytest.fixture
    def jwt_handler(self):
        """Fixture pour JWTHandler avec configuration valide."""
        with patch('backend.src.auth.jwt_handler.settings') as mock_settings:
            mock_settings.jwt_secret_key = "a" * 32
            mock_settings.jwt_algorithm = "HS256"
            mock_settings.jwt_expiration_hours = 24
            return JWTHandler()

    @freeze_time("2023-01-01 12:00:00")
    def test_get_token_expiry_valid(self, jwt_handler):
        """Test d'extraction d'expiration d'un token valide."""
        data = {"user_id": 123}
        token = jwt_handler.create_access_token(data)

        expiry = jwt_handler.get_token_expiry(token)

        assert expiry is not None
        assert isinstance(expiry, datetime)
        expected_expiry = datetime.utcnow() + timedelta(hours=24)
        assert abs((expiry - expected_expiry).total_seconds()) < 5

    def test_get_token_expiry_invalid_token(self, jwt_handler):
        """Test d'extraction d'expiration d'un token invalide."""
        invalid_token = "invalid.token"

        expiry = jwt_handler.get_token_expiry(invalid_token)

        assert expiry is None

    def test_get_token_expiry_expired_token(self, jwt_handler):
        """Test d'extraction d'expiration d'un token expiré."""
        with freeze_time("2023-01-01 12:00:00"):
            data = {"user_id": 123}
            token = jwt_handler.create_access_token(data, expires_delta=timedelta(seconds=1))

        # Le token expire, mais on peut toujours extraire sa date d'expiration
        with freeze_time("2023-01-01 12:01:00"):
            expiry = jwt_handler.get_token_expiry(token)
            assert expiry is None  # verify_token retourne None pour un token expiré


class TestJWTHandlerIntegration:
    """Tests d'intégration pour JWTHandler."""

    @pytest.fixture
    def jwt_handler(self):
        """Fixture pour JWTHandler avec configuration valide."""
        with patch('backend.src.auth.jwt_handler.settings') as mock_settings:
            mock_settings.jwt_secret_key = "a" * 32
            mock_settings.jwt_algorithm = "HS256"
            mock_settings.jwt_expiration_hours = 24
            return JWTHandler()

    def test_full_authentication_flow(self, jwt_handler):
        """Test du flux complet d'authentification."""
        # Créer et hasher un mot de passe
        password = "userpassword123"
        hashed_password = jwt_handler.hash_password(password)

        # Vérifier le mot de passe
        assert jwt_handler.verify_password(password, hashed_password) is True

        # Créer un token
        user_data = {"user_id": 123, "username": "testuser"}
        token = jwt_handler.create_access_token(user_data)

        # Vérifier le token
        payload = jwt_handler.verify_token(token)
        assert payload is not None
        assert payload["user_id"] == 123
        assert payload["username"] == "testuser"

        # Obtenir l'expiration
        expiry = jwt_handler.get_token_expiry(token)
        assert expiry is not None
        assert expiry > datetime.utcnow()

    def test_password_hash_uniqueness(self, jwt_handler):
        """Test que le même mot de passe produit des hashes différents."""
        password = "samepassword"

        hash1 = jwt_handler.hash_password(password)
        hash2 = jwt_handler.hash_password(password)

        # Les hashes doivent être différents (salt aléatoire)
        assert hash1 != hash2

        # Mais les deux doivent être vérifiables
        assert jwt_handler.verify_password(password, hash1) is True
        assert jwt_handler.verify_password(password, hash2) is True

    def test_token_uniqueness(self, jwt_handler):
        """Test que des tokens créés à des moments différents sont uniques."""
        data = {"user_id": 123}

        # Utiliser des dates futures pour éviter l'expiration
        future_date = datetime.now() + timedelta(hours=1)

        with freeze_time(future_date):
            token1 = jwt_handler.create_access_token(data)

        with freeze_time(future_date + timedelta(seconds=1)):
            token2 = jwt_handler.create_access_token(data)

        # Les tokens doivent être différents (timestamps différents)
        assert token1 != token2

        # Mais les deux doivent être valides
        assert jwt_handler.verify_token(token1) is not None
        assert jwt_handler.verify_token(token2) is not None