from __future__ import annotations

from collections.abc import Mapping
from typing import Any


MODERATORS = {
    "visnyovszki.adam@dpckorhaz.hu",
}


def resolve_user_role(user: Mapping[str, Any] | None) -> str:
    if user and user.get("_signature_valid") is False:
        return "user"
    email = str((user or {}).get("email", "")).strip().lower()
    if email in MODERATORS:
        return "moderator"
    return "user"
