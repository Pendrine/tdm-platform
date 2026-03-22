from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class User:
    email: str
    username: str
    name: str
    role: str = "orvos"
    verified: bool = False
    active: bool = True
    password_hash: str = ""
    verification_code: str = ""
    verified_at: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SMTPSettings:
    host: str = ""
    port: int = 587
    smtp_user: str = ""
    smtp_pass: str = ""
    sender: str = ""
    use_starttls: bool = True
    use_ssl: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class HistoryRecord:
    timestamp: str
    user: str
    patient_id: str
    drug: str
    method: str
    status: str
    regimen: str
    decision: str
    report: str
    inputs: dict[str, Any] = field(default_factory=dict)
    app_version: str | None = None
    schema_version: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)
