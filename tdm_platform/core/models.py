from dataclasses import dataclass, field
from typing import Optional, Dict, Any

@dataclass
class User:
    email: str
    username: str
    name: str
    role: str = "orvos"
    verified: bool = False
    active: bool = True

@dataclass
class SMTPSettings:
    host: str = ""
    port: int = 587
    smtp_user: str = ""
    smtp_pass: str = ""
    sender: str = ""
    use_starttls: bool = True
    use_ssl: bool = False

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
    inputs: Dict[str, Any] = field(default_factory=dict)
    app_version: Optional[str] = None
    schema_version: Optional[int] = None
