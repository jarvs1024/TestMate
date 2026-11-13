"""集成凭据加密: RSA 传输解密与 AES-256-GCM 落库加密."""
from __future__ import annotations

import base64
import os
from dataclasses import dataclass

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.core.config import settings

_FORMAT_PREFIX = "v1:"
_NONCE_BYTES = 12
_KEY_BYTES = 32
_HKDF_INFO = b"testmate-integration-credentials"


class IntegrationCryptoError(ValueError):
    """密文无效/解密失败; 调用方只返回笼统文案, 不回显细节."""


@dataclass(frozen=True)
class TransportKeyPair:
    private_key: rsa.RSAPrivateKey
    public_pem: str


def generate_transport_keypair() -> TransportKeyPair:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_pem = private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")
    return TransportKeyPair(private_key=private_key, public_pem=public_pem)


def decrypt_transport(
    payload_b64: str,
    private_key: rsa.RSAPrivateKey,
    *,
    max_length: int = 4096,
) -> str:
    payload = (payload_b64 or "").strip()
    if not payload or len(payload) > max_length:
        raise IntegrationCryptoError("传输密文无效")
    try:
        ciphertext = base64.b64decode(payload, validate=True)
    except Exception as exc:  # noqa: BLE001
        raise IntegrationCryptoError("传输密文无效") from exc
    try:
        plaintext = private_key.decrypt(ciphertext, padding.PKCS1v15())
    except Exception as exc:  # noqa: BLE001
        raise IntegrationCryptoError("传输密文解密失败") from exc
    try:
        return plaintext.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise IntegrationCryptoError("传输密文解密失败") from exc


def master_key() -> bytes:
    raw = (settings.INTEGRATION_CREDENTIAL_KEY or "").strip()
    if raw:
        try:
            key = base64.b64decode(raw, validate=True)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError("INTEGRATION_CREDENTIAL_KEY 不是合法 base64") from exc
        if len(key) != _KEY_BYTES:
            raise RuntimeError(
                f"INTEGRATION_CREDENTIAL_KEY 必须是 {_KEY_BYTES} 字节 (base64), "
                f"当前 {len(key)} 字节"
            )
        return key
    if not settings.DEBUG:
        raise RuntimeError("INTEGRATION_CREDENTIAL_KEY 未配置")
    return HKDF(
        algorithm=hashes.SHA256(),
        length=_KEY_BYTES,
        salt=None,
        info=_HKDF_INFO,
    ).derive(settings.JWT_SECRET.encode("utf-8"))


def _aad(user_id: int, provider: str) -> bytes:
    return f"{user_id}:{provider}".encode("utf-8")


def encrypt_secret(
    plaintext: str, *, user_id: int, provider: str, key: bytes | None = None
) -> str:
    nonce = os.urandom(_NONCE_BYTES)
    ciphertext = AESGCM(key or master_key()).encrypt(
        nonce, plaintext.encode("utf-8"), _aad(user_id, provider)
    )
    return _FORMAT_PREFIX + base64.b64encode(nonce + ciphertext).decode("ascii")


def decrypt_secret(
    token: str | None, *, user_id: int, provider: str, key: bytes | None = None
) -> str:
    if not token or not token.startswith(_FORMAT_PREFIX):
        raise IntegrationCryptoError("密文格式无效")
    encoded = token[len(_FORMAT_PREFIX):]
    try:
        raw = base64.b64decode(encoded, validate=True)
    except Exception as exc:  # noqa: BLE001
        raise IntegrationCryptoError("密文格式无效") from exc
    if len(raw) <= _NONCE_BYTES:
        raise IntegrationCryptoError("密文格式无效")
    nonce, ciphertext = raw[:_NONCE_BYTES], raw[_NONCE_BYTES:]
    try:
        plaintext = AESGCM(key or master_key()).decrypt(
            nonce, ciphertext, _aad(user_id, provider)
        )
    except Exception as exc:  # noqa: BLE001
        raise IntegrationCryptoError("凭据解密失败") from exc
    try:
        return plaintext.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise IntegrationCryptoError("凭据解密失败") from exc
