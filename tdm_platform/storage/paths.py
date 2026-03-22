from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class StoragePaths:
    app_base_dir: Path
    data_dir: Path
    xlsx_candidates: tuple[Path, ...]
    xlsx_path: Path
    users_path: Path
    history_path: Path
    infectologists_path: Path
    settings_path: Path


APP_BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = APP_BASE_DIR / "tdm_platform_data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

XLSX_CANDIDATES = (
    APP_BASE_DIR / "Új Microsoft Excel-munkalap.xlsx",
    DATA_DIR / "Új Microsoft Excel-munkalap.xlsx",
    Path.home() / "Downloads" / "Új Microsoft Excel-munkalap.xlsx",
)

XLSX_PATH = next((path for path in XLSX_CANDIDATES if path.exists()), XLSX_CANDIDATES[0])
USERS_PATH = DATA_DIR / "tdm_users.json"
HISTORY_PATH = DATA_DIR / "tdm_history.json"
INFECTOLOGISTS_PATH = DATA_DIR / "tdm_infectologists.json"
SETTINGS_PATH = DATA_DIR / "tdm_settings.json"

PATHS = StoragePaths(
    app_base_dir=APP_BASE_DIR,
    data_dir=DATA_DIR,
    xlsx_candidates=XLSX_CANDIDATES,
    xlsx_path=XLSX_PATH,
    users_path=USERS_PATH,
    history_path=HISTORY_PATH,
    infectologists_path=INFECTOLOGISTS_PATH,
    settings_path=SETTINGS_PATH,
)
