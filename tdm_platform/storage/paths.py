from pathlib import Path

APP_BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = APP_BASE_DIR / "tdm_platform_data"
DATA_DIR.mkdir(exist_ok=True)

XLSX_CANDIDATES = [
    APP_BASE_DIR / "Új Microsoft Excel-munkalap.xlsx",
    DATA_DIR / "Új Microsoft Excel-munkalap.xlsx",
    Path.home() / "Downloads" / "Új Microsoft Excel-munkalap.xlsx",
]

XLSX_PATH = next((p for p in XLSX_CANDIDATES if p.exists()), XLSX_CANDIDATES[0])
USERS_PATH = DATA_DIR / "tdm_users.json"
HISTORY_PATH = DATA_DIR / "tdm_history.json"
INFECTOLOGISTS_PATH = DATA_DIR / "tdm_infectologists.json"
SETTINGS_PATH = DATA_DIR / "tdm_settings.json"
