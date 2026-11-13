"""集成凭据加密: 传输层 RSA 解密 + 落库 AES-GCM."""
from __future__ import annotations

import base64
import json

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from app.core.config import settings
from app.integrations import crypto


def _key(byte: bytes = b"k") -> bytes:
    return byte * 32


def _rsa_encrypt(public_pem: str, plaintext: bytes) -> str:
    public_key = serialization.load_pem_public_key(public_pem.encode("ascii"))
    ciphertext = public_key.encrypt(plaintext, padding.PKCS1v15())
    return base64.b64encode(ciphertext).decode("ascii")


# ---------------- AES-GCM 落库 ----------------


def test_secret_roundtrip():
    token = crypto.encrypt_secret(
        "p@ssw0rd-中文", user_id=7, provider="pingcode", key=_key()
    )
    assert token.startswith("v1:")
    assert "p@ssw0rd" not in token
    assert (
        crypto.decrypt_secret(token, user_id=7, provider="pingcode", key=_key())
        == "p@ssw0rd-中文"
    )


def test_ciphertext_uses_random_nonce():
    first = crypto.encrypt_secret("same", user_id=1, provider="pingcode", key=_key())
    second = crypto.encrypt_secret("same", user_id=1, provider="pingcode", key=_key())
    assert first != second


def test_decrypt_rejects_aad_mismatch():
    token = crypto.encrypt_secret("secret", user_id=1, provider="pingcode", key=_key())
    with pytest.raises(crypto.IntegrationCryptoError):
        crypto.decrypt_secret(token, user_id=2, provider="pingcode", key=_key())
    with pytest.raises(crypto.IntegrationCryptoError):
        crypto.decrypt_secret(token, user_id=1, provider="plm", key=_key())


def test_decrypt_rejects_tampered_ciphertext():
    token = crypto.encrypt_secret("secret", user_id=1, provider="pingcode", key=_key())
    raw = bytearray(base64.b64decode(token[3:]))
    raw[-1] ^= 0x01
    tampered = "v1:" + base64.b64encode(bytes(raw)).decode("ascii")
    with pytest.raises(crypto.IntegrationCryptoError):
        crypto.decrypt_secret(tampered, user_id=1, provider="pingcode", key=_key())


@pytest.mark.parametrize(
    "token",
    ["", "v2:abcd", "v1:", "v1:not-base64!!", "v1:" + base64.b64encode(b"short").decode()],
)
def test_decrypt_rejects_bad_format(token: str):
    with pytest.raises(crypto.IntegrationCryptoError):
        crypto.decrypt_secret(token, user_id=1, provider="pingcode", key=_key())


def test_decrypt_rejects_wrong_key():
    token = crypto.encrypt_secret("secret", user_id=1, provider="pingcode", key=_key(b"a"))
    with pytest.raises(crypto.IntegrationCryptoError):
        crypto.decrypt_secret(token, user_id=1, provider="pingcode", key=_key(b"b"))


# ---------------- 主密钥解析 ----------------


def test_master_key_reads_setting(monkeypatch):
    raw = bytes(range(32))
    monkeypatch.setattr(
        settings, "INTEGRATION_CREDENTIAL_KEY", base64.b64encode(raw).decode("ascii")
    )
    assert crypto.master_key() == raw


@pytest.mark.parametrize("value", ["not-base64!!", base64.b64encode(b"short").decode("ascii")])
def test_master_key_rejects_invalid_length(monkeypatch, value: str):
    monkeypatch.setattr(settings, "INTEGRATION_CREDENTIAL_KEY", value)
    with pytest.raises(RuntimeError):
        crypto.master_key()


def test_master_key_derives_from_jwt_secret_when_unset(monkeypatch):
    monkeypatch.setattr(settings, "INTEGRATION_CREDENTIAL_KEY", "")
    monkeypatch.setattr(settings, "JWT_SECRET", "j" * 48)
    first = crypto.master_key()
    assert len(first) == 32
    assert first == crypto.master_key()


# ---------------- RSA 传输 ----------------


def test_transport_roundtrip():
    keypair = crypto.generate_transport_keypair()
    payload = json.dumps({"username": "u1", "password": "p1"})
    encrypted = _rsa_encrypt(keypair.public_pem, payload.encode("utf-8"))
    assert crypto.decrypt_transport(encrypted, keypair.private_key) == payload


def test_transport_rejects_oversize_payload():
    keypair = crypto.generate_transport_keypair()
    payload = _rsa_encrypt(keypair.public_pem, b"x" * 200)
    with pytest.raises(crypto.IntegrationCryptoError):
        crypto.decrypt_transport(payload, keypair.private_key, max_length=100)


def test_transport_rejects_invalid_base64():
    keypair = crypto.generate_transport_keypair()
    with pytest.raises(crypto.IntegrationCryptoError):
        crypto.decrypt_transport("not-base64!!", keypair.private_key)


def test_transport_rejects_foreign_key():
    ours = crypto.generate_transport_keypair()
    other = crypto.generate_transport_keypair()
    encrypted = _rsa_encrypt(other.public_pem, b"payload")
    with pytest.raises(crypto.IntegrationCryptoError):
        crypto.decrypt_transport(encrypted, ours.private_key)


def test_public_pem_is_rsa_2048():
    keypair = crypto.generate_transport_keypair()
    public_key = serialization.load_pem_public_key(keypair.public_pem.encode("ascii"))
    assert isinstance(public_key, rsa.RSAPublicKey)
    assert public_key.key_size == 2048
    assert b"BEGIN PUBLIC KEY" in keypair.public_pem.encode("ascii")
