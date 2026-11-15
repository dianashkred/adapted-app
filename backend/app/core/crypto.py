import hashlib
import hmac

from cryptography.fernet import Fernet

from app.core.config import get_settings


def normalise_email(email: str) -> str:
    return email.strip().lower()


def email_hash(email: str, pepper: str | None = None) -> str:
    pepper = pepper if pepper is not None else get_settings().email_hash_pepper
    if not pepper:
        raise RuntimeError("EMAIL_HASH_PEPPER is not set")
    return hmac.new(pepper.encode(), normalise_email(email).encode(), hashlib.sha256).hexdigest()


def _fernet(key: str | None) -> Fernet:
    key = key if key is not None else get_settings().email_encryption_key
    if not key:
        raise RuntimeError("EMAIL_ENCRYPTION_KEY is not set")
    return Fernet(key.encode())


def encrypt_email(email: str, key: str | None = None) -> bytes:
    return _fernet(key).encrypt(normalise_email(email).encode())


def decrypt_email(token: bytes, key: str | None = None) -> str:
    return _fernet(key).decrypt(token).decode()


def mask_email(email: str) -> str:
    local, _, domain = normalise_email(email).partition("@")
    return f"{local[:1]}***@{domain}" if domain else "***"
