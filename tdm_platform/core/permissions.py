from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from tdm_platform.core.roles import resolve_user_role


UserLike = Mapping[str, Any] | None


def role_of(user: UserLike) -> str:
    return resolve_user_role(user)


def is_moderator(user: UserLike) -> bool:
    return role_of(user) == "moderator"


def is_infectologist(user: UserLike) -> bool:
    return role_of(user) == "infektologus"


def can_manage_users(user: UserLike) -> bool:
    return is_moderator(user)


def can_manage_smtp(user: UserLike) -> bool:
    return is_moderator(user)


def can_delete_history(user: UserLike) -> bool:
    return is_moderator(user)


def can_bulk_export(user: UserLike) -> bool:
    return is_infectologist(user) or is_moderator(user)


def can_edit_history(user: UserLike, record_user_email: str) -> bool:
    if is_moderator(user):
        return True
    if not user:
        return False
    return str(user.get("email", "")).strip().lower() == str(record_user_email or "").strip().lower()
