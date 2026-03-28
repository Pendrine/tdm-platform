from __future__ import annotations

import json
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path


STORAGE_CONFIG_FILENAME = "storage_config.json"
DATA_DIRNAME = "data"


@dataclass(frozen=True)
class StoragePaths:
    app_base_dir: Path
    config_path: Path
    data_dir: Path
    xlsx_candidates: tuple[Path, ...]
    xlsx_path: Path
    users_path: Path
    history_path: Path
    infectologists_path: Path
    settings_path: Path


class StorageMigrationError(RuntimeError):
    """Raised when storage root migration fails."""


def _detect_app_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent

    script = Path(sys.argv[0]).resolve() if sys.argv and sys.argv[0] else Path.cwd()
    return script.parent


def _read_storage_config(config_path: Path) -> Path | None:
    if not config_path.exists():
        return None
    try:
        with config_path.open("r", encoding="utf-8") as file:
            payload = json.load(file)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None

    if not isinstance(payload, dict):
        return None

    raw_storage_root = str(payload.get("storage_root", "")).strip()
    if not raw_storage_root:
        return None
    try:
        return Path(raw_storage_root).expanduser().resolve()
    except OSError:
        return None


def _write_storage_config(config_path: Path, storage_root: Path) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"storage_root": str(storage_root.resolve())}
    try:
        with config_path.open("w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2)
    except OSError as exc:
        raise StorageMigrationError(f"A storage config mentése sikertelen: {exc}") from exc


def get_storage_paths() -> StoragePaths:
    app_base_dir = _detect_app_base_dir()
    config_path = app_base_dir / STORAGE_CONFIG_FILENAME

    default_data_dir = app_base_dir / DATA_DIRNAME
    configured_data_dir = _read_storage_config(config_path)
    data_dir = configured_data_dir or default_data_dir
    data_dir.mkdir(parents=True, exist_ok=True)

    xlsx_candidates = (
        app_base_dir / "Új Microsoft Excel-munkalap.xlsx",
        data_dir / "Új Microsoft Excel-munkalap.xlsx",
        Path.home() / "Downloads" / "Új Microsoft Excel-munkalap.xlsx",
    )
    xlsx_path = next((path for path in xlsx_candidates if path.exists()), xlsx_candidates[0])

    return StoragePaths(
        app_base_dir=app_base_dir,
        config_path=config_path,
        data_dir=data_dir,
        xlsx_candidates=xlsx_candidates,
        xlsx_path=xlsx_path,
        users_path=data_dir / "tdm_users.json",
        history_path=data_dir / "tdm_history.json",
        infectologists_path=data_dir / "tdm_infectologists.json",
        settings_path=data_dir / "tdm_settings.json",
    )


def get_active_storage_root() -> Path:
    return get_storage_paths().data_dir


def _assert_directory_writable(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    probe = path / ".tdm_write_probe"
    try:
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
    except OSError as exc:
        raise StorageMigrationError(f"A célmappa nem írható: {path} ({exc})") from exc


def _copy_directory_contents(source: Path, target: Path) -> None:
    for entry in source.iterdir():
        destination = target / entry.name
        if entry.is_dir():
            shutil.copytree(entry, destination, dirs_exist_ok=True)
        else:
            shutil.copy2(entry, destination)


def configure_storage_root(new_storage_root: Path) -> Path:
    paths = get_storage_paths()
    source_root = paths.data_dir
    target_root = new_storage_root.expanduser().resolve()

    _assert_directory_writable(target_root)

    if source_root != target_root and source_root.exists():
        try:
            _copy_directory_contents(source_root, target_root)
        except OSError as exc:
            raise StorageMigrationError(f"Az adatok másolása sikertelen: {exc}") from exc

    _write_storage_config(paths.config_path, target_root)
    return target_root


# Backward-compatible module-level aliases.
PATHS = get_storage_paths()
APP_BASE_DIR = PATHS.app_base_dir
DATA_DIR = PATHS.data_dir
XLSX_CANDIDATES = PATHS.xlsx_candidates
XLSX_PATH = PATHS.xlsx_path
USERS_PATH = PATHS.users_path
HISTORY_PATH = PATHS.history_path
INFECTOLOGISTS_PATH = PATHS.infectologists_path
SETTINGS_PATH = PATHS.settings_path
