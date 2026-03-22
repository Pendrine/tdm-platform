def role_of(user: dict | None) -> str:
    return str((user or {}).get("role", "")).strip().lower()

def is_moderator(user: dict | None) -> bool:
    return role_of(user) == "moderator"

def is_infectologist(user: dict | None) -> bool:
    return role_of(user) == "infektologus"

def can_manage_users(user: dict | None) -> bool:
    return is_moderator(user)

def can_manage_smtp(user: dict | None) -> bool:
    return is_moderator(user)

def can_delete_history(user: dict | None) -> bool:
    return is_moderator(user)

def can_bulk_export(user: dict | None) -> bool:
    return is_infectologist(user) or is_moderator(user)

def can_edit_history(user: dict | None, record_user_email: str) -> bool:
    if is_moderator(user):
        return True
    if not user:
        return False
    return str(user.get("email", "")).strip().lower() == str(record_user_email or "").strip().lower()
