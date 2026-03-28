from __future__ import annotations

import logging
import os
import sys
from pathlib import Path


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


def get_exports_dir() -> Path:
    return _ensure_dir(get_data_dir() / "exports")


def get_data_file(name: str) -> Path:
    if not name or Path(name).is_absolute():
        raise ValueError("A data fájlnév relatív és nem üres kell legyen.")
    target = (get_data_dir() / name).resolve()
    data_root = get_data_dir().resolve()
    if data_root not in target.parents and target != data_root:
        raise ValueError("A data fájl csak a data könyvtáron belül lehet.")
    return target


APP_BASE_DIR = get_base_dir()
DATA_DIR = get_data_dir()
EXPORTS_DIR = get_exports_dir()

XLSX_CANDIDATES = (
    APP_BASE_DIR / "Új Microsoft Excel-munkalap.xlsx",
    DATA_DIR / "Új Microsoft Excel-munkalap.xlsx",
)
XLSX_PATH = next((path for path in XLSX_CANDIDATES if path.exists()), XLSX_CANDIDATES[0])

USERS_PATH = get_data_file("tdm_users.json")
HISTORY_PATH = get_data_file("tdm_history.json")
INFECTOLOGISTS_PATH = get_data_file("tdm_infectologists.json")
SETTINGS_PATH = get_data_file("tdm_settings.json")

logger.info("Active TDM data directory: %s", DATA_DIR)
