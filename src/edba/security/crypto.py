"""Secrets at rest and one-time code hashing."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

from cryptography.fernet import Fernet

from edba.config import Settings


def _fernet(settings: Settings) -> Fernet:
    key = settings.data_key
    if not key:
        digest = hashlib.sha256(("edba-data-key:" + settings.secret_key).encode()).digest()
        key = base64.urlsafe_b64encode(digest).decode()
    return Fernet(key.encode())


def encrypt(settings: Settings, plaintext: str) -> str:
    return _fernet(settings).encrypt(plaintext.encode()).decode()


def decrypt(settings: Settings, token: str) -> str:
    return _fernet(settings).decrypt(token.encode()).decode()


def new_otp() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_otp(settings: Settings, challenge_id: str, code: str) -> str:
    msg = f"{challenge_id}:{code}".encode()
    return hmac.new(settings.secret_key.encode(), msg, hashlib.sha256).hexdigest()


def otp_matches(settings: Settings, challenge_id: str, code: str, expected_hash: str) -> bool:
    return hmac.compare_digest(hash_otp(settings, challenge_id, code.strip()), expected_hash)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
