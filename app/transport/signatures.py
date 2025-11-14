"""Signature utilities based on Ed25519 public key cryptography."""

from __future__ import annotations

import base64
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from .canonical_json import canonical_dumps


class SignatureError(ValueError):
    """Raised when a payload signature is invalid or malformed."""


def load_public_key(pem: str) -> Ed25519PublicKey:
    if not pem:
        raise SignatureError("public key missing")
    return serialization.load_pem_public_key(pem.encode("utf-8"))


def load_private_key(pem: str) -> Ed25519PrivateKey:
    if not pem:
        raise SignatureError("private key missing")
    return serialization.load_pem_private_key(pem.encode("utf-8"), password=None)


def verify_signature(payload: Any, signature_b64: str, public_key_pem: str) -> None:
    """Validate an ed25519 signature over the canonical JSON payload."""
    if not signature_b64:
        raise SignatureError("signature missing")
    public_key = load_public_key(public_key_pem)
    try:
        signature = base64.b64decode(signature_b64)
    except (ValueError, TypeError) as exc:  # pragma: no cover - b64 check
        raise SignatureError("signature is not base64") from exc
    try:
        public_key.verify(signature, canonical_dumps(payload))
    except Exception as exc:  # pragma: no cover - delegated to cryptography
        raise SignatureError("signature verification failed") from exc


def sign_payload(payload: Any, private_key_pem: str) -> str:
    private_key = load_private_key(private_key_pem)
    signature = private_key.sign(canonical_dumps(payload))
    return base64.b64encode(signature).decode("utf-8")
