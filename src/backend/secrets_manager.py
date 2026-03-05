"""
Secrets management module for the Real-Time Data Collection and Monitoring System.

Provides secure handling of secrets and sensitive configuration.
"""

import os
import base64
from typing import Optional
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


class SecretsManager:
    """Simple secrets manager (use AWS Secrets Manager, HashiCorp Vault, etc. in production)."""

    def __init__(self, master_key: Optional[str] = None):
        """
        Initialize secrets manager.

        Args:
            master_key: Master encryption key (if None, generates from env)
        """
        if master_key is None:
            master_key = os.getenv("MASTER_ENCRYPTION_KEY")
            if master_key is None:
                # Generate a key from a password (not secure for production!)
                password = os.getenv("SECRETS_PASSWORD", "default-password-change-in-production")
                salt = os.getenv("SECRETS_SALT", "default-salt-change-in-production").encode()
                kdf = PBKDF2HMAC(
                    algorithm=hashes.SHA256(),
                    length=32,
                    salt=salt,
                    iterations=100000,
                )
                master_key = base64.urlsafe_b64encode(kdf.derive(password.encode())).decode()

        self.cipher = Fernet(master_key.encode() if isinstance(master_key, str) else master_key)

    def encrypt(self, plaintext: str) -> str:
        """
        Encrypt a string.

        Args:
            plaintext: Plain text to encrypt

        Returns:
            Encrypted string (base64 encoded)
        """
        return self.cipher.encrypt(plaintext.encode()).decode()

    def decrypt(self, ciphertext: str) -> str:
        """
        Decrypt a string.

        Args:
            ciphertext: Encrypted string (base64 encoded)

        Returns:
            Decrypted plain text
        """
        return self.cipher.decrypt(ciphertext.encode()).decode()

    def get_secret(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """
        Get a secret from environment or encrypted storage.

        Args:
            key: Secret key name
            default: Default value if not found

        Returns:
            Secret value or default
        """
        # First check environment variable
        value = os.getenv(key)
        if value:
            return value

        # Check encrypted storage (in production, use proper secret store)
        encrypted_key = f"{key}_ENCRYPTED"
        encrypted_value = os.getenv(encrypted_key)
        if encrypted_value:
            try:
                return self.decrypt(encrypted_value)
            except Exception:
                return default

        return default

    def set_secret(self, key: str, value: str, encrypt: bool = True) -> None:
        """
        Set a secret (for testing/development only).

        Args:
            key: Secret key name
            value: Secret value
            encrypt: Whether to encrypt the value
        """
        if encrypt:
            encrypted_value = self.encrypt(value)
            os.environ[f"{key}_ENCRYPTED"] = encrypted_value
        else:
            os.environ[key] = value


# Global secrets manager instance
secrets_manager = SecretsManager()


def get_database_password() -> str:
    """Get database password from secrets."""
    password = secrets_manager.get_secret("DB_PASSWORD", "postgres")
    if password is None:
        raise ValueError("Database password not configured")
    return password


def get_jwt_secret() -> str:
    """Get JWT secret key from secrets."""
    secret = secrets_manager.get_secret("JWT_SECRET_KEY")
    if secret is None:
        # Generate a new secret if not set
        import secrets

        secret = secrets.token_urlsafe(32)
        secrets_manager.set_secret("JWT_SECRET_KEY", secret)
    return secret
