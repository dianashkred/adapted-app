"""Protection of e-mail addresses (the only direct personal data in the database).

* ``email_encrypted`` – Fernet (AES-128-CBC + HMAC-SHA256); the key lives outside the database.
* ``email_hash`` – HMAC-SHA256 of the normalised address with a secret pepper; used for
  look-ups and the UNIQUE constraint without storing the address in clear text.
* ``mask_email`` – masked form for logs and admin screens (``d***@gmail.com``).
Passwords are never stored by AdaptED: the identity provider (Supabase Auth) keeps only bcrypt hashes.
"""

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
