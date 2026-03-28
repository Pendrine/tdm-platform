from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

from tdm_platform.core.roles import is_primary_moderator


logger = logging.getLogger(__name__)


def get_base_dir() -> Path:
    """Return executable/script directory used as storage base."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent

    main_module = sys.modules.get("__main__")
    main_file = getattr(main_module, "__file__", None)
    if main_file:
        return Path(main_file).resolve().parent

    argv0 = sys.argv[0] if sys.argv else ""
    if argv0:
        return Path(argv0).resolve().parent

    return Path.cwd().resolve()


def _ensure_dir(path: Path) -> Path:
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise RuntimeError(f"A könyvtár nem hozható létre: {path}") from exc

    if not os.access(path, os.W_OK):
        raise RuntimeError(f"A könyvtár nem írható: {path}")
    return path


def get_data_dir() -> Path:
    return _ensure_dir(get_base_dir() / "data")


def _storage_config_path() -> Path:
    return get_data_dir() / "storage_paths.json"


def _load_storage_config() -> dict[str, Any]:
    path = _storage_config_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_storage_config(cfg: dict[str, Any]) -> None:
    path = _storage_config_path()
    path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def get_secure_data_dir() -> Path:
    cfg = _load_storage_config()
    target = Path(str(cfg.get("secure_data_dir", get_data_dir() / "secure")))
    if not target.is_absolute():
        target = get_data_dir() / target
    return _ensure_dir(target.resolve())


def get_runtime_data_dir() -> Path:
    cfg = _load_storage_config()
    target = Path(str(cfg.get("runtime_data_dir", get_data_dir() / "runtime")))
    if not target.is_absolute():
        target = get_data_dir() / target
    return _ensure_dir(target.resolve())


def set_secure_data_dir(user: dict | None, directory: str | Path) -> Path:
    if not is_primary_moderator(user):
        raise PermissionError("Secure data directory-t csak primary moderator állíthat.")
    target = _ensure_dir(Path(directory).expanduser().resolve())
    cfg = _load_storage_config()
    cfg["secure_data_dir"] = str(target)
    _save_storage_config(cfg)
    return target


def set_runtime_data_dir(user: dict | None, directory: str | Path) -> Path:
    if not is_primary_moderator(user):
        raise PermissionError("Runtime data directory-t csak primary moderator állíthat.")
    target = _ensure_dir(Path(directory).expanduser().resolve())
    cfg = _load_storage_config()
    cfg["runtime_data_dir"] = str(target)
    _save_storage_config(cfg)
    return target


def get_exports_dir() -> Path:
    return _ensure_dir(get_runtime_data_dir() / "exports")


def get_logs_dir() -> Path:
    return _ensure_dir(get_runtime_data_dir() / "logs")


def get_secure_file(name: str) -> Path:
    if not name or Path(name).is_absolute():
        raise ValueError("A secure fájlnév relatív és nem üres kell legyen.")
    return (get_secure_data_dir() / name).resolve()


def get_runtime_file(name: str) -> Path:
    if not name or Path(name).is_absolute():
        raise ValueError("A runtime fájlnév relatív és nem üres kell legyen.")
    return (get_runtime_data_dir() / name).resolve()


APP_BASE_DIR = get_base_dir()
DATA_DIR = get_data_dir()
SECURE_DATA_DIR = get_secure_data_dir()
RUNTIME_DATA_DIR = get_runtime_data_dir()
EXPORTS_DIR = get_exports_dir()
LOGS_DIR = get_logs_dir()

XLSX_CANDIDATES = (
    APP_BASE_DIR / "Új Microsoft Excel-munkalap.xlsx",
    RUNTIME_DATA_DIR / "Új Microsoft Excel-munkalap.xlsx",
)
XLSX_PATH = next((path for path in XLSX_CANDIDATES if path.exists()), XLSX_CANDIDATES[0])

USERS_PATH = get_secure_file("tdm_users.json")
SETTINGS_PATH = get_secure_file("tdm_settings.json")
INFECTOLOGISTS_PATH = get_secure_file("tdm_infectologists.json")
HISTORY_PATH = get_runtime_file("tdm_history.json")

logger.info("Active TDM secure data directory: %s", SECURE_DATA_DIR)
logger.info("Active TDM runtime data directory: %s", RUNTIME_DATA_DIR)
