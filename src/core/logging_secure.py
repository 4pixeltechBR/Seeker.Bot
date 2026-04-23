"""
Seeker.Bot — Secure Logging with Secret Masking
src/core/logging_secure.py

Sanitiza logs para remover credentials, API keys, tokens, etc.
"""

import re
import logging
from typing import Any


class SecretMasker:
    """Mascara secrets em logs antes de exibir"""

    # Padrões de secrets a mascarar
    SECRET_PATTERNS = [
        # API Keys
        (r'api[_-]?key\s*[=:]\s*["\']?([^\s"\']+)', 'api_key'),
        (r'apikey\s*[=:]\s*["\']?([^\s"\']+)', 'api_key'),
        # Tokens
        (r'token\s*[=:]\s*["\']?([^\s"\']{20,})', 'token'),
        (r'bearer\s+([^\s]+)', 'bearer_token'),
        # Database URLs
        (r'postgresql://([^:]+):([^@]+)@', 'postgres_url'),
        (r'mongodb://[^/]+:([^@]+)@', 'mongo_url'),
        # AWS Keys
        (r'AKIA[0-9A-Z]{16}', 'aws_key_id'),
        (r'aws_secret_access_key\s*[=:]\s*["\']?([^\s"\']+)', 'aws_secret'),
        # Google API Keys
        (r'AIza[0-9A-Za-z\-_]{35}', 'google_api_key'),
        # JWT Tokens
        (r'eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}', 'jwt_token'),
        # Email addresses (partial masking)
        (r'([a-zA-Z0-9._%+-]{1,3})[a-zA-Z0-9._%+-]*@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', 'email'),
        # Phone numbers
        (r'\b(?:\+1|1)?[-.\s]?\(?([0-9]{3})\)?[-.\s]?([0-9]{3})[-.\s]?([0-9]{4})\b', 'phone'),
        # Credit card numbers
        (r'\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13})\b', 'credit_card'),
    ]

    @classmethod
    def mask(cls, message: str) -> str:
        """Mascara secrets em uma string"""
        if not message:
            return message

        masked = str(message)

        for pattern, secret_type in cls.SECRET_PATTERNS:
            masked = re.sub(pattern, f'***{secret_type}***', masked, flags=re.IGNORECASE)

        return masked

    @classmethod
    def mask_dict(cls, data: dict) -> dict:
        """Mascara secrets em um dicionário"""
        result = {}
        sensitive_keys = {
            'password', 'secret', 'token', 'api_key', 'apikey',
            'auth', 'credential', 'credentials', 'api_secret',
            'aws_secret_access_key', 'private_key', 'key'
        }

        for key, value in data.items():
            if any(sensitive in key.lower() for sensitive in sensitive_keys):
                result[key] = '***REDACTED***'
            elif isinstance(value, str):
                result[key] = cls.mask(value)
            elif isinstance(value, dict):
                result[key] = cls.mask_dict(value)
            elif isinstance(value, list):
                result[key] = [
                    cls.mask(str(item)) if isinstance(item, str) else item
                    for item in value
                ]
            else:
                result[key] = value

        return result


class SecureLogger(logging.Logger):
    """Logger que automaticamente mascara secrets"""

    def _log(self, level: int, msg: Any, args, **kwargs):
        """Override de _log para mascarar secrets"""
        if isinstance(msg, str):
            msg = SecretMasker.mask(msg)

        if args:
            if isinstance(args, dict):
                args = SecretMasker.mask_dict(args)
            elif isinstance(args, tuple):
                args = tuple(
                    SecretMasker.mask(str(arg)) if isinstance(arg, str) else arg
                    for arg in args
                )

        return super()._log(level, msg, args, **kwargs)


def setup_secure_logging():
    """Configura logging global com secret masking"""
    logging.setLoggerClass(SecureLogger)


# Exemplo de uso
if __name__ == "__main__":
    setup_secure_logging()
    logger = logging.getLogger("test")

    # Testa masking
    logger.info("API Key: sk-1234567890abcdef")
    logger.info("Database: postgresql://user:password123@localhost/db")
    logger.info("Email: user@example.com")
    logger.warning("Token: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9")
