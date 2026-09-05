"""🔐 Authenticated encryption for persisted browser session state."""
from __future__ import annotations

import base64
import binascii
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class SessionVault:
    """Encrypt/decrypt session payloads using an operator-supplied 256-bit key."""

    VERSION = b"OBV1"
    KEY_BYTES = 32
    NONCE_BYTES = 12

    def __init__(self, encoded_key: str) -> None:
        if not encoded_key:
            raise ValueError("SESSION_ENCRYPTION_KEY обязателен для защищённого хранения сессий")
        try:
            key = base64.urlsafe_b64decode(encoded_key.encode("ascii"))
        except (ValueError, UnicodeEncodeError, binascii.Error) as exc:
            raise ValueError("SESSION_ENCRYPTION_KEY должен быть base64url-ключом") from exc
        if len(key) != self.KEY_BYTES:
            raise ValueError("SESSION_ENCRYPTION_KEY должен декодироваться ровно в 32 байта")
        self._aes = AESGCM(key)

    @classmethod
    def generate_key(cls) -> str:
        return base64.urlsafe_b64encode(os.urandom(cls.KEY_BYTES)).decode("ascii")

    def encrypt(self, plaintext: bytes, *, associated_data: bytes = b"") -> bytes:
        nonce = os.urandom(self.NONCE_BYTES)
        return self.VERSION + nonce + self._aes.encrypt(nonce, plaintext, associated_data)

    def decrypt(self, blob: bytes, *, associated_data: bytes = b"") -> bytes:
        if not blob.startswith(self.VERSION) or len(blob) <= len(self.VERSION) + self.NONCE_BYTES:
            raise ValueError("Некорректный формат зашифрованной сессии")
        offset = len(self.VERSION)
        nonce = blob[offset : offset + self.NONCE_BYTES]
        ciphertext = blob[offset + self.NONCE_BYTES :]
        try:
            return self._aes.decrypt(nonce, ciphertext, associated_data)
        except Exception as exc:  # cryptography raises InvalidTag, intentionally not leaked
            raise ValueError("Не удалось расшифровать сессию") from exc
