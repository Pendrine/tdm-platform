from __future__ import annotations

from collections.abc import Mapping
from typing import Any


MODERATORS = {
    "visnyovszki.adam@dpckorhaz.hu",
}
PRIMARY_MODERATOR_EMAIL = "visnyovszki.adam@dpckorhaz.hu"


def is_primary_moderator(user: Mapping[str, Any] | None) -> bool:
    email = str((user or {}).get("email", "")).strip().lower()
    return email == PRIMARY_MODERATOR_EMAIL


def resolve_user_role(user: Mapping[str, Any] | None) -> str:
    if user and user.get("_signature_valid") is False:
        return "user"
    email = str((user or {}).get("email", "")).strip().lower()
    if email in MODERATORS:
        return "moderator"
    return "user"
