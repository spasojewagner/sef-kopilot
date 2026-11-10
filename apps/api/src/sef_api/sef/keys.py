"""The organizations' API keys, to SEF and to a language model's provider, sealed under
``SEF_FERNET_KEY`` (ADR-0050, ADR-0058).

A key is sealed with Fernet: AES-128 in CBC mode with a random IV, and HMAC-SHA256 over it, under
a key that only the environment holds, so that the database keeps a token that opens nothing
alone. Fernet authenticates no data beside its message, so the message names the organization
as well as the key: a token copied to another organization's row does not open there. A key to
a model's provider also names what it is for, ``model``: its token does not open as a key to
SEF, nor a SEF key's as one to a model (a SEF key's message, written before there were two
kinds, names none).

``SEF_FERNET_KEY`` may hold several keys while it is rotated: the first seals, every one opens,
and :meth:`Keyring.reseal` seals a token again under the first (``make rotate-sef-keys``).
"""

from __future__ import annotations

import json
import uuid
from typing import Literal

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from pydantic import SecretStr

from sef_api.settings import Settings

__all__ = ["Keyring", "Purpose", "UnreadableKeyError", "keyring_for"]

#: What a key opens: SEF, or a language model's provider.
Purpose = Literal["sef", "model"]
_LABELS: dict[Purpose, str] = {"sef": "SEF key", "model": "key to the model's provider"}


class UnreadableKeyError(Exception):
    """A token that no key of ``SEF_FERNET_KEY`` opens, or that another organization's key was
    sealed in."""


class Keyring:
    """Seals and opens the organizations' keys under the keys of ``SEF_FERNET_KEY``."""

    def __init__(self, keys: tuple[str, ...]) -> None:
        self._fernet = MultiFernet([Fernet(key) for key in keys])

    def seal(self, organization_id: uuid.UUID, api_key: SecretStr, purpose: Purpose = "sef") -> str:
        """``api_key`` sealed for ``organization_id`` and ``purpose``, as a Fernet token."""
        message = {"organization": str(organization_id), "key": api_key.get_secret_value()}
        if purpose != "sef":
            message["purpose"] = purpose
        sealed = self._fernet.encrypt(json.dumps(message, separators=(",", ":")).encode())
        return sealed.decode("ascii")

    def open(self, organization_id: uuid.UUID, token: str, purpose: Purpose = "sef") -> SecretStr:
        """The key sealed in ``token`` for ``organization_id`` and ``purpose``.
        :class:`UnreadableKeyError` for a token that no key opens, that is not one, or that was
        sealed for another organization or another purpose."""
        label = _LABELS[purpose]
        try:
            message = json.loads(self._fernet.decrypt(token.encode("ascii")))
        except (InvalidToken, UnicodeError, ValueError):
            raise UnreadableKeyError(f"the {label} cannot be opened with SEF_FERNET_KEY") from None
        if not isinstance(message, dict) or message.get("organization") != str(organization_id):
            raise UnreadableKeyError(f"the {label} was sealed for another organization")
        if message.get("purpose", "sef") != purpose:
            raise UnreadableKeyError(f"the {label} was sealed for another purpose")
        key = message.get("key")
        if not isinstance(key, str):
            raise UnreadableKeyError(f"the {label} cannot be opened with SEF_FERNET_KEY")
        return SecretStr(key)

    def reseal(self, token: str) -> str:
        """``token`` sealed again under the first key, whichever opened it."""
        try:
            return self._fernet.rotate(token.encode("ascii")).decode("ascii")
        except (InvalidToken, UnicodeError):
            raise UnreadableKeyError("the key cannot be opened with SEF_FERNET_KEY") from None


def keyring_for(settings: Settings) -> Keyring | None:
    """The keyring of ``SEF_FERNET_KEY``; none without it, and no SEF key can be set."""
    keys = settings.fernet_keys
    return Keyring(keys) if keys else None
