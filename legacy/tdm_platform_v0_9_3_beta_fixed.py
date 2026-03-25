import json
import math
import os
import sys
import hashlib
import html
import secrets
import smtplib
import ssl
from email.message import EmailMessage
import tempfile
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Tuple

try:
    import openpyxl
except Exception:
    openpyxl = None

from PySide6.QtCore import QDateTime, Qt, QMarginsF
from PySide6.QtGui import QAction, QPainter, QTextDocument, QPageLayout, QPageSize, QImage
from PySide6.QtPrintSupport import QPrinter

from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDateTimeEdit,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QInputDialog,
    QPushButton,
    QPlainTextEdit,
    QScrollArea,
    QSplitter,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QCompleter,
)

try:
    from PySide6.QtWebEngineWidgets import QWebEngineView
    WEB_OK = True
except Exception:
    WEB_OK = False
    QWebEngineView = None

import plotly.graph_objects as go
import plotly.io as pio

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas as pdf_canvas
    REPORTLAB_OK = True
except Exception:
    REPORTLAB_OK = False

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages
    MATPLOTLIB_OK = True
except Exception:
    MATPLOTLIB_OK = False
    PdfPages = None

APP_VERSION = "v0.9.2-beta"
BUILD_INFO = "build 2026-03-22"
SCHEMA_VERSION = "schema 1"

APP_TITLE = "Klinikai TDM Platform"
UMOL_PER_MGDL_CREATININE = 88.4
TARGET_AUC_LOW = 400.0
TARGET_AUC_HIGH = 600.0
TARGET_TROUGH_LOW = 10.0
TARGET_TROUGH_HIGH = 20.0
ALLOWED_EMAIL_DOMAIN = "dpckorhaz.hu"
ALLOWED_TEST_EMAILS = {"visnyo.adam@gmail.com"}


def generate_temp_password(length: int = 12) -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789!@#$%*"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def user_is_active(user: Optional[dict]) -> bool:
    return bool(user) and user.get("active", True) is not False


def _detect_app_base_dir() -> str:
    try:
        return os.path.dirname(os.path.abspath(__file__))
    except Exception:
        return os.getcwd()


APP_BASE_DIR = _detect_app_base_dir()
DATA_DIR = os.path.join(APP_BASE_DIR, "tdm_platform_data")
os.makedirs(DATA_DIR, exist_ok=True)

_XLSX_CANDIDATES = [
    os.path.join(APP_BASE_DIR, "Új Microsoft Excel-munkalap.xlsx"),
    os.path.join(DATA_DIR, "Új Microsoft Excel-munkalap.xlsx"),
    os.path.join(os.path.expanduser("~"), "Downloads", "Új Microsoft Excel-munkalap.xlsx"),
]
XLSX_PATH = next((p for p in _XLSX_CANDIDATES if os.path.exists(p)), _XLSX_CANDIDATES[0])
HISTORY_PATH = os.path.join(DATA_DIR, "tdm_history.json")
USERS_PATH = os.path.join(DATA_DIR, "tdm_users.json")
INFECTOLOGISTS_PATH = os.path.join(DATA_DIR, "tdm_infectologists.json")
SETTINGS_PATH = os.path.join(DATA_DIR, "tdm_settings.json")
MAIN_MODERATOR_EMAIL = "visnyovszki.adam@dpckorhaz.hu"
SMTP_DEFAULT_HOST = "mail.dpckorhaz.hu"
SMTP_DEFAULT_PORT = "587"
SMTP_DEFAULT_USER = "visnyovszki.adam@dpckorhaz.hu"
SMTP_DEFAULT_FROM = "visnyovszki.adam@dpckorhaz.hu"
SMTP_DEFAULT_STARTTLS = "1"
SMTP_DEFAULT_SSL = "0"


def parse_float(text: str, optional: bool = False) -> Optional[float]:
    txt = str(text).strip().replace(",", ".")
    if txt == "":
        if optional:
            return None
        raise ValueError("Hiányzó numerikus érték.")
    return float(txt)


@dataclass
class Citation:
    title: str
    journal: str
    year: str
    pmid: str = ""
    doi: str = ""
    note: str = ""


EVIDENCE: Dict[str, Dict[str, List[Citation]]] = {
    "Vancomycin": {
        "Klasszikus": [
            Citation(
                title="Therapeutic monitoring of vancomycin for serious MRSA infections: a revised consensus guideline and review",
                journal="Am J Health Syst Pharm",
                year="2020",
                pmid="32191793",
                note="AUC/MIC 400–600 cél; a klasszikus kétszintes számítás jó auditálható fallback stabil, steady-state helyzetben.",
            )
        ],
        "Bayesian": [
            Citation(
                title="Therapeutic monitoring of vancomycin for serious MRSA infections: a revised consensus guideline and review",
                journal="Am J Health Syst Pharm",
                year="2020",
                pmid="32191793",
                note="Bayes-alapú AUC monitorozás preferált, ha korai individualizálás vagy nem stabil kinetika áll fenn.",
            ),
            Citation(
                title="Trough Concentration versus Ratio of Area Under the Curve to Minimum Inhibitory Concentration for Vancomycin Dosing",
                journal="Can J Hosp Pharm",
                year="2022",
                pmid="35387369",
                note="A trough önmagában nem jó surrogate minden helyzetben; az AUC-cél közelebb áll az ajánlásokhoz.",
            ),
        ],
        "ICU / Haladó": [
            Citation(
                title="Therapeutic monitoring of vancomycin for serious MRSA infections: a revised consensus guideline and review",
                journal="Am J Health Syst Pharm",
                year="2020",
                pmid="32191793",
                note="Kritikus állapotban ismételt újrabecslés és AUC-fókusz különösen fontos.",
            ),
            Citation(
                title="Vancomycin population pharmacokinetics and dosing individualization in adult obese patients",
                journal="Eur J Drug Metab Pharmacokinet",
                year="2024",
                pmid="38895623",
                note="Obesitasban és megváltozott eloszlási térfogat mellett külön prior/logika indokolt lehet.",
            ),
        ],
    },
    "Linezolid": {
        "Gyors TDM": [
            Citation(
                title="Expert consensus statement on therapeutic drug monitoring and individualization of linezolid",
                journal="Front Public Health",
                year="2022",
                pmid="36033811",
                note="A trough-célok és a TDM szerepe hatásosság és toxicitás egyensúlyában.",
            )
        ],
        "Bayesian (általános)": [
            Citation(
                title="Expert consensus statement on therapeutic drug monitoring and individualization of linezolid",
                journal="Front Public Health",
                year="2022",
                pmid="36033811",
                note="AUC és trough együttes értelmezése segíthet az expozíció optimalizálásában.",
            ),
            Citation(
                title="Pharmacokinetic and Pharmacodynamic Principles of Anti-Infective Dosing",
                journal="általános TDM szemlélet",
                year="review",
                note="A linezolidnál jelentős interindividuális variabilitás miatt a modellalapú megközelítés hasznos.",
            ),
        ],
        "Bayesian (hematológia)": [
            Citation(
                title="Pharmacokinetics and hematologic toxicity of linezolid in children receiving anti-cancer chemotherapy",
                journal="J Antimicrob Chemother",
                year="2025",
                pmid="40698816",
                note="Onkohematológiai/cancer populációban magas trough mellett nőhet a hematológiai toxicitás kockázata.",
            ),
            Citation(
                title="Expert consensus statement on therapeutic drug monitoring and individualization of linezolid",
                journal="Front Public Health",
                year="2022",
                pmid="36033811",
                note="A TDM különösen hasznos lehet toxicitásveszélyes populációban.",
            ),
        ],
    },
    "Amikacin": {
        "Extended-interval Bayesian": [
            Citation(
                title="Population pharmacokinetic modeling and optimal sampling strategy for Bayesian estimation of amikacin exposure in critically ill septic patients",
                journal="Ther Drug Monit",
                year="2010",
                pmid="20962708",
                doi="10.1097/FTD.0b013e3181f675c2",
                note="Bayesian expozícióbecslés és mintavételi stratégia kritikus állapotban.",
            ),
            Citation(
                title="A simulation study on model-informed precision dosing of amikacin in critically ill patients",
                journal="Br J Clin Pharmacol",
                year="2024",
                pmid="38304967",
                note="AUC-célzás és modellalapú dózistervezés kritikus állapotban is ígéretes.",
            ),
        ],
        "Konvencionális Bayesian": [
            Citation(
                title="Population pharmacokinetics of amikacin in critically ill patients",
                journal="Antimicrob Agents Chemother",
                year="1996",
                pmid="8807062",
                note="A Bayesian megközelítés alkalmas a koncentrációk predikciójára és a dózisindividualizálásra.",
            ),
            Citation(
                title="Pharmacokinetics of amikacin in intensive care unit patients",
                journal="J Antimicrob Chemother",
                year="1997",
                pmid="9201569",
                note="ICU populációban a variabilitás nagy, ezért a monitorozott individualizálás fontos.",
            ),
        ],
    },
}

GUIDE_TEXT: Dict[Tuple[str, str], Dict[str, List[str]]] = {
    ("Vancomycin", "Klasszikus"): {
        "why": [
            "Stabil beteg, steady-state, jól időzített két minta.",
            "Átlátható, auditálható képletalapú számítás.",
        ],
        "avoid": [
            "Erősen instabil vesefunkció.",
            "Korai terápia, amikor még nincs közel steady-state.",
        ],
    },
    ("Vancomycin", "Bayesian"): {
        "why": [
            "Korai individualizálás, nem feltétlen steady-state helyzet.",
            "Egy vagy két szintből rugalmasabb AUC-becslés.",
        ],
        "avoid": [
            "Nagyon rosszul időzített minták esetén a posterior is félremehet.",
        ],
    },
    ("Vancomycin", "ICU / Haladó"): {
        "why": [
            "ICU, obesitas, instabil clearance, CRRT/ECMO-közeli szituáció.",
            "Konzervatívabb prior és szorosabb újramérés javasolt.",
        ],
        "avoid": [
            "Egyszerű, stabil osztályos betegnél általában elég a sima Bayes vagy klasszikus mód.",
        ],
    },
    ("Linezolid", "Gyors TDM"): {
        "why": [
            "Gyors bedside trough-interpretáció.",
            "Ha azonnal kell kockázatbecslés, de nincs teljes PK-profil.",
        ],
        "avoid": [
            "Komplex dózisoptimalizáláshoz kevés lehet önmagában.",
        ],
    },
    ("Linezolid", "Bayesian (általános)"): {
        "why": [
            "Általános adult prior, 1–2 mintából AUC és Cmin becslés.",
            "Jó kompromisszum a gyorsaság és a precizitás között.",
        ],
        "avoid": [
            "Extrém speciális populációban szükség lehet testreszabott priorra.",
        ],
    },
    ("Linezolid", "Bayesian (hematológia)"): {
        "why": [
            "Hematológiai/onkohematológiai beteganyag, toxicitásfókusz.",
            "Szigorúbb trough-cél és konzervatívabb clearance-prior.",
        ],
        "avoid": [
            "Átlagos, nem hematológiai betegben nem feltétlen ez az első választás.",
        ],
    },
    ("Amikacin", "Extended-interval Bayesian"): {
        "why": [
            "Naponta egyszeri adagolásnál peak-expozíció + alacsony trough cél.",
            "Kritikus állapotban a modellalapú közelítés különösen hasznos.",
        ],
        "avoid": [
            "Ha a helyi protokoll hagyományos többszöri napi adagolást használ.",
        ],
    },
    ("Amikacin", "Konvencionális Bayesian"): {
        "why": [
            "Hagyományos peak/trough logika, többszöri napi adagolás mellett.",
            "Jobban illeszkedik a klasszikus labor- és osztályos workflow-hoz.",
        ],
        "avoid": [
            "Extended-interval stratégia mellett inkább az ahhoz tartozó módot válaszd.",
        ],
    },
}

METHOD_RECOMMENDATION = {
    "Vancomycin": {
        "Klasszikus": "stabil beteg, jó mintavételi időzítés, auditálható képlet",
        "Bayesian": "korai individualizálás, bizonytalan steady-state, kevés minta",
        "ICU / Haladó": "kritikus állapot, instabil vesefunkció, obesitas vagy extracorporalis support",
    },
    "Linezolid": {
        "Gyors TDM": "gyors trough-központú ágy melletti döntés",
        "Bayesian (általános)": "általános adult popPK megközelítés",
        "Bayesian (hematológia)": "hematológiai/onkohematológiai populáció, toxicitásfókusz",
    },
    "Amikacin": {
        "Extended-interval Bayesian": "napi egyszeri adagolás, magas peak és alacsony trough cél",
        "Konvencionális Bayesian": "hagyományos többszöri napi adagolás",
    },
}

EMPIRICAL_FALLBACK = [
    {
        "drug": "Amikacin",
        "parameter": "Völgy + csúcs",
        "target": "trough <5 mg/L; egyszeri napi adagolásnál peak tipikusan 50–64 mg/L",
        "toxicity": "magas csúcs és tartós trough növelheti oto/nephrotoxicitás kockázatát",
        "coverage": "Pseudomonas aeruginosa",
        "from_resistant": 16,
        "method": "peak/trough + PAE",
        "toxicity_method": "trough",
        "note": "Empirikus nagy rizikó esetben Pseudomonas-centrikus célzás.",
    },
    {
        "drug": "Linezolid",
        "parameter": "Völgy + AUC",
        "target": "Cmin kb. 2–8 mg/L; AUC/MIC >80–100",
        "toxicity": "Cmin >8 mg/L mellett nőhet a toxicitási kockázat",
        "coverage": "MRSA / CoNS",
        "from_resistant": 4,
        "method": "AUC/MIC + trough",
        "toxicity_method": "trough",
        "note": "Hematológiai betegben szigorúbb értelmezés indokolt.",
    },
    {
        "drug": "Vancomycin",
        "parameter": "AUC24 + völgy",
        "target": "AUC24 400–600 mg·h/L; régi surrogate: trough 15–20 mg/L súlyos MRSA esetben",
        "toxicity": "AUC >600 vagy tartósan magas trough esetén nő a nephrotoxicitás kockázata",
        "coverage": "MRSA / CoNS",
        "from_resistant": 2,
        "method": "AUC24/MIC",
        "toxicity_method": "AUC + trough",
        "note": "Empirikusan gyakran MIC=1 feltételezéssel indulunk, majd deeszkalálunk.",
    },
]


def load_empirical_targets() -> List[dict]:
    if openpyxl is None or not os.path.exists(XLSX_PATH):
        return EMPIRICAL_FALLBACK
    try:
        wb = openpyxl.load_workbook(XLSX_PATH, data_only=True)
        ws = wb["TDM"]
        rows = list(ws.iter_rows(values_only=True))
        header = rows[0]
        out = []
        for row in rows[1:]:
            if not row or len(row) < 8:
                continue
            drug = row[2]
            if not drug:
                continue
            out.append(
                {
                    "drug": str(row[2]),
                    "parameter": str(row[3] or ""),
                    "target": str(row[4] or ""),
                    "toxicity": str(row[5] or ""),
                    "coverage": str(row[6] or ""),
                    "from_resistant": row[7],
                    "method": str(row[8] or ""),
                    "toxicity_method": str(row[9] or ""),
                    "note": str(row[10] or ""),
                }
            )
        return out or EMPIRICAL_FALLBACK
    except Exception:
        return EMPIRICAL_FALLBACK


class StatCard(QFrame):
    def __init__(self, title: str, value: str = "—", subtitle: str = ""):
        super().__init__()
        self.setObjectName("StatCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(4)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("CardTitle")
        self.value_label = QLabel(value)
        self.value_label.setObjectName("CardValue")
        self.subtitle_label = QLabel(subtitle)
        self.subtitle_label.setObjectName("CardSubtitle")
        self.subtitle_label.setWordWrap(True)
        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label)
        layout.addWidget(self.subtitle_label)

    def update_card(self, value: str, subtitle: str = ""):
        self.value_label.setText(value)
        self.subtitle_label.setText(subtitle)




def normalize_email_value(email: str) -> str:
    return str(email or '').strip().lower()

def validate_doctor_email_value(email: str) -> str:
    e = normalize_email_value(email)
    if not e or '@' not in e:
        raise ValueError('Adj meg egy érvényes e-mail címet.')
    if e in ALLOWED_TEST_EMAILS:
        return e
    if not e.endswith(f'@{ALLOWED_EMAIL_DOMAIN}'):
        allowed_extra = ', '.join(sorted(ALLOWED_TEST_EMAILS))
        raise ValueError(f'Csak @{ALLOWED_EMAIL_DOMAIN} e-mail címmel lehet regisztrálni és belépni. Teszt kivétel: {allowed_extra}')
    return e

def load_users_file() -> List[dict]:
    if not os.path.exists(USERS_PATH):
        return []
    try:
        with open(USERS_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []

def save_users_file(users: List[dict]):
    os.makedirs(os.path.dirname(USERS_PATH), exist_ok=True)
    with open(USERS_PATH, 'w', encoding='utf-8') as f:
        json.dump(users, f, ensure_ascii=False, indent=2)

def hash_password_value(password: str) -> str:
    return hashlib.sha256(str(password).encode('utf-8')).hexdigest()


def ensure_special_roles(users: List[dict]) -> List[dict]:
    found = False
    for user in users:
        email = normalize_email_value(user.get("email", ""))
        if email == MAIN_MODERATOR_EMAIL:
            user["role"] = "moderator"
            found = True
        else:
            user.setdefault("role", "orvos")
    if not found:
        users.append({
            "name": "Dr. Visnyovszki Ádám",
            "email": MAIN_MODERATOR_EMAIL,
            "password_hash": hash_password_value("ChangeMe123!"),
            "role": "moderator",
            "verified": True,
            "verification_code": "",
            "verified_at": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        })
    return users


def load_infectologists_file() -> List[dict]:
    if not os.path.exists(INFECTOLOGISTS_PATH):
        return []
    try:
        with open(INFECTOLOGISTS_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def save_infectologists_file(items: List[dict]):
    os.makedirs(os.path.dirname(INFECTOLOGISTS_PATH), exist_ok=True)
    with open(INFECTOLOGISTS_PATH, 'w', encoding='utf-8') as f:
        json.dump(items, f, ensure_ascii=False, indent=2)


def load_settings_file() -> dict:
    defaults = {
        "smtp_host": SMTP_DEFAULT_HOST,
        "smtp_port": SMTP_DEFAULT_PORT,
        "smtp_user": SMTP_DEFAULT_USER,
        "smtp_from": SMTP_DEFAULT_FROM,
        "smtp_starttls": SMTP_DEFAULT_STARTTLS,
        "smtp_ssl": SMTP_DEFAULT_SSL,
        "smtp_pass": "",
    }
    if not os.path.exists(SETTINGS_PATH):
        return defaults
    try:
        with open(SETTINGS_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, dict):
            merged = defaults.copy()
            merged.update({k: str(v) if v is not None else '' for k, v in data.items() if k in merged})
            return merged
    except Exception:
        pass
    return defaults


def save_settings_file(settings: dict):
    os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
    safe = load_settings_file()
    safe.update({k: settings.get(k, safe.get(k, '')) for k in safe.keys()})
    with open(SETTINGS_PATH, 'w', encoding='utf-8') as f:
        json.dump(safe, f, ensure_ascii=False, indent=2)


def get_smtp_settings() -> dict:
    cfg = load_settings_file()
    return {
        'host': os.getenv('TDM_SMTP_HOST', cfg.get('smtp_host', SMTP_DEFAULT_HOST)).strip(),
        'port': int(os.getenv('TDM_SMTP_PORT', cfg.get('smtp_port', SMTP_DEFAULT_PORT)) or SMTP_DEFAULT_PORT),
        'smtp_user': os.getenv('TDM_SMTP_USER', cfg.get('smtp_user', SMTP_DEFAULT_USER)).strip(),
        'smtp_pass': os.getenv('TDM_SMTP_PASS', cfg.get('smtp_pass', '')).strip(),
        'sender': os.getenv('TDM_SMTP_FROM', cfg.get('smtp_from', SMTP_DEFAULT_FROM)).strip(),
        'use_starttls': os.getenv('TDM_SMTP_STARTTLS', cfg.get('smtp_starttls', SMTP_DEFAULT_STARTTLS)).strip().lower() in {'1','true','yes','on'},
        'use_ssl': os.getenv('TDM_SMTP_SSL', cfg.get('smtp_ssl', SMTP_DEFAULT_SSL)).strip().lower() in {'1','true','yes','on'},
    }


class AuthDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f'Orvos bejelentkezés – {APP_VERSION}')
        self.setModal(True)
        self.resize(860, 760)
        self.setMinimumSize(760, 680)
        self.current_user: Optional[dict] = None
        self.users_data: List[dict] = ensure_special_roles(load_users_file())
        save_users_file(self.users_data)
        self._build_ui()
        self._apply_auth_theme()

    def _make_scroll_tab(self, inner_widget: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setWidget(inner_widget)
        return scroll

    def refresh_role_dependent_ui(self):
        role = str((self.current_user or {}).get("role", "")).strip().lower()
        is_moderator = role == "moderator"
        is_infectologist = role == "infektologus"
        if hasattr(self, "delete_history_btn"):
            self.delete_history_btn.setVisible(is_moderator)
            self.delete_history_btn.setEnabled(is_moderator)
        if hasattr(self, "save_history_changes_btn"):
            self.save_history_changes_btn.setEnabled(bool(self.current_user))
        if hasattr(self, "clear_form_btn"):
            self.clear_form_btn.setEnabled(True)
        if hasattr(self, "send_bulk_btn"):
            self.send_bulk_btn.setVisible(is_infectologist)
            self.send_bulk_btn.setEnabled(is_infectologist)
        if hasattr(self, "bulk_send_btn"):
            self.bulk_send_btn.setVisible(is_infectologist)
            self.bulk_send_btn.setEnabled(is_infectologist)

    def refresh_role_dependent_ui(self):
        role = str((self.current_user or {}).get("role", "")).strip().lower()
        is_moderator = role == "moderator"
        is_infectologist = role == "infektologus"
        if hasattr(self, "delete_history_btn"):
            self.delete_history_btn.setVisible(is_moderator)
            self.delete_history_btn.setEnabled(is_moderator)
        if hasattr(self, "save_history_changes_btn"):
            self.save_history_changes_btn.setEnabled(bool(self.current_user))
        if hasattr(self, "clear_form_btn"):
            self.clear_form_btn.setEnabled(True)
        if hasattr(self, "send_bulk_btn"):
            self.send_bulk_btn.setVisible(is_infectologist)
            self.send_bulk_btn.setEnabled(is_infectologist)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        theme_row = QFrame()
        theme_row.setObjectName('ThemeBar')
        theme_layout = QHBoxLayout(theme_row)
        theme_layout.setContentsMargins(14, 10, 14, 10)
        theme_layout.setSpacing(8)
        badge = QLabel('Belépés')
        badge.setObjectName('AuthBadge')
        theme_layout.addWidget(badge)
        theme_layout.addWidget(QLabel('Klinikai TDM Platform'))
        theme_layout.addStretch(1)
        helper_small = QLabel(f'Csak hitelesített orvos felhasználó • {APP_VERSION}')
        helper_small.setObjectName('HintLabel')
        theme_layout.addWidget(helper_small)
        layout.addWidget(theme_row)

        header = QFrame()
        header.setObjectName('Header')
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(18, 16, 18, 16)
        header_layout.setSpacing(4)
        head = QLabel(f'Klinikai TDM Platform – belépés ({APP_VERSION})')
        head.setObjectName('HeaderTitle')
        sub = QLabel('Bejelentkezés után nyílik meg a program. Alapértelmezetten csak @dpckorhaz.hu címmel lehet regisztrálni.')
        sub.setObjectName('HeaderSubtitle')
        sub.setWordWrap(True)
        header_layout.addWidget(head)
        header_layout.addWidget(sub)
        layout.addWidget(header)

        login_box = QGroupBox('Bejelentkezés')
        lf = QFormLayout(login_box)
        lf.setContentsMargins(14, 16, 14, 14)
        lf.setSpacing(10)
        self.login_identifier_combo = QComboBox()
        self.login_identifier_combo.setEditable(True)
        self.login_identifier_combo.setInsertPolicy(QComboBox.NoInsert)
        self.login_identifier_combo.setMinimumContentsLength(28)
        self.login_identifier_combo.lineEdit().setPlaceholderText('felhasználónév vagy e-mail')
        self.refresh_login_autofill()
        self.login_password_edit = QLineEdit(); self.login_password_edit.setEchoMode(QLineEdit.Password)
        self.login_password_edit.setPlaceholderText('jelszó')
        self.login_info = QLabel('')
        self.login_info.setObjectName('HintLabel')
        self.login_info.setWordWrap(True)
        login_btn = QPushButton('Belépés a programba')
        login_btn.setObjectName('PrimaryButton')
        login_btn.clicked.connect(self.login_user)
        self.reset_password_btn = QPushButton('Új ideiglenes jelszó kérése')
        self.reset_password_btn.clicked.connect(self.request_password_reset)
        lf.addRow('Felhasználónév / e-mail', self.login_identifier_combo)
        lf.addRow('Jelszó', self.login_password_edit)
        lf.addRow('', login_btn)
        lf.addRow('', self.reset_password_btn)
        lf.addRow('', self.login_info)
        layout.addWidget(login_box)

        reg_box = QGroupBox('Új orvos regisztráció')
        reg_box.setCheckable(True)
        reg_box.setChecked(False)
        rf = QFormLayout(reg_box)
        rf.setContentsMargins(14, 16, 14, 14)
        rf.setSpacing(10)
        self.reg_name_edit = QLineEdit()
        self.reg_name_edit.setPlaceholderText('teljes név')
        self.reg_email_edit = QLineEdit()
        self.reg_email_edit.setPlaceholderText('kórházi e-mail vagy tesztcím')
        self.reg_password_edit = QLineEdit(); self.reg_password_edit.setEchoMode(QLineEdit.Password)
        self.reg_password2_edit = QLineEdit(); self.reg_password2_edit.setEchoMode(QLineEdit.Password)
        reg_btn = QPushButton('Regisztráció indítása')
        reg_btn.clicked.connect(self.register_user)
        rf.addRow('Név', self.reg_name_edit)
        rf.addRow('Kórházi e-mail', self.reg_email_edit)
        rf.addRow('Jelszó', self.reg_password_edit)
        rf.addRow('Jelszó újra', self.reg_password2_edit)
        rf.addRow('', reg_btn)
        self._set_groupbox_content_visible(reg_box, False)
        reg_box.toggled.connect(lambda checked, box=reg_box: self._set_groupbox_content_visible(box, checked))
        layout.addWidget(reg_box)

        ver_box = QGroupBox('E-mail visszaigazolás')
        ver_box.setCheckable(True)
        ver_box.setChecked(False)
        vf = QFormLayout(ver_box)
        vf.setContentsMargins(14, 16, 14, 14)
        vf.setSpacing(10)
        self.verify_email_edit = QLineEdit()
        self.verify_code_edit = QLineEdit()
        verify_btn = QPushButton('Visszaigazolás')
        verify_btn.clicked.connect(self.verify_user)
        vf.addRow('Kórházi e-mail', self.verify_email_edit)
        vf.addRow('Kód', self.verify_code_edit)
        vf.addRow('', verify_btn)
        self._set_groupbox_content_visible(ver_box, False)
        ver_box.toggled.connect(lambda checked, box=ver_box: self._set_groupbox_content_visible(box, checked))
        layout.addWidget(ver_box)

        layout.addStretch(1)

    def _set_groupbox_content_visible(self, box: QGroupBox, visible: bool):
        layout = box.layout()
        if not layout:
            return
        for i in range(layout.rowCount()):
            label_item = layout.itemAt(i, QFormLayout.LabelRole)
            field_item = layout.itemAt(i, QFormLayout.FieldRole)
            for item in (label_item, field_item):
                if item and item.widget():
                    item.widget().setVisible(visible)

    def _apply_auth_theme(self):
        self.setStyleSheet("""
            QDialog, QWidget { background: #f6f9fc; color: #16324f; font-family: 'Segoe UI', Arial, sans-serif; font-size: 13px; }
            #ThemeBar, #HintBox { background: #eef4fb; border: 1px solid #d4e0ef; border-radius: 16px; }
            #Header { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #eef4fb, stop:1 #dcecff); border: 1px solid #d4e0ef; border-radius: 18px; }
            #HeaderTitle { font-size: 22px; font-weight: 800; color: #10263d; }
            #HeaderSubtitle { color: #4f6680; }
            QGroupBox { border: 1px solid #d4e0ef; border-radius: 16px; margin-top: 10px; padding-top: 14px; background: #ffffff; font-weight: 600; }
            QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 8px; color: #2b5fd9; }
            QLineEdit, QComboBox, QTextBrowser { background: #f9fbfe; border: 1px solid #d4e0ef; border-radius: 10px; padding: 8px 10px; color: #16324f; }
            QPushButton { background: #ffffff; border: 1px solid #d4e0ef; border-radius: 12px; padding: 10px 14px; color: #16324f; font-weight: 600; }
            QPushButton:hover { background: #f2f7fd; }
            #PrimaryButton { background: #2b5fd9; border: 1px solid #2b5fd9; color: white; }
            #AuthBadge { background: #2b5fd9; color: white; padding: 5px 10px; border-radius: 10px; font-weight: 700; }
            #HintLabel { color: #5f738b; }
        """)
    def find_user(self, email: str) -> Optional[dict]:
        e = normalize_email_value(email)
        for u in self.users_data:
            if normalize_email_value(u.get('email')) == e:
                return u
        return None

    def save_users(self):
        save_users_file(self.users_data)

    def send_verification_email(self, email: str, code: str) -> tuple[bool, str]:
        host = os.environ.get('TDM_SMTP_HOST', SMTP_DEFAULT_HOST).strip()
        port = int(os.environ.get('TDM_SMTP_PORT', SMTP_DEFAULT_PORT) or SMTP_DEFAULT_PORT)
        smtp_user = os.environ.get('TDM_SMTP_USER', SMTP_DEFAULT_USER).strip()
        smtp_pass = os.environ.get('TDM_SMTP_PASS', '').strip()
        sender = os.environ.get('TDM_SMTP_FROM', SMTP_DEFAULT_FROM or smtp_user or f'tdm-noreply@{ALLOWED_EMAIL_DOMAIN}')
        if not host:
            return False, f'Fejlesztői mód: ellenőrző kód = {code}'
        msg = EmailMessage()
        msg['Subject'] = 'Klinikai TDM Platform – e-mail visszaigazolás'
        msg['From'] = sender
        msg['To'] = email
        msg.set_content(f"A Klinikai TDM Platform regisztrációjához használd ezt az ellenőrző kódot: {code}\n\nHa nem te indítottad a regisztrációt, hagyd figyelmen kívül ezt az üzenetet.\n")
        try:
            context = ssl.create_default_context()
            use_ssl = os.environ.get('TDM_SMTP_SSL', SMTP_DEFAULT_SSL).strip().lower() in {'1', 'true', 'yes', 'on'}
            use_starttls = os.environ.get('TDM_SMTP_STARTTLS', SMTP_DEFAULT_STARTTLS).strip().lower() in {'1', 'true', 'yes', 'on'}
            if use_ssl:
                with smtplib.SMTP_SSL(host, port, timeout=20, context=context) as server:
                    if smtp_user:
                        server.login(smtp_user, smtp_pass)
                    server.send_message(msg)
            else:
                with smtplib.SMTP(host, port, timeout=20) as server:
                    server.ehlo()
                    if use_starttls:
                        server.starttls(context=context)
                        server.ehlo()
                    if smtp_user:
                        server.login(smtp_user, smtp_pass)
                    server.send_message(msg)
            return True, f'Visszaigazoló e-mail elküldve: {email}'
        except smtplib.SMTPAuthenticationError as e:
            return False, (
                "SMTP hitelesítés sikertelen. Ellenőrizd az SMTP felhasználónevet, jelszót, "
                f"STARTTLS/SSL beállítást. Fejlesztői fallback ellenőrző kód: {code}. SMTP hiba: {e}"
            )
        except Exception as e:
            return False, f'Az e-mail küldése nem sikerült ({e}). Ellenőrző kód: {code}'

    def send_password_reset_email(self, email: str, temp_password: str) -> tuple[bool, str]:
        smtp = get_smtp_settings()
        host = smtp['host']
        port = smtp['port']
        smtp_user = smtp['smtp_user']
        smtp_pass = smtp['smtp_pass']
        sender = smtp['sender'] or smtp_user
        if not host or not sender or not smtp_pass:
            return False, f'Az SMTP nincs teljesen beállítva. Ideiglenes jelszó: {temp_password}'
        msg = EmailMessage()
        msg['Subject'] = 'Klinikai TDM Platform – ideiglenes jelszó'
        msg['From'] = sender
        msg['To'] = email
        msg.set_content(f"Ideiglenes jelszó kérés történt a Klinikai TDM Platformhoz.\n\nIdeiglenes jelszó: {temp_password}\n\nBelépés után a Beállításoknál javasolt azonnal új jelszót megadni.\n")
        try:
            context = ssl.create_default_context()
            if smtp['use_ssl']:
                with smtplib.SMTP_SSL(host, port, timeout=20, context=context) as server:
                    if smtp_user:
                        server.login(smtp_user, smtp_pass)
                    server.send_message(msg)
            else:
                with smtplib.SMTP(host, port, timeout=20) as server:
                    server.ehlo()
                    if smtp['use_starttls']:
                        server.starttls(context=context)
                        server.ehlo()
                    if smtp_user:
                        server.login(smtp_user, smtp_pass)
                    server.send_message(msg)
            return True, f'Az ideiglenes jelszó elküldve: {email}'
        except Exception as e:
            return False, f'Az e-mail küldése nem sikerült ({e}). Ideiglenes jelszó: {temp_password}'

    def request_password_reset(self):
        try:
            identifier = self.login_identifier_combo.currentText().strip() or self.verify_email_edit.text().strip()
            email = self.resolve_login_identifier(identifier) if identifier else validate_doctor_email_value(self.verify_email_edit.text())
            user = self.find_user(email)
            if not user:
                raise ValueError('Nincs ilyen regisztrált felhasználó.')
            temp_password = secrets.token_urlsafe(8)[:12]
            user['password_hash'] = hash_password_value(temp_password)
            user['password_changed_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            self.save_users()
            ok, message = self.send_password_reset_email(email, temp_password)
            QMessageBox.information(self, 'Új ideiglenes jelszó', message)
        except Exception as e:
            QMessageBox.warning(self, 'Jelszó visszaállítás hiba', str(e))

    def _login_candidates(self) -> List[str]:
        candidates = []
        for u in self.users_data:
            email = str(u.get("email", "")).strip()
            if not email:
                continue
            username = str(u.get("username", "")).strip() or email.split("@")[0]
            for value in (username, email):
                if value and value not in candidates:
                    candidates.append(value)
        return candidates

    def refresh_login_autofill(self):
        from PySide6.QtWidgets import QCompleter
        candidates = self._login_candidates()
        try:
            self.login_identifier_combo.clear()
            self.login_identifier_combo.addItems(candidates)
        except Exception:
            pass
        completer = QCompleter(candidates, self)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)
        self.login_identifier_combo.setCompleter(completer)

    def resolve_login_identifier(self, raw_value: str) -> str:
        value = (raw_value or "").strip()
        if not value:
            raise ValueError('Add meg a felhasználónevet vagy kórházi e-mail címet.')
        if '@' in value:
            return validate_doctor_email_value(value)
        matches = []
        lower_value = value.lower()
        for u in self.users_data:
            email = str(u.get('email', '')).strip()
            username = str(u.get('username', '')).strip() or (email.split('@')[0] if email else '')
            if username.lower() == lower_value:
                matches.append(email)
        if not matches:
            raise ValueError('Nincs ilyen felhasználónév. Használhatsz kórházi e-mail címet is.')
        if len(set(matches)) > 1:
            raise ValueError('Ez a felhasználónév nem egyedi. Jelentkezz be teljes e-mail címmel.')
        return validate_doctor_email_value(matches[0])

    def register_user(self):
        try:
            name = self.reg_name_edit.text().strip()
            email = validate_doctor_email_value(self.reg_email_edit.text())
            password = self.reg_password_edit.text()
            password2 = self.reg_password2_edit.text()
            if not name:
                raise ValueError('Adj meg nevet.')
            if len(password) < 8:
                raise ValueError('A jelszó legyen legalább 8 karakter.')
            if password != password2:
                raise ValueError('A két jelszó nem egyezik.')
            existing = self.find_user(email)
            if existing and existing.get('verified'):
                raise ValueError('Ez az e-mail cím már regisztrált és visszaigazolt.')
            code = secrets.token_hex(3).upper()
            record = existing or {}
            record.update({
                'name': name, 'email': email, 'username': email.split('@')[0], 'password_hash': hash_password_value(password),
                'role': ('moderator' if email == MAIN_MODERATOR_EMAIL else 'orvos'), 'verified': False, 'active': True, 'verification_code': code,
                'verification_sent_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            })
            if existing is None:
                self.users_data.append(record)
            self.save_users()
            ok, msg = self.send_verification_email(email, code)
            self.verify_email_edit.setText(email)
            self.verify_code_edit.setText(code)
            self.login_identifier_combo.setEditText(record.get('username', email.split('@')[0]))
            self.refresh_login_autofill()
            if not ok:
                msg = f"{msg}\n\nA regisztráció rögzítve lett, a visszaigazolás helyben folytatható az ellenőrző kóddal."
            QMessageBox.information(self, 'Regisztráció', msg)
        except Exception as e:
            QMessageBox.warning(self, 'Regisztrációs hiba', str(e))

    def verify_user(self):
        try:
            email = validate_doctor_email_value(self.verify_email_edit.text())
            code = self.verify_code_edit.text().strip().upper()
            if not code:
                raise ValueError('Add meg az ellenőrző kódot.')
            user = self.find_user(email)
            if not user:
                raise ValueError('Nincs ilyen regisztrált felhasználó.')
            if code != str(user.get('verification_code', '')).strip().upper():
                raise ValueError('Az ellenőrző kód hibás.')
            user['verified'] = True
            user['verification_code'] = ''
            user['verified_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            self.save_users()
            self.refresh_login_autofill()
            QMessageBox.information(self, 'Sikeres visszaigazolás', 'Az e-mail cím hitelesítve lett. Most már be tudsz jelentkezni.')
        except Exception as e:
            QMessageBox.warning(self, 'Visszaigazolási hiba', str(e))

    def login_user(self):
        try:
            email = self.resolve_login_identifier(self.login_identifier_combo.currentText())
            password = self.login_password_edit.text()
            user = self.find_user(email)
            if not user:
                raise ValueError('Nincs ilyen regisztrált felhasználó.')
            if not user.get('verified'):
                raise ValueError('Az e-mail cím még nincs visszaigazolva.')
            if not user.get('active', True):
                raise ValueError('Ez a felhasználó le van tiltva.')
            if user.get('password_hash') != hash_password_value(password):
                raise ValueError('Hibás jelszó.')
            self.current_user = dict(user)
            self.accept()
        except Exception as e:
            self.login_info.setText(str(e))
            QMessageBox.warning(self, 'Bejelentkezési hiba', str(e))

class TDMMainWindow(QMainWindow):
    def __init__(self, current_user: Optional[dict] = None):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(1580, 980)
        self.setMinimumSize(1220, 760)
        self.empirical_data = load_empirical_targets()
        self.results: Dict[str, object] = {}
        self.latest_report = ""
        self.current_user: Optional[dict] = dict(current_user) if current_user else None
        self.users_data: List[dict] = ensure_special_roles(self.load_users())
        self.infectologists_data: List[dict] = load_infectologists_file()
        self.smtp_settings: dict = load_settings_file()
        self.history_data: List[dict] = self.load_history()
        self.save_users()
        self._build_ui()
        self.reset_defaults()
        self.apply_theme()
        self.refresh_role_dependent_ui()

    def _make_scroll_tab(self, inner_widget: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setWidget(inner_widget)
        return scroll

    def refresh_role_dependent_ui(self):
        role = str((self.current_user or {}).get("role", "")).strip().lower()
        is_moderator = role == "moderator"
        is_infectologist = role == "infektologus"
        if hasattr(self, "delete_history_btn"):
            self.delete_history_btn.setVisible(is_moderator)
            self.delete_history_btn.setEnabled(is_moderator)
        if hasattr(self, "save_history_changes_btn"):
            self.save_history_changes_btn.setEnabled(bool(self.current_user))
        if hasattr(self, "clear_form_btn"):
            self.clear_form_btn.setEnabled(True)
        if hasattr(self, "send_bulk_btn"):
            self.send_bulk_btn.setVisible(is_infectologist)
            self.send_bulk_btn.setEnabled(is_infectologist)
        if hasattr(self, "bulk_send_btn"):
            self.bulk_send_btn.setVisible(is_infectologist)
            self.bulk_send_btn.setEnabled(is_infectologist)

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        theme_row = QFrame()
        theme_row.setObjectName("ThemeBar")
        theme_layout = QHBoxLayout(theme_row)
        theme_layout.setContentsMargins(14, 10, 14, 10)
        theme_layout.setSpacing(8)
        theme_layout.addWidget(QLabel("Téma"))
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["Light Clinical", "Midnight Blue", "Emerald Dark", "Graphite"])
        self.theme_combo.currentIndexChanged.connect(self.apply_theme)
        theme_layout.addWidget(self.theme_combo)
        theme_layout.addSpacing(18)
        theme_layout.addWidget(QLabel("Modul"))
        self.module_combo = QComboBox()
        self.module_combo.addItems(["TDM", "Statisztika"])
        self.module_combo.currentIndexChanged.connect(self.switch_module)
        theme_layout.addWidget(self.module_combo)
        theme_layout.addStretch(1)
        root.addWidget(theme_row)

        header = QFrame()
        header.setObjectName("Header")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(18, 16, 18, 16)
        header_layout.setSpacing(2)
        self.header_title = QLabel("Klinikai TDM platform")
        self.header_title.setObjectName("HeaderTitle")
        self.header_subtitle = QLabel(
            "Vancomycin, linezolid és amikacin modulok magyar felülettel, guide/evidence/empirikus támogatással. "
            "A számolás prototípus jellegű, lokális validáció szükséges."
        )
        self.header_subtitle.setObjectName("HeaderSubtitle")
        self.header_subtitle.setWordWrap(True)
        header_layout.addWidget(self.header_title)
        header_layout.addWidget(self.header_subtitle)
        root.addWidget(header)

        self.module_stack = QTabWidget()
        self.module_stack.setDocumentMode(True)
        self.module_stack.tabBar().hide()
        root.addWidget(self.module_stack, 1)

        self.tdm_widget = QWidget()
        self.stats_module = QWidget()
        self.module_stack.addTab(self.tdm_widget, "TDM")
        self.module_stack.addTab(self.stats_module, "Statisztika")

        self._build_tdm_widget()
        self._build_stats_module()
        self._build_menu()
        self.switch_module()

    def _build_tdm_widget(self):
        root = QVBoxLayout(self.tdm_widget)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        action_bar = QFrame()
        action_bar.setObjectName("ActionBar")
        action_layout = QHBoxLayout(action_bar)
        action_layout.setContentsMargins(14, 12, 14, 12)
        action_layout.addWidget(QLabel("Antibiotikum"))
        self.antibiotic_combo = QComboBox()
        self.antibiotic_combo.addItems(["Vancomycin", "Linezolid", "Amikacin"])
        self.antibiotic_combo.currentTextChanged.connect(self.on_antibiotic_change)
        action_layout.addWidget(self.antibiotic_combo)
        action_layout.addWidget(QLabel("Módszer"))
        self.method_combo = QComboBox()
        self.method_combo.currentTextChanged.connect(self.refresh_context_panels)
        action_layout.addWidget(self.method_combo)
        action_layout.addWidget(QLabel("Empirikus stratégia"))
        self.empirical_mode_combo = QComboBox()
        self.empirical_mode_combo.addItems(["Worst-case / high-risk", "Irányított / ismert MIC"])
        self.empirical_mode_combo.currentTextChanged.connect(self.refresh_context_panels)
        action_layout.addWidget(self.empirical_mode_combo)
        self.calc_btn = QPushButton("Számítás")
        self.calc_btn.setObjectName("PrimaryButton")
        self.calc_btn.clicked.connect(self.calculate)
        self.reset_btn = QPushButton("Alapértékek")
        self.reset_btn.clicked.connect(self.reset_defaults)
        action_layout.addStretch(1)
        action_layout.addWidget(self.calc_btn)
        action_layout.addWidget(self.reset_btn)
        root.addWidget(action_bar)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        root.addWidget(self.tabs, 1)

        self.tabs.setUsesScrollButtons(True)
        self.tabs.setElideMode(Qt.ElideNone)

        self.input_tab = QWidget()
        self.results_tab = QWidget()
        self.plot_tab = QWidget()
        self.info_tab = QWidget()
        self.empirical_tab = QWidget()
        self.history_tab = QWidget()
        self.export_tab = QWidget()

        self.tabs.addTab(self._make_scroll_tab(self.input_tab), "Bemenet")
        self.tabs.addTab(self.results_tab, "Eredmények")
        self.tabs.addTab(self._make_scroll_tab(self.info_tab), "Info és citációk")
        self.tabs.addTab(self._make_scroll_tab(self.empirical_tab), "Empirikus támogatás")
        self.tabs.addTab(self.history_tab, "Előző mérések")
        self.tabs.addTab(self._make_scroll_tab(self.export_tab), "Export")

        self._build_input_tab()
        self._build_results_tab()
        self._build_plot_tab()
        self._build_info_tab()
        self._build_empirical_tab()
        self._build_history_tab()
        self._build_export_tab()
        self.on_antibiotic_change()

    def _build_input_tab(self):
        layout = QVBoxLayout(self.input_tab)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(10)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        layout.addWidget(splitter, 1)
        left = QWidget()
        right = QWidget()
        splitter.addWidget(left)
        splitter.addWidget(right)
        left.setMinimumWidth(520)
        right.setMinimumWidth(340)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([900, 620])

        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(10)

        self.mode_frame = QFrame()
        self.mode_frame.setObjectName("HintBox")
        mode_layout = QHBoxLayout(self.mode_frame)
        mode_layout.setContentsMargins(14, 12, 14, 12)
        mode_layout.addWidget(QLabel("Mintavételi mód"))
        self.sample_mode_combo = QComboBox()
        self.sample_mode_combo.addItems(["Klinikai mód (dátum-idő)", "Egyszerű mód (relatív órák)"])
        self.sample_mode_combo.currentIndexChanged.connect(self.update_sampling_visibility)
        mode_layout.addWidget(self.sample_mode_combo)
        mode_layout.addStretch(1)
        left_layout.addWidget(self.mode_frame)

        common_box = QGroupBox("Közös beteg- és sémaadatok")
        common_form = QFormLayout(common_box)
        self.user_edit = QLineEdit(); self.user_edit.setReadOnly(True); self.patient_edit = QLineEdit()
        self.sex_combo = QComboBox(); self.sex_combo.addItems(["férfi", "nő"])
        self.age_edit = QLineEdit(); self.weight_edit = QLineEdit(); self.height_edit = QLineEdit()
        self.scr_edit = QLineEdit(); self.mic_edit = QLineEdit(); self.dose_edit = QLineEdit()
        self.tau_edit = QLineEdit(); self.tinf_edit = QLineEdit(); self.rounding_edit = QLineEdit()
        self.target_auc_edit = QLineEdit()
        common_form.addRow("Felhasználó", self.user_edit)
        common_form.addRow("Beteg azonosító / jel", self.patient_edit)
        common_form.addRow("Nem", self.sex_combo)
        common_form.addRow("Életkor (év)", self.age_edit)
        common_form.addRow("Testsúly (kg)", self.weight_edit)
        common_form.addRow("Magasság (cm)", self.height_edit)
        common_form.addRow("Kreatinin (µmol/L)", self.scr_edit)
        common_form.addRow("MIC (mg/L, opcionális)", self.mic_edit)
        common_form.addRow("Adag (mg)", self.dose_edit)
        common_form.addRow("Intervallum τ (óra)", self.tau_edit)
        common_form.addRow("Infúziós idő (óra)", self.tinf_edit)
        common_form.addRow("Cél AUC24 (ha releváns)", self.target_auc_edit)
        common_form.addRow("Kerekítés (mg)", self.rounding_edit)
        left_layout.addWidget(common_box)

        self.clinical_box = QGroupBox("Klinikai mintavétel")
        clin_form = QFormLayout(self.clinical_box)
        self.last_infusion_dt = QDateTimeEdit(); self.last_infusion_dt.setCalendarPopup(True)
        self.sample1_dt = QDateTimeEdit(); self.sample1_dt.setCalendarPopup(True)
        self.sample2_dt = QDateTimeEdit(); self.sample2_dt.setCalendarPopup(True)
        self.level1_clin_edit = QLineEdit(); self.level2_clin_edit = QLineEdit()
        clin_form.addRow("Utolsó releváns infúzió kezdete", self.last_infusion_dt)
        clin_form.addRow("1. minta ideje", self.sample1_dt)
        clin_form.addRow("1. szint (mg/L)", self.level1_clin_edit)
        clin_form.addRow("2. minta ideje", self.sample2_dt)
        clin_form.addRow("2. szint (mg/L)", self.level2_clin_edit)
        left_layout.addWidget(self.clinical_box)

        self.relative_box = QGroupBox("Relatív mintavétel")
        rel_form = QFormLayout(self.relative_box)
        self.level1_rel_edit = QLineEdit(); self.t1_edit = QLineEdit()
        self.level2_rel_edit = QLineEdit(); self.t2_edit = QLineEdit()
        self.level3_edit = QLineEdit(); self.t3_edit = QLineEdit()
        rel_form.addRow("1. szint (mg/L)", self.level1_rel_edit)
        rel_form.addRow("1. minta ideje T1 (óra)", self.t1_edit)
        rel_form.addRow("2. szint (mg/L)", self.level2_rel_edit)
        rel_form.addRow("2. minta ideje T2 (óra)", self.t2_edit)
        rel_form.addRow("3. szint (mg/L, opcionális)", self.level3_edit)
        rel_form.addRow("3. minta ideje T3 (óra, opcionális)", self.t3_edit)
        left_layout.addWidget(self.relative_box)

        flags_box = QGroupBox("Klinikai flag-ek")
        flags_form = QFormLayout(flags_box)
        self.icu_check = QCheckBox("ICU / kritikus állapot")
        self.hematology_check = QCheckBox("Hematológiai populáció")
        self.unstable_renal_check = QCheckBox("Instabil vesefunkció / CRRT-közeli")
        self.obesity_check = QCheckBox("Obesitas / nagyobb Vd valószínű")
        self.neutropenia_check = QCheckBox("Neutropenia / magas rizikó")
        for chk in [self.icu_check, self.hematology_check, self.unstable_renal_check, self.obesity_check, self.neutropenia_check]:
            flags_form.addRow("", chk)
        left_layout.addWidget(flags_box)

        log_box = QGroupBox("Naplózás / döntés")
        log_form = QFormLayout(log_box)
        self.decision_edit = QPlainTextEdit()
        self.decision_edit.setPlaceholderText("Pl. dózis marad / emelés / csökkentés / újraszint mikor / rövid indoklás")
        self.decision_edit.setMaximumHeight(90)
        log_form.addRow("Döntés / megjegyzés", self.decision_edit)
        left_layout.addWidget(log_box)
        left_layout.addStretch(1)

        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(10)

        card_grid = QGridLayout()
        self.card_primary = StatCard("Fő cél")
        self.card_secondary = StatCard("Másodlagos")
        self.card_regimen = StatCard("Ajánlott séma")
        self.card_status = StatCard("Státusz")
        card_grid.addWidget(self.card_primary, 0, 0)
        card_grid.addWidget(self.card_secondary, 0, 1)
        card_grid.addWidget(self.card_regimen, 1, 0)
        card_grid.addWidget(self.card_status, 1, 1)
        right_layout.addLayout(card_grid)

        self.quick_context = QTextBrowser()
        self.quick_context.setOpenExternalLinks(True)
        self.quick_context.setMinimumHeight(260)
        right_layout.addWidget(self.quick_context, 1)

    def _build_results_tab(self):
        layout = QVBoxLayout(self.results_tab)
        layout.setContentsMargins(6, 6, 6, 6)
        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        layout.addWidget(splitter, 1)
        self.result_text = QPlainTextEdit()
        self.result_text.setReadOnly(True)
        self.result_text.setMinimumWidth(420)
        splitter.addWidget(self.result_text)
        if WEB_OK:
            self.plot_view = QWebEngineView()
            self.plot_view.setMinimumWidth(420)
        else:
            self.plot_view = QTextBrowser()
            self.plot_view.setMinimumWidth(420)
            self.plot_view.setHtml("<h3>Plotly előnézet nem érhető el: PySide6-WebEngine hiányzik.</h3>")
        splitter.addWidget(self.plot_view)
        splitter.setSizes([520, 780])

    def _build_plot_tab(self):
        layout = QVBoxLayout(self.plot_tab)
        layout.setContentsMargins(6, 6, 6, 6)
        info = QTextBrowser()
        info.setHtml("<p>A grafikon az <b>Eredmények</b> fül jobb oldalán látható.</p>")
        layout.addWidget(info)

    def _build_info_tab(self):
        layout = QVBoxLayout(self.info_tab)
        splitter = QSplitter(Qt.Vertical)
        splitter.setChildrenCollapsible(False)
        layout.addWidget(splitter, 1)
        self.guide_browser = QTextBrowser()
        self.guide_browser.setOpenExternalLinks(True)
        self.evidence_browser = QTextBrowser()
        self.evidence_browser.setOpenExternalLinks(True)
        self.guide_browser.setMinimumHeight(260)
        self.evidence_browser.setMinimumHeight(220)
        splitter.addWidget(self.guide_browser)
        splitter.addWidget(self.evidence_browser)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([420, 260])

    def _build_empirical_tab(self):
        layout = QVBoxLayout(self.empirical_tab)
        layout.setContentsMargins(6, 6, 6, 6)
        self.empirical_browser = QTextBrowser()
        self.empirical_browser.setMinimumHeight(520)
        self.empirical_browser.setOpenExternalLinks(True)
        layout.addWidget(self.empirical_browser)

    def _build_history_tab(self):
        layout = QVBoxLayout(self.history_tab)
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("Szűrés felhasználó szerint"))
        self.history_user_filter = QComboBox()
        self.history_user_filter.currentTextChanged.connect(self.refresh_history_table)
        toolbar.addWidget(self.history_user_filter)
        self.reload_history_btn = QPushButton("Frissítés")
        self.reload_history_btn.clicked.connect(self.reload_history)
        toolbar.addWidget(self.reload_history_btn)
        self.clear_form_btn = QPushButton("Űrlap kitöltése kijelölt sorból")
        self.clear_form_btn.clicked.connect(self.load_selected_history_into_form)
        toolbar.addWidget(self.clear_form_btn)
        self.save_history_changes_btn = QPushButton("Kijelölt sor mentése")
        self.save_history_changes_btn.clicked.connect(self.update_selected_history_from_form)
        toolbar.addWidget(self.save_history_changes_btn)
        self.delete_history_btn = QPushButton("Kijelölt sor törlése")
        self.delete_history_btn.clicked.connect(self.delete_selected_history)
        self.delete_history_btn.setEnabled(False)
        toolbar.addWidget(self.delete_history_btn)
        toolbar.addStretch(1)
        layout.addLayout(toolbar)

        splitter = QSplitter(Qt.Vertical)
        splitter.setChildrenCollapsible(False)
        layout.addWidget(splitter, 1)
        self.history_table = QTableWidget(0, 8)
        self.history_table.setHorizontalHeaderLabels([
            "Időpont", "Felhasználó", "Beteg", "Antibiotikum", "Módszer", "Státusz", "Javaslat", "Döntés"
        ])
        self.history_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.history_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.history_table.setSelectionMode(QTableWidget.ExtendedSelection)
        self.history_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.history_table.itemSelectionChanged.connect(self.show_history_detail)
        self.history_table.setMinimumHeight(280)
        splitter.addWidget(self.history_table)
        self.history_detail = QTextBrowser()
        self.history_detail.setMinimumHeight(180)
        self.history_detail.setOpenExternalLinks(True)
        splitter.addWidget(self.history_detail)
        splitter.setSizes([420, 260])
        self.refresh_history_filter()
        self.refresh_history_table()
        self.refresh_role_dependent_ui()

    def _build_user_tab(self):
        layout = QVBoxLayout(self.user_tab)
        title = QLabel("Orvos felhasználói hozzáférés")
        title.setObjectName("SectionTitle")
        desc = QLabel("Alapból csak @dpckorhaz.hu e-mail címmel lehet regisztrálni. A regisztráció után e-mailes visszaigazolás szükséges.")
        desc.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(desc)

        status_box = QGroupBox("Aktuális állapot")
        status_form = QFormLayout(status_box)
        self.user_status_label = QLabel("Nincs bejelentkezve")
        self.user_status_detail = QLabel("A számításhoz hitelesített orvos felhasználó szükséges.")
        self.user_status_detail.setWordWrap(True)
        status_form.addRow("Állapot", self.user_status_label)
        status_form.addRow("Részletek", self.user_status_detail)
        layout.addWidget(status_box)

        reg_box = QGroupBox("Új orvos regisztráció")
        reg_form = QFormLayout(reg_box)
        self.reg_name_edit = QLineEdit()
        self.reg_email_edit = QLineEdit()
        self.reg_password_edit = QLineEdit(); self.reg_password_edit.setEchoMode(QLineEdit.Password)
        self.reg_password2_edit = QLineEdit(); self.reg_password2_edit.setEchoMode(QLineEdit.Password)
        reg_form.addRow("Név", self.reg_name_edit)
        reg_form.addRow("Kórházi e-mail", self.reg_email_edit)
        reg_form.addRow("Jelszó", self.reg_password_edit)
        reg_form.addRow("Jelszó újra", self.reg_password2_edit)
        reg_buttons = QHBoxLayout()
        self.register_btn = QPushButton("Regisztráció indítása")
        self.register_btn.clicked.connect(self.register_user)
        self.verify_btn = QPushButton("E-mail visszaigazolása")
        self.verify_btn.clicked.connect(self.verify_user_dialog)
        reg_buttons.addWidget(self.register_btn)
        reg_buttons.addWidget(self.verify_btn)
        reg_buttons.addStretch(1)
        reg_form.addRow(reg_buttons)
        layout.addWidget(reg_box)

        login_box = QGroupBox("Bejelentkezés")
        login_form = QFormLayout(login_box)
        self.login_identifier_combo = QComboBox()
        self.login_identifier_combo.setEditable(True)
        self.login_identifier_combo.setInsertPolicy(QComboBox.NoInsert)
        self.login_identifier_combo.setMinimumContentsLength(28)
        self.login_identifier_combo.lineEdit().setPlaceholderText('felhasználónév vagy e-mail')
        self.refresh_login_autofill()
        self.login_password_edit = QLineEdit(); self.login_password_edit.setEchoMode(QLineEdit.Password)
        login_form.addRow("Felhasználónév / e-mail", self.login_identifier_combo)
        login_form.addRow("Jelszó", self.login_password_edit)
        login_buttons = QHBoxLayout()
        self.login_btn = QPushButton("Bejelentkezés")
        self.login_btn.clicked.connect(self.login_user)
        self.logout_btn = QPushButton("Kijelentkezés")
        self.logout_btn.clicked.connect(self.logout_user)
        login_buttons.addWidget(self.login_btn)
        login_buttons.addWidget(self.logout_btn)
        login_buttons.addStretch(1)
        login_form.addRow(login_buttons)
        layout.addWidget(login_box)
        layout.addStretch(1)
        self.update_user_status_ui()

    def _build_export_tab(self):
        layout = QVBoxLayout(self.export_tab)
        layout.setContentsMargins(6, 6, 6, 6)
        title = QLabel("Export")
        title.setObjectName("SectionTitle")
        desc = QLabel("TXT és PDF mentés. Innen közvetlenül el is küldhető a riport a beállított infektológus címzettek egyikének.")
        desc.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(desc)

        file_box = QGroupBox("Fájl export")
        file_row = QHBoxLayout(file_box)
        b1 = QPushButton("TXT riport mentése")
        b1.clicked.connect(self.save_report_txt)
        b3 = QPushButton("PDF riport mentése vizualizációval")
        b3.clicked.connect(self.save_report_pdf)
        file_row.addWidget(b1)
        file_row.addWidget(b3)
        file_row.addStretch(1)
        layout.addWidget(file_box)

        mail_box = QGroupBox("Küldés az infektológus részére")
        mail_form = QFormLayout(mail_box)
        self.export_infectologist_combo = QComboBox()
        self.export_infectologist_combo.setMinimumWidth(380)
        self.refresh_infectologist_combo()
        self.export_mail_note = QLineEdit()
        self.export_mail_note.setPlaceholderText("Rövid kísérő megjegyzés (opcionális)")
        self.send_single_btn = QPushButton("Küldés riportként (TXT + grafikon + PDF)")
        self.send_single_btn.clicked.connect(self.send_report_to_infectologist)
        self.send_bulk_btn = QPushButton("Kijelölt history sorok tömeges küldése")
        self.send_bulk_btn.clicked.connect(self.send_selected_history_to_infectologist)
        mail_form.addRow("Infektológus", self.export_infectologist_combo)
        mail_form.addRow("Megjegyzés", self.export_mail_note)
        mail_form.addRow("", self.send_single_btn)
        mail_form.addRow("", self.send_bulk_btn)
        layout.addWidget(mail_box)

        self.export_status = QLabel("Még nincs mentett riport.")
        self.export_status.setWordWrap(True)
        layout.addWidget(self.export_status)
        layout.addStretch(1)


    def _build_settings_dialog_content(self, parent_widget: QWidget):
        layout = QVBoxLayout(parent_widget)
        title = QLabel("Beállítások")
        title.setObjectName("SectionTitle")
        desc = QLabel("A bejelentkezett orvos itt módosíthatja a megjelenített nevét és a jelszavát. A változtatások helyben, a felhasználói adatbázisban mentődnek.")
        desc.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(desc)

        profile_box = QGroupBox("Aktív felhasználó")
        profile_form = QFormLayout(profile_box)
        self.settings_email_label = QLabel("—")
        self.settings_name_label = QLabel("—")
        self.settings_verified_label = QLabel("—")
        self.settings_role_label = QLabel("—")
        profile_form.addRow("E-mail", self.settings_email_label)
        profile_form.addRow("Jelenlegi név", self.settings_name_label)
        profile_form.addRow("Szerepkör", self.settings_role_label)
        profile_form.addRow("Visszaigazolás", self.settings_verified_label)
        layout.addWidget(profile_box)

        name_box = QGroupBox("Név módosítása")
        name_form = QFormLayout(name_box)
        self.settings_new_name_edit = QLineEdit()
        self.settings_new_name_edit.setPlaceholderText("Új megjelenített név")
        self.settings_save_name_btn = QPushButton("Név mentése")
        self.settings_save_name_btn.clicked.connect(self.change_display_name)
        name_form.addRow("Új név", self.settings_new_name_edit)
        name_form.addRow("", self.settings_save_name_btn)
        layout.addWidget(name_box)

        pwd_box = QGroupBox("Jelszó módosítása")
        pwd_form = QFormLayout(pwd_box)
        self.settings_old_password_edit = QLineEdit(); self.settings_old_password_edit.setEchoMode(QLineEdit.Password)
        self.settings_new_password_edit = QLineEdit(); self.settings_new_password_edit.setEchoMode(QLineEdit.Password)
        self.settings_new_password2_edit = QLineEdit(); self.settings_new_password2_edit.setEchoMode(QLineEdit.Password)
        self.settings_save_password_btn = QPushButton("Jelszó módosítása")
        self.settings_save_password_btn.clicked.connect(self.change_password)
        pwd_form.addRow("Jelenlegi jelszó", self.settings_old_password_edit)
        pwd_form.addRow("Új jelszó", self.settings_new_password_edit)
        pwd_form.addRow("Új jelszó újra", self.settings_new_password2_edit)
        pwd_form.addRow("", self.settings_save_password_btn)
        layout.addWidget(pwd_box)

        self.admin_users_box = QGroupBox("Aktív regisztrált profilok")
        admin_users_layout = QVBoxLayout(self.admin_users_box)
        self.settings_users_table = QTableWidget(0, 5)
        self.settings_users_table.setHorizontalHeaderLabels(["Név", "E-mail", "Szerepkör", "Visszaigazolt", "Aktív"])
        self.settings_users_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        admin_users_layout.addWidget(self.settings_users_table)
        admin_btns = QHBoxLayout()
        self.make_moderator_btn = QPushButton("Kijelölt profil moderátorrá tétele")
        self.make_moderator_btn.clicked.connect(lambda: self.set_selected_user_role("moderator"))
        self.make_doctor_btn = QPushButton("Orvos szerepkör")
        self.make_doctor_btn.clicked.connect(lambda: self.set_selected_user_role("orvos"))
        self.make_infectologist_btn = QPushButton("Infektológus szerepkör")
        self.make_infectologist_btn.clicked.connect(lambda: self.set_selected_user_role("infektologus"))
        self.disable_user_btn = QPushButton("Felhasználó tiltása")
        self.disable_user_btn.clicked.connect(lambda: self.set_selected_user_active(False))
        self.enable_user_btn = QPushButton("Felhasználó engedélyezése")
        self.enable_user_btn.clicked.connect(lambda: self.set_selected_user_active(True))
        self.delete_user_btn = QPushButton("Felhasználó törlése")
        self.delete_user_btn.clicked.connect(self.delete_selected_user)
        admin_btns.addWidget(self.make_moderator_btn)
        admin_btns.addWidget(self.make_doctor_btn)
        admin_btns.addWidget(self.make_infectologist_btn)
        admin_btns.addWidget(self.disable_user_btn)
        admin_btns.addWidget(self.enable_user_btn)
        admin_btns.addWidget(self.delete_user_btn)
        admin_btns.addStretch(1)
        admin_users_layout.addLayout(admin_btns)
        layout.addWidget(self.admin_users_box)

        self.manual_user_box = QGroupBox("Felhasználó kézi hozzáadása")
        manual_layout = QFormLayout(self.manual_user_box)
        self.manual_user_name_edit = QLineEdit()
        self.manual_user_email_edit = QLineEdit()
        self.manual_user_role_combo = QComboBox()
        self.manual_user_role_combo.addItems(["orvos", "infektologus", "moderator"])
        self.manual_add_user_btn = QPushButton("Felhasználó létrehozása és jelszó kiküldése")
        self.manual_add_user_btn.clicked.connect(self.add_user_manually)
        manual_layout.addRow("Név", self.manual_user_name_edit)
        manual_layout.addRow("E-mail", self.manual_user_email_edit)
        manual_layout.addRow("Szerepkör", self.manual_user_role_combo)
        manual_layout.addRow("", self.manual_add_user_btn)
        layout.addWidget(self.manual_user_box)


        self.infecto_box = QGroupBox("Infektológus címzettek")
        infecto_layout = QVBoxLayout(self.infecto_box)
        infecto_form = QFormLayout()
        self.infectologist_name_edit = QLineEdit()
        self.infectologist_email_edit = QLineEdit()
        infecto_form.addRow("Név", self.infectologist_name_edit)
        infecto_form.addRow("E-mail", self.infectologist_email_edit)
        infecto_layout.addLayout(infecto_form)
        infecto_btns = QHBoxLayout()
        self.add_infectologist_btn = QPushButton("Infektológus hozzáadása")
        self.add_infectologist_btn.clicked.connect(self.add_infectologist)
        self.remove_infectologist_btn = QPushButton("Kijelölt infektológus törlése")
        self.remove_infectologist_btn.clicked.connect(self.remove_selected_infectologist)
        infecto_btns.addWidget(self.add_infectologist_btn)
        infecto_btns.addWidget(self.remove_infectologist_btn)
        infecto_btns.addStretch(1)
        infecto_layout.addLayout(infecto_btns)
        self.infectologists_table = QTableWidget(0, 2)
        self.infectologists_table.setHorizontalHeaderLabels(["Név", "E-mail"])
        self.infectologists_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        infecto_layout.addWidget(self.infectologists_table)
        layout.addWidget(self.infecto_box)

        self.smtp_box = QGroupBox("SMTP beállítások")
        smtp_layout = QFormLayout(self.smtp_box)
        self.smtp_host_edit = QLineEdit()
        self.smtp_port_edit = QLineEdit()
        self.smtp_user_edit = QLineEdit()
        self.smtp_from_edit = QLineEdit()
        self.smtp_pass_edit = QLineEdit(); self.smtp_pass_edit.setEchoMode(QLineEdit.Password)
        self.smtp_starttls_combo = QComboBox(); self.smtp_starttls_combo.addItems(["Igen", "Nem"])
        self.smtp_ssl_combo = QComboBox(); self.smtp_ssl_combo.addItems(["Nem", "Igen"])
        self.smtp_save_btn = QPushButton("SMTP mentése")
        self.smtp_save_btn.clicked.connect(self.save_smtp_settings)
        self.smtp_test_btn = QPushButton("SMTP teszt")
        self.smtp_test_btn.clicked.connect(self.test_smtp_settings)
        smtp_layout.addRow("SMTP szerver", self.smtp_host_edit)
        smtp_layout.addRow("Port", self.smtp_port_edit)
        smtp_layout.addRow("Felhasználó", self.smtp_user_edit)
        smtp_layout.addRow("Feladó cím", self.smtp_from_edit)
        smtp_layout.addRow("Jelszó", self.smtp_pass_edit)
        smtp_layout.addRow("STARTTLS", self.smtp_starttls_combo)
        smtp_layout.addRow("SSL", self.smtp_ssl_combo)
        smtp_btns = QHBoxLayout()
        smtp_btns.addWidget(self.smtp_save_btn)
        smtp_btns.addWidget(self.smtp_test_btn)
        smtp_btns.addStretch(1)
        smtp_layout.addRow("", smtp_btns)
        layout.addWidget(self.smtp_box)

        self.settings_hint = QLabel("A beállítások módosításához előbb jelentkezz be.")
        self.settings_hint.setWordWrap(True)
        layout.addWidget(self.settings_hint)
        layout.addStretch(1)
        self.refresh_settings_tab()
        if hasattr(self, "delete_history_btn"):
            self.delete_history_btn.setEnabled(bool(self.current_user and self.current_user.get("role") == "moderator"))

    def _build_stats_module(self):
        layout = QVBoxLayout(self.stats_module)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        info = QFrame()
        info.setObjectName("HintBox")
        info_layout = QVBoxLayout(info)
        info_layout.setContentsMargins(18, 16, 18, 16)
        title = QLabel("Statisztikai modul")
        title.setObjectName("SectionTitle")
        subtitle = QLabel(
            "Ez a modul elő van készítve a későbbi statisztikai és surveillance workflow-khoz. "
            "Ide kerülhetnek később leíró statisztikák, ROC-analízis, regressziók, trendek és kumulatív antibiogramok."
        )
        subtitle.setWordWrap(True)
        info_layout.addWidget(title)
        info_layout.addWidget(subtitle)
        layout.addWidget(info)
        placeholder = QPlainTextEdit()
        placeholder.setReadOnly(True)
        placeholder.setPlainText(
            "Statisztikai modul – jelenleg váz.\n\n"
            "Tervezett hely a jövőbeli funkcióknak:\n"
            "- surveillance trendek\n"
            "- leíró statisztika\n"
            "- ROC / cutoff analízis\n"
            "- regressziók\n"
            "- export\n"
        )
        layout.addWidget(placeholder, 1)

    def _build_menu(self):
        menu = self.menuBar().addMenu("Fájl")
        s1 = QAction("Beállítások", self)
        s1.triggered.connect(self.open_settings_dialog)
        menu.addAction(s1)
        logout_action = QAction("Kijelentkezés", self)
        logout_action.triggered.connect(self.logout_to_login)
        menu.addAction(logout_action)
        a3 = QAction("Kilépés", self)
        a3.triggered.connect(self.close)
        menu.addAction(a3)

    def logout_to_login(self):
        answer = QMessageBox.question(
            self,
            'Kijelentkezés',
            'Biztosan kijelentkezel? A program visszatér a belépési ablakra.',
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        self.hide()
        auth = AuthDialog()
        if auth.exec() == QDialog.Accepted and auth.current_user:
            self.current_user = dict(auth.current_user)
            self.users_data = ensure_special_roles(self.load_users())
            self.infectologists_data = load_infectologists_file()
            self.smtp_settings = load_settings_file()
            self.history_data = self.load_history()
            self.refresh_history_table()
            self.refresh_settings_tab()
            self.refresh_role_dependent_ui()
            self.show()
            return
        QApplication.instance().quit()

    def open_settings_dialog(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Beállítások")
        dlg.resize(1100, 760)
        dlg.setMinimumSize(900, 620)
        outer = QVBoxLayout(dlg)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        host = QWidget()
        scroll.setWidget(host)
        outer.addWidget(scroll)
        self._build_settings_dialog_content(host)
        self.refresh_settings_tab()
        dlg.exec()

    def load_users(self) -> List[dict]:
        if not os.path.exists(USERS_PATH):
            return []
        try:
            with open(USERS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                for user in data:
                    if isinstance(user, dict):
                        user.setdefault("active", True)
                        user.setdefault("username", str(user.get("email", "")).split("@")[0] if user.get("email") else "")
                return data
            return []
        except Exception:
            return []

    def save_users(self):
        try:
            self.users_data = ensure_special_roles(self.users_data)
            with open(USERS_PATH, "w", encoding="utf-8") as f:
                json.dump(self.users_data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def save_infectologists(self):
        try:
            save_infectologists_file(self.infectologists_data)
        except Exception:
            pass

    @staticmethod
    def normalize_email(email: str) -> str:
        return str(email).strip().lower()

    @staticmethod
    def hash_password(password: str) -> str:
        return hashlib.sha256(password.encode("utf-8")).hexdigest()

    def validate_doctor_email(self, email: str) -> str:
        email = self.normalize_email(email)
        if not email or "@" not in email:
            raise ValueError("Adj meg egy érvényes e-mail címet.")
        if not email.endswith(f"@{ALLOWED_EMAIL_DOMAIN}"):
            raise ValueError(f"Csak @{ALLOWED_EMAIL_DOMAIN} e-mail címmel lehet regisztrálni.")
        return email

    def validate_general_email(self, email: str) -> str:
        email = self.normalize_email(email)
        if not email or "@" not in email:
            raise ValueError("Adj meg egy érvényes e-mail címet.")
        local, _, domain = email.partition("@")
        if not local or not domain or "." not in domain:
            raise ValueError("Adj meg egy érvényes e-mail címet.")
        return email

    def find_user(self, email: str) -> Optional[dict]:
        email = self.normalize_email(email)
        for user in self.users_data:
            if self.normalize_email(user.get("email", "")) == email:
                return user
        return None

    def send_verification_email(self, email: str, code: str) -> Tuple[bool, str]:
        smtp = get_smtp_settings()
        host = smtp["host"]
        port = smtp["port"]
        smtp_user = smtp["smtp_user"]
        smtp_pass = smtp["smtp_pass"]
        sender = smtp["sender"]
        use_ssl = smtp["use_ssl"]
        use_starttls = smtp["use_starttls"]
        if not host or not sender or not smtp_pass:
            return False, f"Fejlesztői mód: SMTP jelszó nincs beállítva. Ellenőrző kód: {code}"

        msg = EmailMessage()
        msg["Subject"] = "Klinikai TDM Platform – e-mail visszaigazolás"
        msg["From"] = sender
        msg["To"] = email
        msg.set_content(
            "Kedves Kolléga!\n\n"
            f"A Klinikai TDM Platform regisztrációjához használd ezt az ellenőrző kódot: {code}\n\n"
            "Ha nem te indítottad a regisztrációt, hagyd figyelmen kívül ezt az üzenetet.\n"
        )
        try:
            context = ssl.create_default_context()
            if use_ssl:
                with smtplib.SMTP_SSL(host, port, timeout=20, context=context) as server:
                    if smtp_user:
                        server.login(smtp_user, smtp_pass)
                    server.send_message(msg)
            else:
                with smtplib.SMTP(host, port, timeout=20) as server:
                    server.ehlo()
                    if use_starttls:
                        server.starttls(context=context)
                        server.ehlo()
                    if smtp_user:
                        server.login(smtp_user, smtp_pass)
                    server.send_message(msg)
            return True, f"Visszaigazoló e-mail elküldve: {email}"
        except smtplib.SMTPAuthenticationError as e:
            return False, (
                "Az SMTP hitelesítés sikertelen. Ellenőrizd az SMTP felhasználónevet, jelszót, "
                f"STARTTLS/SSL beállítást. Fejlesztői fallback ellenőrző kód: {code}. SMTP hiba: {e}"
            )
        except Exception as e:
            return False, f"Az e-mail küldése nem sikerült ({e}). Ellenőrző kód: {code}"

    def update_user_status_ui(self):
        if self.current_user:
            if hasattr(self, "user_status_label"):
                role_txt = self.current_user.get("role", "orvos")
                self.user_status_label.setText(f"Bejelentkezve: {self.current_user.get('name','')} ({self.current_user.get('email','')}) – {role_txt}")
            if hasattr(self, "user_status_detail"):
                self.user_status_detail.setText("Hitelesített orvos felhasználó. A naplózás az e-mail címhez kötve történik.")
            self.user_edit.setText(self.current_user.get("email", ""))
            self.user_edit.setReadOnly(True)
        else:
            if hasattr(self, "user_status_label"):
                self.user_status_label.setText("Nincs bejelentkezve")
            if hasattr(self, "user_status_detail"):
                self.user_status_detail.setText("A számításhoz hitelesített orvos felhasználó szükséges.")
            self.user_edit.setText("")
            self.user_edit.setReadOnly(True)
        self.refresh_settings_tab()

    def refresh_settings_tab(self):
        if not hasattr(self, "settings_email_label"):
            return
        try:
            self.settings_email_label.setText(self.settings_email_label.text())
        except RuntimeError:
            return
        if self.current_user:
            self.settings_email_label.setText(self.current_user.get("email", "—"))
            self.settings_name_label.setText(self.current_user.get("name", "—"))
            self.settings_verified_label.setText("Igen" if self.current_user.get("verified") else "Nem")
            self.settings_role_label.setText(self.current_user.get("role", "orvos"))
            self.settings_new_name_edit.setText(self.current_user.get("name", ""))
            if self.current_user and self.current_user.get('role') == 'moderator':
                self.settings_hint.setText("A név és a jelszó itt módosítható. Moderátorként az adminisztratív beállítások is elérhetők.")
            else:
                self.settings_hint.setText("Itt a saját neved és jelszavad módosítható. Az adminisztratív beállítások csak moderátoroknak láthatók.")
            enabled = True
        else:
            self.settings_email_label.setText("—")
            self.settings_name_label.setText("—")
            self.settings_verified_label.setText("—")
            self.settings_role_label.setText("—")
            self.settings_new_name_edit.clear()
            self.settings_old_password_edit.clear()
            self.settings_new_password_edit.clear()
            self.settings_new_password2_edit.clear()
            self.settings_hint.setText("A beállítások módosításához előbb jelentkezz be.")
            enabled = False
        for w in [self.settings_new_name_edit, self.settings_save_name_btn, self.settings_old_password_edit, self.settings_new_password_edit, self.settings_new_password2_edit, self.settings_save_password_btn]:
            w.setEnabled(enabled)
        cfg = load_settings_file()
        self.smtp_settings = deepcopy(cfg)
        self.smtp_host_edit.setText(cfg.get("smtp_host", SMTP_DEFAULT_HOST))
        self.smtp_port_edit.setText(str(cfg.get("smtp_port", SMTP_DEFAULT_PORT)))
        self.smtp_user_edit.setText(cfg.get("smtp_user", SMTP_DEFAULT_USER))
        self.smtp_from_edit.setText(cfg.get("smtp_from", SMTP_DEFAULT_FROM))
        self.smtp_pass_edit.setText(cfg.get("smtp_pass", ""))
        self.smtp_starttls_combo.setCurrentText("Igen" if str(cfg.get("smtp_starttls", SMTP_DEFAULT_STARTTLS)).lower() in {"1", "true", "yes", "on"} else "Nem")
        self.smtp_ssl_combo.setCurrentText("Igen" if str(cfg.get("smtp_ssl", SMTP_DEFAULT_SSL)).lower() in {"1", "true", "yes", "on"} else "Nem")
        is_moderator = bool(self.current_user and self.current_user.get("role") == "moderator")
        moderator_widgets = [
            'make_moderator_btn', 'make_doctor_btn', 'make_infectologist_btn',
            'disable_user_btn', 'enable_user_btn', 'delete_user_btn',
            'manual_user_name_edit', 'manual_user_email_edit', 'manual_user_role_combo', 'manual_add_user_btn',
            'add_infectologist_btn', 'remove_infectologist_btn',
            'settings_users_table', 'infectologists_table',
            'infectologist_name_edit', 'infectologist_email_edit',
            'smtp_host_edit', 'smtp_port_edit', 'smtp_user_edit', 'smtp_from_edit',
            'smtp_pass_edit', 'smtp_starttls_combo', 'smtp_ssl_combo',
            'smtp_save_btn', 'smtp_test_btn'
        ]
        for name in moderator_widgets:
            w = getattr(self, name, None)
            if w is not None:
                w.setEnabled(is_moderator)
        for name in ['admin_users_box', 'manual_user_box', 'infecto_box', 'smtp_box']:
            box = getattr(self, name, None)
            if box is not None:
                box.setVisible(is_moderator)
        for box in [getattr(self, 'admin_users_box', None), getattr(self, 'infecto_box', None), getattr(self, 'smtp_box', None)]:
            if box is not None:
                box.setVisible(is_moderator)
        if hasattr(self, 'save_history_changes_btn'):
            self.save_history_changes_btn.setEnabled(bool(self.current_user))
        self.refresh_user_admin_tables()
        self.refresh_infectologist_combo()
        if hasattr(self, "send_bulk_btn"):
            self.send_bulk_btn.setVisible(bool(self.current_user and self.current_user.get("role") == "infektologus"))

    def refresh_user_admin_tables(self):
        if hasattr(self, "settings_users_table"):
            self.settings_users_table.setRowCount(0)
            users_sorted = sorted(self.users_data, key=lambda u: (u.get("name", ""), u.get("email", "")))
            for user in users_sorted:
                row = self.settings_users_table.rowCount()
                self.settings_users_table.insertRow(row)
                self.settings_users_table.setItem(row, 0, QTableWidgetItem(str(user.get("name", ""))))
                self.settings_users_table.setItem(row, 1, QTableWidgetItem(str(user.get("email", ""))))
                self.settings_users_table.setItem(row, 2, QTableWidgetItem(str(user.get("role", "orvos"))))
                self.settings_users_table.setItem(row, 3, QTableWidgetItem("Igen" if user.get("verified") else "Nem"))
                self.settings_users_table.setItem(row, 4, QTableWidgetItem("Igen" if user.get("active", True) else "Nem"))
        if hasattr(self, "infectologists_table"):
            self.infectologists_table.setRowCount(0)
            for item in sorted(self.infectologists_data, key=lambda x: (x.get("name", ""), x.get("email", ""))):
                row = self.infectologists_table.rowCount()
                self.infectologists_table.insertRow(row)
                self.infectologists_table.setItem(row, 0, QTableWidgetItem(str(item.get("name", ""))))
                self.infectologists_table.setItem(row, 1, QTableWidgetItem(str(item.get("email", ""))))

    def selected_user_email_from_settings(self) -> str:
        row = self.settings_users_table.currentRow()
        if row < 0:
            raise ValueError("Jelölj ki egy felhasználót a listában.")
        item = self.settings_users_table.item(row, 1)
        if not item:
            raise ValueError("A kijelölt felhasználó e-mail címe nem olvasható.")
        return self.normalize_email(item.text())

    def set_selected_user_role(self, role: str):
        try:
            if not self.current_user or self.current_user.get("role") != "moderator":
                raise ValueError("Ehhez moderátor jogosultság szükséges.")
            email = self.selected_user_email_from_settings()
            user = self.find_user(email)
            if not user:
                raise ValueError("A kijelölt felhasználó nem található.")
            if email == MAIN_MODERATOR_EMAIL and role != "moderator":
                raise ValueError("A fő moderátor szerepkörét nem lehet visszavonni.")
            user["role"] = role
            self.save_users()
            if self.current_user and self.normalize_email(self.current_user.get("email", "")) == email:
                self.current_user = dict(user)
            self.refresh_settings_tab()
            self.update_user_status_ui()
            QMessageBox.information(self, "Beállítások", "A szerepkör frissítve lett.")
        except Exception as e:
            QMessageBox.warning(self, "Beállítások hiba", str(e))


    def set_selected_user_active(self, active: bool):
        try:
            if not self.current_user or self.current_user.get("role") != "moderator":
                raise ValueError("Ehhez moderátor jogosultság szükséges.")
            email = self.selected_user_email_from_settings()
            user = self.find_user(email)
            if not user:
                raise ValueError("A kijelölt felhasználó nem található.")
            if email == MAIN_MODERATOR_EMAIL and not active:
                raise ValueError("A fő moderátor nem tiltható le.")
            user["active"] = bool(active)
            self.save_users()
            if self.current_user and self.normalize_email(self.current_user.get("email", "")) == email:
                self.current_user = dict(user)
            self.refresh_settings_tab()
            QMessageBox.information(self, "Beállítások", "A felhasználó állapota frissítve lett.")
        except Exception as e:
            QMessageBox.warning(self, "Beállítások hiba", str(e))

    def delete_selected_user(self):
        try:
            if not self.current_user or self.current_user.get("role") != "moderator":
                raise ValueError("Ehhez moderátor jogosultság szükséges.")
            email = self.selected_user_email_from_settings()
            if email == MAIN_MODERATOR_EMAIL:
                raise ValueError("A fő moderátor nem törölhető.")
            self.users_data = [u for u in self.users_data if self.normalize_email(u.get("email", "")) != email]
            self.save_users()
            self.refresh_settings_tab()
            QMessageBox.information(self, "Beállítások", "A felhasználó törölve lett.")
        except Exception as e:
            QMessageBox.warning(self, "Beállítások hiba", str(e))

    def send_temp_password_email(self, email: str, password: str) -> Tuple[bool, str]:
        smtp = get_smtp_settings()
        host = smtp["host"]; port = smtp["port"]; smtp_user = smtp["smtp_user"]; smtp_pass = smtp["smtp_pass"]; sender = smtp["sender"]
        use_ssl = smtp["use_ssl"]; use_starttls = smtp["use_starttls"]
        if not host or not sender or not smtp_pass:
            return False, f"SMTP nincs teljesen beállítva. Ideiglenes jelszó: {password}"
        msg = EmailMessage()
        msg["Subject"] = "Klinikai TDM Platform – felhasználó létrehozva"
        msg["From"] = sender
        msg["To"] = email
        msg.set_content(f"Kedves Kolléga!\n\nA Klinikai TDM Platformhoz létrejött a felhasználód.\nIdeiglenes jelszó: {password}\nKérlek belépés után változtasd meg.\n")
        context = ssl.create_default_context()
        if use_ssl:
            with smtplib.SMTP_SSL(host, port, timeout=20, context=context) as server:
                if smtp_user: server.login(smtp_user, smtp_pass)
                server.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=20) as server:
                server.ehlo()
                if use_starttls:
                    server.starttls(context=context); server.ehlo()
                if smtp_user: server.login(smtp_user, smtp_pass)
                server.send_message(msg)
        return True, f"Ideiglenes jelszó elküldve: {email}"

    def add_user_manually(self):
        try:
            if not self.current_user or self.current_user.get("role") != "moderator":
                raise ValueError("Ehhez moderátor jogosultság szükséges.")
            name = self.manual_user_name_edit.text().strip()
            email_raw = self.manual_user_email_edit.text().strip()
            role = self.manual_user_role_combo.currentText().strip() or "orvos"
            if not name:
                raise ValueError("Adj meg nevet.")
            email = self.validate_general_email(email_raw)
            existing = self.find_user(email)
            temp_password = generate_temp_password()
            record = existing or {}
            record.update({
                "name": name,
                "email": email,
                "username": email.split("@")[0],
                "password_hash": self.hash_password(temp_password),
                "role": ("moderator" if email == MAIN_MODERATOR_EMAIL else role),
                "verified": True,
                "active": True,
                "verification_code": "",
                "verified_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            })
            if existing is None:
                self.users_data.append(record)
            self.save_users()
            ok, msg = self.send_temp_password_email(email, temp_password)
            self.manual_user_name_edit.clear(); self.manual_user_email_edit.clear()
            self.refresh_settings_tab()
            QMessageBox.information(self, "Beállítások", msg if ok else msg)
        except Exception as e:
            QMessageBox.warning(self, "Beállítások hiba", str(e))

    def add_infectologist(self):
        try:
            if not self.current_user or self.current_user.get("role") != "moderator":
                raise ValueError("Ehhez moderátor jogosultság szükséges.")
            name = self.infectologist_name_edit.text().strip()
            email = self.validate_general_email(self.infectologist_email_edit.text())
            if not name:
                raise ValueError("Adj meg nevet.")
            existing = next((x for x in self.infectologists_data if self.normalize_email(x.get("email", "")) == email), None)
            if existing:
                existing["name"] = name
            else:
                self.infectologists_data.append({"name": name, "email": email})
            self.save_infectologists()
            self.infectologist_name_edit.clear()
            self.infectologist_email_edit.clear()
            self.refresh_user_admin_tables()
            self.refresh_infectologist_combo()
            QMessageBox.information(self, "Beállítások", "Az infektológus címzett mentve lett.")
        except Exception as e:
            QMessageBox.warning(self, "Beállítások hiba", str(e))

    def remove_selected_infectologist(self):
        try:
            if not self.current_user or self.current_user.get("role") != "moderator":
                raise ValueError("Ehhez moderátor jogosultság szükséges.")
            row = self.infectologists_table.currentRow()
            if row < 0:
                raise ValueError("Jelölj ki egy infektológust a listában.")
            email_item = self.infectologists_table.item(row, 1)
            email = self.normalize_email(email_item.text()) if email_item else ""
            self.infectologists_data = [x for x in self.infectologists_data if self.normalize_email(x.get("email", "")) != email]
            self.save_infectologists()
            self.refresh_user_admin_tables()
            self.refresh_infectologist_combo()
            QMessageBox.information(self, "Beállítások", "Az infektológus címzett törölve lett.")
        except Exception as e:
            QMessageBox.warning(self, "Beállítások hiba", str(e))

    def refresh_infectologist_combo(self):
        if not hasattr(self, "export_infectologist_combo"):
            return
        self.export_infectologist_combo.clear()
        for item in sorted(self.infectologists_data, key=lambda x: (x.get("name", ""), x.get("email", ""))):
            label = f"{item.get('name','')} <{item.get('email','')}>"
            self.export_infectologist_combo.addItem(label, item.get("email", ""))

    def save_smtp_settings(self):
        try:
            if not self.current_user or self.current_user.get("role") != "moderator":
                raise ValueError("Ehhez moderátor jogosultság szükséges.")
            settings = {
                "smtp_host": self.smtp_host_edit.text().strip(),
                "smtp_port": self.smtp_port_edit.text().strip() or SMTP_DEFAULT_PORT,
                "smtp_user": self.smtp_user_edit.text().strip(),
                "smtp_from": self.smtp_from_edit.text().strip(),
                "smtp_pass": self.smtp_pass_edit.text().strip(),
                "smtp_starttls": "1" if self.smtp_starttls_combo.currentText() == "Igen" else "0",
                "smtp_ssl": "1" if self.smtp_ssl_combo.currentText() == "Igen" else "0",
            }
            if not settings["smtp_host"] or not settings["smtp_user"] or not settings["smtp_from"]:
                raise ValueError("Az SMTP szerver, felhasználó és feladó cím kötelező.")
            int(settings["smtp_port"])
            save_settings_file(settings)
            self.smtp_settings = load_settings_file()
            QMessageBox.information(self, "Beállítások", "Az SMTP beállítások mentve lettek.")
        except Exception as e:
            QMessageBox.warning(self, "Beállítások hiba", str(e))

    def test_smtp_settings(self):
        try:
            if not self.current_user or self.current_user.get("role") != "moderator":
                raise ValueError("Ehhez moderátor jogosultság szükséges.")
            self.save_smtp_settings()
            cfg = get_smtp_settings()
            if not cfg["host"] or not cfg["smtp_pass"] or not cfg["sender"]:
                raise ValueError("Az SMTP még nincs teljesen beállítva.")
            msg = EmailMessage()
            msg["Subject"] = "Klinikai TDM Platform – SMTP teszt"
            msg["From"] = cfg["sender"]
            msg["To"] = self.current_user.get("email", cfg["sender"])
            msg.set_content("Ez egy automatikus SMTP tesztüzenet a Klinikai TDM Platformból.")
            context = ssl.create_default_context()
            if cfg["use_ssl"]:
                with smtplib.SMTP_SSL(cfg["host"], cfg["port"], timeout=20, context=context) as server:
                    if cfg["smtp_user"]:
                        server.login(cfg["smtp_user"], cfg["smtp_pass"])
                    server.send_message(msg)
            else:
                with smtplib.SMTP(cfg["host"], cfg["port"], timeout=20) as server:
                    server.ehlo()
                    if cfg["use_starttls"]:
                        server.starttls(context=context)
                        server.ehlo()
                    if cfg["smtp_user"]:
                        server.login(cfg["smtp_user"], cfg["smtp_pass"])
                    server.send_message(msg)
            QMessageBox.information(self, "SMTP teszt", "A tesztüzenet sikeresen elküldve.")
        except Exception as e:
            QMessageBox.warning(self, "SMTP teszt hiba", str(e))

    def send_report_to_infectologist(self):
        try:
            if not self.latest_report:
                raise ValueError('Előbb számolj egy eredményt.')
            if self.export_infectologist_combo.count() == 0:
                raise ValueError('Nincs beállított infektológus címzett.')
            target_email = self.export_infectologist_combo.currentData() or ''
            if not target_email:
                raise ValueError('Válassz címzettet.')
            smtp = get_smtp_settings()
            host = smtp['host']
            port = smtp['port']
            smtp_user = smtp['smtp_user']
            smtp_pass = smtp['smtp_pass']
            sender = smtp['sender']
            use_ssl = smtp['use_ssl']
            use_starttls = smtp['use_starttls']
            if not host or not sender or not smtp_pass:
                raise ValueError('SMTP nincs teljesen beállítva. A moderátor a Beállítások ablakban tudja megadni az SMTP adatokat.')

            drug = self.results.get('drug', 'ismeretlen antibiotikum')
            method = self.results.get('method', '—')
            patient_id = str(self.patient_id_edit.text()).strip() if hasattr(self, 'patient_id_edit') else ''
            patient_part = f' – {patient_id}' if patient_id else ''
            subject = f'Klinikai TDM riport – {drug} – {method}{patient_part}'
            note = self.export_mail_note.text().strip() if hasattr(self, 'export_mail_note') else ''
            sender_line = f"{self.current_user.get('name','—')} <{self.current_user.get('email','—')}>" if self.current_user else '—'

            plain_lines = [
                'Klinikai TDM riport',
                f'Küldő: {sender_line}',
                f'Antibiotikum: {drug}',
                f'Módszer: {method}',
            ]
            if patient_id:
                plain_lines.append(f'Betegazonosító: {patient_id}')
            if note:
                plain_lines.extend(['', f'Megjegyzés: {note}'])
            plain_lines.extend(['', self.latest_report])
            plain_body = '\n'.join(plain_lines)

            msg = EmailMessage()
            msg['Subject'] = subject
            msg['From'] = sender
            msg['To'] = target_email
            msg.set_content(plain_body)

            html_parts = [
                '<html><body>',
                '<h2>Klinikai TDM riport</h2>',
                f'<p><b>Küldő:</b> {html.escape(sender_line)}<br>',
                f'<b>Antibiotikum:</b> {html.escape(str(drug))}<br>',
                f'<b>Módszer:</b> {html.escape(str(method))}'
            ]
            if patient_id:
                html_parts.append(f'<br><b>Betegazonosító:</b> {html.escape(patient_id)}')
            html_parts.append('</p>')
            if note:
                html_parts.append(f'<p><b>Megjegyzés:</b> {html.escape(note)}</p>')
            html_parts.append('<p><b>Vizualizáció:</b><br><img src="cid:tdm_plot_png" style="max-width:900px; width:100%; height:auto; border:1px solid #cccccc;"></p>')
            html_parts.append(f'<pre style="white-space:pre-wrap; font-family:Consolas, monospace; font-size:12px;">{html.escape(self.latest_report)}</pre>')
            html_parts.append('</body></html>')
            msg.add_alternative(''.join(html_parts), subtype='html')

            plot_path = self._export_plot_to_png()
            if plot_path and os.path.exists(plot_path):
                with open(plot_path, 'rb') as f:
                    img_data = f.read()
                msg.get_payload()[-1].add_related(img_data, maintype='image', subtype='png', cid='<tdm_plot_png>', filename='tdm_plot.png')

            txt_name = f"tdm_riport_{str(drug).replace(' ', '_')}.txt"
            msg.add_attachment(plain_body.encode('utf-8'), maintype='text', subtype='plain', filename=txt_name)

            pdf_note = ''
            tmp_pdf = tempfile.NamedTemporaryFile(delete=False, suffix='.pdf')
            tmp_pdf.close()
            try:
                try:
                    self._render_report_pdf_to_path(tmp_pdf.name)
                    if os.path.exists(tmp_pdf.name) and os.path.getsize(tmp_pdf.name) > 0:
                        with open(tmp_pdf.name, 'rb') as f:
                            msg.add_attachment(f.read(), maintype='application', subtype='pdf', filename='tdm_riport.pdf')
                    else:
                        pdf_note = ' (PDF melléklet nélkül)'
                except Exception as pdf_err:
                    pdf_note = f' (PDF melléklet nélkül: {pdf_err})'
            finally:
                try:
                    os.remove(tmp_pdf.name)
                except Exception:
                    pass
                if plot_path:
                    try:
                        os.remove(plot_path)
                    except Exception:
                        pass

            context = ssl.create_default_context()
            if use_ssl:
                with smtplib.SMTP_SSL(host, port, timeout=20, context=context) as server:
                    if smtp_user:
                        server.login(smtp_user, smtp_pass)
                    server.send_message(msg)
            else:
                with smtplib.SMTP(host, port, timeout=20) as server:
                    server.ehlo()
                    if use_starttls:
                        server.starttls(context=context)
                        server.ehlo()
                    if smtp_user:
                        server.login(smtp_user, smtp_pass)
                    server.send_message(msg)
            self.export_status.setText(f'Riport elküldve: {target_email}')
            QMessageBox.information(self, 'Export', f'A riport elküldve ide: {target_email}\n\nTXT melléklet + beágyazott grafikon{pdf_note}.')
        except Exception as e:
            QMessageBox.warning(self, 'Export hiba', str(e))



    def send_selected_history_to_infectologist(self):
        try:
            if not self.current_user or self.current_user.get("role") not in {"moderator", "infektologus"}:
                raise ValueError("Ehhez infektológus vagy moderátor jogosultság szükséges.")
            if self.export_infectologist_combo.count() == 0:
                raise ValueError("Nincs beállított infektológus címzett.")
            target_email = self.export_infectologist_combo.currentData() or ''
            if not target_email:
                raise ValueError("Válassz címzettet.")
            selection_model = self.history_table.selectionModel()
            selected = selection_model.selectedRows() if selection_model else []
            rows = self.history_table.property("history_rows") or []
            selected_records = [rows[idx.row()] for idx in selected if 0 <= idx.row() < len(rows)]
            if not selected_records:
                raise ValueError("Jelölj ki legalább egy history sort.")
            lines = ["Klinikai TDM – kijelölt history sorok", ""]
            for rec in selected_records:
                lines.extend([
                    f"Időpont: {rec.get('timestamp','')}",
                    f"Felhasználó: {rec.get('user','')}",
                    f"Beteg: {rec.get('patient_id','')}",
                    f"Antibiotikum: {rec.get('drug','')}",
                    f"Módszer: {rec.get('method','')}",
                    f"Státusz: {rec.get('status','')}",
                    f"Javaslat: {rec.get('regimen','')}",
                    f"Döntés: {rec.get('decision','')}",
                    "-"*60,
                    rec.get('report',''),
                    "="*80,
                    ""
                ])
            text_body = "\n".join(lines)
            smtp = get_smtp_settings()
            if not smtp['host'] or not smtp['sender'] or not smtp['smtp_pass']:
                raise ValueError('SMTP nincs teljesen beállítva. A moderátor a Beállítások ablakban tudja megadni az SMTP adatokat.')
            msg = EmailMessage()
            msg['Subject'] = f'Klinikai TDM history kivonat – {len(selected_records)} sor'
            msg['From'] = smtp['sender']
            msg['To'] = target_email
            msg.set_content(text_body)
            msg.add_attachment(text_body.encode('utf-8'), maintype='text', subtype='plain', filename='tdm_history_kijelolt_sorok.txt')
            context = ssl.create_default_context()
            if smtp['use_ssl']:
                with smtplib.SMTP_SSL(smtp['host'], smtp['port'], timeout=20, context=context) as server:
                    if smtp['smtp_user']: server.login(smtp['smtp_user'], smtp['smtp_pass'])
                    server.send_message(msg)
            else:
                with smtplib.SMTP(smtp['host'], smtp['port'], timeout=20) as server:
                    server.ehlo()
                    if smtp['use_starttls']:
                        server.starttls(context=context); server.ehlo()
                    if smtp['smtp_user']: server.login(smtp['smtp_user'], smtp['smtp_pass'])
                    server.send_message(msg)
            self.export_status.setText(f"Kijelölt history sorok elküldve: {target_email}")
            QMessageBox.information(self, 'Tömeges küldés', f'{len(selected_records)} history sor elküldve: {target_email}')
        except Exception as e:
            QMessageBox.warning(self, 'Tömeges küldési hiba', str(e))

    def change_display_name(self):
        try:
            if not self.current_user:
                raise ValueError("Nincs bejelentkezett felhasználó.")
            new_name = self.settings_new_name_edit.text().strip()
            if len(new_name) < 2:
                raise ValueError("Adj meg legalább 2 karakter hosszú nevet.")
            user = self.find_user(self.current_user.get("email", ""))
            if not user:
                raise ValueError("A felhasználó nem található az adatbázisban.")
            user["name"] = new_name
            self.current_user = user
            self.save_users()
            self.update_user_status_ui()
            QMessageBox.information(self, "Beállítások", "A név sikeresen frissítve lett.")
        except Exception as e:
            QMessageBox.warning(self, "Beállítások hiba", str(e))

    def change_password(self):
        try:
            if not self.current_user:
                raise ValueError("Nincs bejelentkezett felhasználó.")
            old_password = self.settings_old_password_edit.text()
            new_password = self.settings_new_password_edit.text()
            new_password2 = self.settings_new_password2_edit.text()
            user = self.find_user(self.current_user.get("email", ""))
            if not user:
                raise ValueError("A felhasználó nem található az adatbázisban.")
            if user.get("password_hash") != self.hash_password(old_password):
                raise ValueError("A jelenlegi jelszó hibás.")
            if len(new_password) < 8:
                raise ValueError("Az új jelszó legyen legalább 8 karakter.")
            if new_password != new_password2:
                raise ValueError("Az új jelszavak nem egyeznek.")
            if self.hash_password(new_password) == user.get("password_hash"):
                raise ValueError("Az új jelszó ne egyezzen a jelenlegivel.")
            user["password_hash"] = self.hash_password(new_password)
            user["password_changed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.current_user = user
            self.save_users()
            self.settings_old_password_edit.clear()
            self.settings_new_password_edit.clear()
            self.settings_new_password2_edit.clear()
            self.refresh_settings_tab()
            QMessageBox.information(self, "Beállítások", "A jelszó sikeresen módosítva lett.")
        except Exception as e:
            QMessageBox.warning(self, "Beállítások hiba", str(e))


    def send_password_reset_email(self, email: str, temp_password: str) -> tuple[bool, str]:
        smtp = get_smtp_settings()
        host = smtp['host']
        port = smtp['port']
        smtp_user = smtp['smtp_user']
        smtp_pass = smtp['smtp_pass']
        sender = smtp['sender'] or smtp_user
        if not host or not sender or not smtp_pass:
            return False, f'Az SMTP nincs teljesen beállítva. Ideiglenes jelszó: {temp_password}'
        msg = EmailMessage()
        msg['Subject'] = 'Klinikai TDM Platform – ideiglenes jelszó'
        msg['From'] = sender
        msg['To'] = email
        msg.set_content(f"Ideiglenes jelszó kérés történt a Klinikai TDM Platformhoz.\n\nIdeiglenes jelszó: {temp_password}\n\nBelépés után a Beállításoknál javasolt azonnal új jelszót megadni.\n")
        try:
            context = ssl.create_default_context()
            if smtp['use_ssl']:
                with smtplib.SMTP_SSL(host, port, timeout=20, context=context) as server:
                    if smtp_user:
                        server.login(smtp_user, smtp_pass)
                    server.send_message(msg)
            else:
                with smtplib.SMTP(host, port, timeout=20) as server:
                    server.ehlo()
                    if smtp['use_starttls']:
                        server.starttls(context=context)
                        server.ehlo()
                    if smtp_user:
                        server.login(smtp_user, smtp_pass)
                    server.send_message(msg)
            return True, f'Az ideiglenes jelszó elküldve: {email}'
        except smtplib.SMTPAuthenticationError as e:
            return False, (
                "Az SMTP hitelesítés sikertelen. Ellenőrizd az SMTP felhasználónevet, jelszót, "
                f"STARTTLS/SSL beállítást. Fejlesztői fallback ideiglenes jelszó: {temp_password}. SMTP hiba: {e}"
            )
        except Exception as e:
            return False, f'Az e-mail küldése nem sikerült ({e}). Ideiglenes jelszó: {temp_password}'

    def request_password_reset(self):
        try:
            identifier = self.login_identifier_combo.currentText().strip() or self.verify_email_edit.text().strip()
            email = self.resolve_login_identifier(identifier) if identifier else validate_doctor_email_value(self.verify_email_edit.text())
            user = self.find_user(email)
            if not user:
                raise ValueError('Nincs ilyen regisztrált felhasználó.')
            temp_password = secrets.token_urlsafe(8)[:12]
            user['password_hash'] = hash_password_value(temp_password)
            user['password_changed_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            self.save_users()
            ok, message = self.send_password_reset_email(email, temp_password)
            QMessageBox.information(self, 'Új ideiglenes jelszó', message)
        except Exception as e:
            QMessageBox.warning(self, 'Jelszó visszaállítás hiba', str(e))

    def _login_candidates(self) -> List[str]:
        candidates = []
        for u in self.users_data:
            email = str(u.get("email", "")).strip()
            if not email:
                continue
            username = str(u.get("username", "")).strip() or email.split("@")[0]
            for value in (username, email):
                if value and value not in candidates:
                    candidates.append(value)
        return candidates

    def refresh_login_autofill(self):
        from PySide6.QtWidgets import QCompleter
        candidates = self._login_candidates()
        try:
            self.login_identifier_combo.clear()
            self.login_identifier_combo.addItems(candidates)
        except Exception:
            pass
        completer = QCompleter(candidates, self)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)
        self.login_identifier_combo.setCompleter(completer)

    def resolve_login_identifier(self, raw_value: str) -> str:
        value = (raw_value or "").strip()
        if not value:
            raise ValueError('Add meg a felhasználónevet vagy kórházi e-mail címet.')
        if '@' in value:
            return validate_doctor_email_value(value)
        matches = []
        lower_value = value.lower()
        for u in self.users_data:
            email = str(u.get('email', '')).strip()
            username = str(u.get('username', '')).strip() or (email.split('@')[0] if email else '')
            if username.lower() == lower_value:
                matches.append(email)
        if not matches:
            raise ValueError('Nincs ilyen felhasználónév. Használhatsz kórházi e-mail címet is.')
        if len(set(matches)) > 1:
            raise ValueError('Ez a felhasználónév nem egyedi. Jelentkezz be teljes e-mail címmel.')
        return validate_doctor_email_value(matches[0])

    def register_user(self):
        try:
            name = self.reg_name_edit.text().strip()
            email = self.validate_doctor_email(self.reg_email_edit.text())
            password = self.reg_password_edit.text()
            password2 = self.reg_password2_edit.text()
            if not name:
                raise ValueError("Adj meg nevet.")
            if len(password) < 8:
                raise ValueError("A jelszó legyen legalább 8 karakter.")
            if password != password2:
                raise ValueError("A két jelszó nem egyezik.")
            existing = self.find_user(email)
            if existing and existing.get("verified"):
                raise ValueError("Ez az e-mail cím már regisztrált és visszaigazolt.")
            code = secrets.token_hex(3).upper()
            record = existing or {}
            moderator_emails = {e.strip().lower() for e in os.getenv("TDM_MODERATOR_EMAILS", "").split(",") if e.strip()}
            role = "moderator" if email in moderator_emails else "orvos"
            record.update({
                "name": name,
                "email": email,
                "password_hash": self.hash_password(password),
                "role": role,
                "verified": False,
                "active": True,
                "verification_code": code,
                "verification_sent_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            })
            if existing is None:
                self.users_data.append(record)
            self.save_users()
            ok, msg = self.send_verification_email(email, code)
            if not ok:
                msg = f"{msg}\n\nA regisztráció rögzítve lett, a visszaigazolás helyben folytatható az ellenőrző kóddal."
            QMessageBox.information(self, "Regisztráció", msg)
            self.login_identifier_combo.setEditText(record.get('username', email.split('@')[0]))
            self.refresh_login_autofill()
        except Exception as e:
            QMessageBox.warning(self, "Regisztrációs hiba", str(e))

    def verify_user_dialog(self):
        email = self.normalize_email(self.reg_email_edit.text() or self.login_email_edit.text())
        if not email:
            QMessageBox.information(self, "E-mail szükséges", "Add meg a regisztrált e-mail címet.")
            return
        user = self.find_user(email)
        if not user:
            QMessageBox.warning(self, "Nincs ilyen felhasználó", "Előbb regisztrálni kell.")
            return
        code, ok = QInputDialog.getText(self, "E-mail visszaigazolás", "Írd be a kapott ellenőrző kódot:")
        if not ok:
            return
        if str(code).strip().upper() != str(user.get("verification_code", "")).strip().upper():
            QMessageBox.warning(self, "Hibás kód", "Az ellenőrző kód nem megfelelő.")
            return
        user["verified"] = True
        user["verification_code"] = ""
        user["verified_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.save_users()
        QMessageBox.information(self, "Sikeres visszaigazolás", "Az e-mail cím hitelesítve lett. Most már be tudsz jelentkezni.")

    def login_user(self):
        try:
            email = self.validate_doctor_email(self.login_email_edit.text())
            password = self.login_password_edit.text()
            user = self.find_user(email)
            if not user:
                raise ValueError("Nincs ilyen regisztrált felhasználó.")
            if not user.get("verified"):
                raise ValueError("Az e-mail cím még nincs visszaigazolva.")
            if not user.get("active", True):
                raise ValueError("Ez a felhasználó le van tiltva.")
            if user.get("password_hash") != self.hash_password(password):
                raise ValueError("Hibás jelszó.")
            self.current_user = user
            self.update_user_status_ui()
            self.refresh_history_table()
            QMessageBox.information(self, "Bejelentkezés", f"Sikeres bejelentkezés: {user.get('name','')} ({user.get('role','orvos')})")
        except Exception as e:
            QMessageBox.warning(self, "Bejelentkezési hiba", str(e))

    def logout_user(self):
        self.current_user = None
        self.login_password_edit.setText("")
        self.update_user_status_ui()
        self.refresh_history_table()

    def load_history(self) -> List[dict]:
        if not os.path.exists(HISTORY_PATH):
            return []
        try:
            with open(HISTORY_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                for user in data:
                    if isinstance(user, dict):
                        user.setdefault("active", True)
                        user.setdefault("username", str(user.get("email", "")).split("@")[0] if user.get("email") else "")
                return data
            return []
        except Exception:
            return []

    def save_history(self):
        try:
            with open(HISTORY_PATH, "w", encoding="utf-8") as f:
                json.dump(self.history_data, f, ensure_ascii=False, indent=2, default=str)
        except Exception:
            pass

    def refresh_history_filter(self):
        if not hasattr(self, "history_user_filter"):
            return
        current = self.history_user_filter.currentText() if self.history_user_filter.count() else "Összes"
        users = sorted({str(r.get("user", "")).strip() for r in self.history_data if str(r.get("user", "")).strip()})
        self.history_user_filter.blockSignals(True)
        self.history_user_filter.clear()
        self.history_user_filter.addItem("Összes")
        if self.current_user:
            self.history_user_filter.addItem("Saját")
        self.history_user_filter.addItems(users)
        idx = self.history_user_filter.findText(current)
        self.history_user_filter.setCurrentIndex(max(0, idx))
        self.history_user_filter.blockSignals(False)

    def refresh_history_table(self):
        if not hasattr(self, "history_table"):
            return
        selected_user = self.history_user_filter.currentText() if self.history_user_filter.count() else "Összes"
        rows = self.history_data
        if selected_user == "Saját" and self.current_user:
            rows = [r for r in rows if str(r.get("user", "")).strip() == self.current_user.get("email", "")]
        elif selected_user and selected_user != "Összes":
            rows = [r for r in rows if str(r.get("user", "")).strip() == selected_user]
        rows = sorted(rows, key=lambda x: str(x.get("timestamp", "")), reverse=True)
        self.history_table.setRowCount(len(rows))
        self.history_table.setProperty("history_rows", rows)
        for i, row in enumerate(rows):
            vals = [
                row.get("timestamp", ""), row.get("user", ""), row.get("patient_id", ""), row.get("drug", ""),
                row.get("method", ""), row.get("status", ""), row.get("regimen", ""), row.get("decision", "")
            ]
            for j, val in enumerate(vals):
                self.history_table.setItem(i, j, QTableWidgetItem(str(val)))
        if rows:
            self.history_table.selectRow(0)
        else:
            self.history_detail.setHtml("<p>Még nincs naplózott számítás.</p>")

    def show_history_detail(self):
        rows = self.history_table.property("history_rows") or []
        idx = self.history_table.currentRow()
        if idx < 0 or idx >= len(rows):
            return
        rec = rows[idx]
        report_html = "<br>".join(str(rec.get("report", "")).splitlines())
        input_html = "<br>".join(f"<b>{k}</b>: {v}" for k, v in (rec.get("inputs") or {}).items())
        self.history_detail.setHtml(
            f"<h3>{rec.get('drug','')} – {rec.get('method','')}</h3>"
            f"<p><b>Időpont:</b> {rec.get('timestamp','')}<br>"
            f"<b>Felhasználó:</b> {rec.get('user','—')}<br>"
            f"<b>Beteg:</b> {rec.get('patient_id','—')}<br>"
            f"<b>Döntés:</b> {rec.get('decision','—')}</p>"
            f"<h4>Riport</h4><p>{report_html}</p>"
            f"<h4>Rögzített input</h4><p>{input_html}</p>"
        )

    def append_history_record(self, pk: dict, res: dict):
        record = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "user": pk.get("user", ""),
            "patient_id": pk.get("patient_id", ""),
            "drug": res.get("drug", ""),
            "method": res.get("method", ""),
            "status": res.get("status", ""),
            "regimen": res.get("regimen", ""),
            "decision": pk.get("decision", ""),
            "report": res.get("report", ""),
            "inputs": {
                "nem": pk.get("sex"), "életkor": pk.get("age"), "testsúly": pk.get("weight"), "magasság": pk.get("height"),
                "kreatinin_µmol/L": pk.get("scr_umol"), "MIC": pk.get("mic"), "adag_mg": pk.get("dose"),
                "intervallum_h": pk.get("tau"), "infúzió_h": pk.get("tinf"), "T1": pk.get("t1"), "C1": pk.get("c1"),
                "T2": pk.get("t2"), "C2": pk.get("c2"), "T3": pk.get("t3"), "C3": pk.get("c3"),
                "ICU": pk.get("icu"), "hematológia": pk.get("hematology"), "instabil_vese": pk.get("unstable_renal"),
                "obesitas": pk.get("obesity"), "neutropenia": pk.get("neutropenia"),
            },
        }
        self.history_data.append(record)
        self.save_history()
        self.refresh_history_filter()
        self.refresh_history_table()

    def reload_history(self):
        self.history_data = self.load_history()
        self.refresh_history_filter()
        self.refresh_history_table()

    def load_selected_history_into_form(self):
        rows = self.history_table.property("history_rows") or []
        selection_model = self.history_table.selectionModel()
        idx = -1
        if selection_model is not None:
            selected = selection_model.selectedRows()
            if selected:
                idx = selected[0].row()
        if idx < 0:
            idx = self.history_table.currentRow()
        if idx < 0 or idx >= len(rows):
            QMessageBox.information(self, "Nincs kijelölés", "Válassz ki egy korábbi sort.")
            return
        rec = rows[idx]
        inp = rec.get("inputs") or {}
        if not self.current_user:
            self.user_edit.setText(str(rec.get("user", "")))
        self.patient_edit.setText(str(rec.get("patient_id", "")))
        drug = str(rec.get("drug", "Vancomycin") or "Vancomycin")
        self.antibiotic_combo.setCurrentText(drug)
        self.on_antibiotic_change()
        method = str(rec.get("method", "") or "")
        if self.method_combo.findText(method) >= 0:
            self.method_combo.setCurrentText(method)
        if inp.get("nem"):
            self.sex_combo.setCurrentText(str(inp.get("nem")))
        for widget, key in [
            (self.age_edit, "életkor"), (self.weight_edit, "testsúly"), (self.height_edit, "magasság"),
            (self.scr_edit, "kreatinin_µmol/L"), (self.mic_edit, "MIC"), (self.dose_edit, "adag_mg"),
            (self.tau_edit, "intervallum_h"), (self.tinf_edit, "infúzió_h"), (self.t1_edit, "T1"),
            (self.level1_rel_edit, "C1"), (self.t2_edit, "T2"), (self.level2_rel_edit, "C2"),
            (self.t3_edit, "T3"), (self.level3_edit, "C3")
        ]:
            val = inp.get(key)
            widget.setText("" if val in [None, "None"] else str(val))
        self.icu_check.setChecked(bool(inp.get("ICU")))
        self.hematology_check.setChecked(bool(inp.get("hematológia")))
        self.unstable_renal_check.setChecked(bool(inp.get("instabil_vese")))
        self.obesity_check.setChecked(bool(inp.get("obesitas")))
        self.neutropenia_check.setChecked(bool(inp.get("neutropenia")))
        self.decision_edit.setPlainText(str(rec.get("decision", "")))
        self.tabs.setCurrentWidget(self.input_tab)


    def update_selected_history_from_form(self):
        try:
            rows = self.history_table.property('history_rows') or []
            idx = self.history_table.currentRow()
            if idx < 0 or idx >= len(rows):
                raise ValueError('Válassz ki egy módosítandó sort.')
            rec = rows[idx]
            rec_user = str(rec.get('user', '')).strip().lower()
            cur_user = str((self.current_user or {}).get('email', '')).strip().lower()
            is_moderator = bool(self.current_user and self.current_user.get('role') == 'moderator')
            if not self.current_user:
                raise ValueError('Előbb jelentkezz be.')
            if not is_moderator and rec_user != cur_user:
                raise ValueError('Csak a saját bejegyzésedet módosíthatod.')
            pk = self.collect_common()
            rec['patient_id'] = pk.get('patient_id', '')
            rec['decision'] = pk.get('decision', '')
            rec['user'] = cur_user or rec_user
            rec['inputs'] = {
                'nem': pk.get('sex'), 'életkor': pk.get('age'), 'testsúly': pk.get('weight'), 'magasság': pk.get('height'),
                'kreatinin_µmol/L': pk.get('scr_umol'), 'MIC': pk.get('mic'), 'adag_mg': pk.get('dose'),
                'intervallum_h': pk.get('tau'), 'infúzió_h': pk.get('tinf'), 'T1': pk.get('t1'), 'C1': pk.get('c1'),
                'T2': pk.get('t2'), 'C2': pk.get('c2'), 'T3': pk.get('t3'), 'C3': pk.get('c3'),
                'ICU': pk.get('icu'), 'hematológia': pk.get('hematology'), 'instabil_vese': pk.get('unstable_renal'),
                'obesitas': pk.get('obesity'), 'neutropenia': pk.get('neutropenia'),
            }
            if self.latest_report and self.results:
                rec['drug'] = self.results.get('drug', rec.get('drug', ''))
                rec['method'] = self.results.get('method', rec.get('method', ''))
                rec['status'] = self.results.get('status', rec.get('status', ''))
                rec['regimen'] = self.results.get('regimen', rec.get('regimen', ''))
                rec['report'] = self.results.get('report', rec.get('report', ''))
            self.save_history()
            self.refresh_history_filter()
            self.refresh_history_table()
            QMessageBox.information(self, 'Előző mérések', 'A kijelölt bejegyzés frissítve lett.')
        except Exception as e:
            QMessageBox.warning(self, 'Mentési hiba', str(e))

    def delete_selected_history(self):
        if not self.current_user or self.current_user.get("role") != "moderator":
            QMessageBox.warning(self, "Jogosultság hiányzik", "A törléshez moderátor felhasználó szükséges.")
            return
        rows = self.history_table.property("history_rows") or []
        selection_model = self.history_table.selectionModel()
        if selection_model is None:
            QMessageBox.information(self, "Nincs kijelölés", "Válassz ki legalább egy törlendő sort.")
            return
        selected_indexes = selection_model.selectedRows()
        selected_row_indexes = sorted({idx.row() for idx in selected_indexes})
        if not selected_row_indexes:
            current_idx = self.history_table.currentRow()
            if current_idx >= 0:
                selected_row_indexes = [current_idx]
        if not selected_row_indexes:
            QMessageBox.information(self, "Nincs kijelölés", "Válassz ki legalább egy törlendő sort.")
            return

        selected_records = [rows[i] for i in selected_row_indexes if 0 <= i < len(rows)]
        if not selected_records:
            QMessageBox.information(self, "Nincs kijelölés", "A kijelölt sorok nem találhatók a naplóban.")
            return

        if len(selected_records) == 1:
            msg = f"Biztosan törlöd ezt a naplóbejegyzést?\n\n{selected_records[0].get('timestamp','')} | {selected_records[0].get('drug','')} | {selected_records[0].get('patient_id','—')}"
        else:
            msg = f"Biztosan törlöd a kijelölt {len(selected_records)} naplóbejegyzést?"

        reply = QMessageBox.question(
            self,
            "Mérések törlése",
            msg,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        before = len(self.history_data)
        to_remove = {id(rec) for rec in selected_records}
        self.history_data = [rec for rec in self.history_data if id(rec) not in to_remove]

        # Fallback tartalmi egyezés alapján, ha a rekordok újra lettek példányosítva
        if len(self.history_data) == before:
            keys = {(rec.get("timestamp"), rec.get("user_email"), rec.get("drug"), rec.get("method"), rec.get("patient_id"), rec.get("decision")) for rec in selected_records}
            self.history_data = [
                rec for rec in self.history_data
                if (rec.get("timestamp"), rec.get("user_email"), rec.get("drug"), rec.get("method"), rec.get("patient_id"), rec.get("decision")) not in keys
            ]

        removed = before - len(self.history_data)
        self.save_history()
        self.refresh_history_filter()
        self.refresh_history_table()
        self.history_detail.setHtml(f"<p>{removed} bejegyzés törölve lett.</p>")

    def switch_module(self):
        module_name = self.module_combo.currentText() if hasattr(self, "module_combo") else "TDM"
        if module_name == "Statisztika":
            self.module_stack.setCurrentWidget(self.stats_module)
            self.header_title.setText("Statisztikai modul")
            self.header_subtitle.setText("Jövőbeli statisztikai és surveillance workflow-k helye. A modul jelenleg vázként érhető el.")
        else:
            self.module_stack.setCurrentWidget(self.tdm_widget)
            self.header_title.setText("Klinikai TDM platform")
            self.header_subtitle.setText("Vancomycin, linezolid és amikacin modulok magyar felülettel, guide/evidence/empirikus támogatással. Lokális validáció szükséges.")

    def palette(self):
        name = self.theme_combo.currentText() if hasattr(self, "theme_combo") else "Light Clinical"
        palettes = {
            "Midnight Blue": {"bg": "#0b1020", "panel": "#111827", "panel2": "#0f172a", "border": "#23304f", "accent": "#1d4ed8", "accent2": "#93c5fd", "text": "#e5e7eb", "muted": "#cbd5e1", "header_to": "#1d4ed8", "header_text": "#ffffff", "toolbox_text": "#e2e8f0"},
            "Light Clinical": {"bg": "#f3f7fb", "panel": "#ffffff", "panel2": "#eef4fb", "border": "#cbd5e1", "accent": "#2563eb", "accent2": "#0f172a", "text": "#0f172a", "muted": "#334155", "header_to": "#93c5fd", "header_text": "#0f172a", "toolbox_text": "#1e293b"},
            "Emerald Dark": {"bg": "#061311", "panel": "#0b1f1b", "panel2": "#0f2a24", "border": "#1f4d45", "accent": "#10b981", "accent2": "#a7f3d0", "text": "#ecfdf5", "muted": "#bbf7d0", "header_to": "#059669", "header_text": "#ffffff", "toolbox_text": "#d1fae5"},
            "Graphite": {"bg": "#111111", "panel": "#1a1a1a", "panel2": "#202020", "border": "#3a3a3a", "accent": "#6b7280", "accent2": "#f3f4f6", "text": "#f3f4f6", "muted": "#d1d5db", "header_to": "#4b5563", "header_text": "#ffffff", "toolbox_text": "#f3f4f6"},
        }
        return palettes.get(name, palettes["Light Clinical"])

    def apply_theme(self):
        p = self.palette()
        self.setStyleSheet(f"""
            QMainWindow, QWidget {{ background: {p['bg']}; color: {p['text']}; font-family: 'Segoe UI', Arial, sans-serif; font-size: 13px; }}
            QMenuBar, QMenu {{ background: {p['panel']}; color: {p['text']}; }}
            #ThemeBar, #ActionBar, #HintBox {{ background: {p['panel']}; border: 1px solid {p['border']}; border-radius: 16px; }}
            #Header {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {p['panel']}, stop:1 {p['header_to']}); border: 1px solid {p['border']}; border-radius: 18px; }}
            #HeaderTitle {{ font-size: 24px; font-weight: 800; color: {p['header_text']}; }}
            #HeaderSubtitle {{ color: {p['muted']}; }}
            QTabWidget::pane {{ border: 1px solid {p['border']}; background: {p['panel2']}; border-radius: 16px; }}
            QTabBar::tab {{ background: {p['panel']}; color: {p['muted']}; padding: 10px 18px; border-top-left-radius: 10px; border-top-right-radius: 10px; margin-right: 4px; }}
            QTabBar::tab:selected {{ background: {p['accent']}; color: white; }}
            QGroupBox {{ border: 1px solid {p['border']}; border-radius: 16px; margin-top: 10px; padding-top: 14px; background: {p['panel']}; font-weight: 600; }}
            QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 6px; color: {p['accent2']}; }}
            QLineEdit, QComboBox, QDateTimeEdit, QPlainTextEdit, QTextBrowser {{ background: {p['panel2']}; border: 1px solid {p['border']}; border-radius: 10px; padding: 8px 10px; color: {p['text']}; selection-background-color: {p['accent']}; }}
            QPushButton {{ background: {p['panel']}; border: 1px solid {p['border']}; border-radius: 12px; padding: 10px 14px; color: {p['text']}; font-weight: 600; }}
            QPushButton:hover {{ background: {p['panel2']}; }}
            #PrimaryButton {{ background: {p['accent']}; border: 1px solid {p['accent']}; color: white; }}
            #SectionTitle {{ font-size: 18px; font-weight: 700; color: {p['text']}; }}
            #StatCard {{ background: {p['panel']}; border: 1px solid {p['border']}; border-radius: 18px; }}
            #CardTitle {{ color: {p['accent2']}; font-size: 12px; font-weight: 600; }}
            #CardValue {{ color: {p['text']}; font-size: 24px; font-weight: 800; }}
            #CardSubtitle {{ color: {p['muted']}; font-size: 12px; }}
            a {{ color: {p['accent']}; }}
        """)
        self.refresh_context_panels()

    def methods_for_antibiotic(self, abx: str) -> List[str]:
        return {
            "Vancomycin": ["Klasszikus", "Bayesian", "ICU / Haladó"],
            "Linezolid": ["Gyors TDM", "Bayesian (általános)", "Bayesian (hematológia)"],
            "Amikacin": ["Extended-interval Bayesian", "Konvencionális Bayesian"],
        }[abx]

    def on_antibiotic_change(self):
        abx = self.antibiotic_combo.currentText()
        current = self.method_combo.currentText()
        self.method_combo.blockSignals(True)
        self.method_combo.clear()
        self.method_combo.addItems(self.methods_for_antibiotic(abx))
        if current in self.methods_for_antibiotic(abx):
            self.method_combo.setCurrentText(current)
        elif self.method_combo.count():
            self.method_combo.setCurrentIndex(0)
        self.method_combo.blockSignals(False)
        is_vanco = abx == "Vancomycin"
        self.mode_frame.setVisible(is_vanco)
        self.sample_mode_combo.setEnabled(is_vanco)
        if not is_vanco:
            self.sample_mode_combo.setCurrentIndex(1)
        self.update_sampling_visibility()
        self.refresh_context_panels()

    def update_sampling_visibility(self):
        is_vanco = self.antibiotic_combo.currentText() == "Vancomycin"
        clinical = is_vanco and self.sample_mode_combo.currentIndex() == 0
        self.clinical_box.setVisible(clinical)
        self.relative_box.setVisible(not clinical)

    def reset_defaults(self):
        if self.current_user:
            self.user_edit.setText(self.current_user.get("email", ""))
        else:
            self.user_edit.setText("")
        self.patient_edit.setText("")
        self.decision_edit.setPlainText("")
        self.sex_combo.setCurrentText("férfi")
        self.antibiotic_combo.setCurrentText("Vancomycin")
        self.on_antibiotic_change()
        if self.method_combo.findText("Klasszikus") >= 0:
            self.method_combo.setCurrentText("Klasszikus")
        self.sample_mode_combo.setCurrentIndex(0)
        self.age_edit.setText("55")
        self.height_edit.setText("175")
        self.weight_edit.setText("80")
        self.scr_edit.setText("88")
        self.mic_edit.setText("")
        self.dose_edit.setText("1000")
        self.tau_edit.setText("12")
        self.tinf_edit.setText("1")
        self.target_auc_edit.setText("500")
        self.rounding_edit.setText("250")
        self.level1_clin_edit.setText("23,5")
        self.level2_clin_edit.setText("8,0")
        self.level1_rel_edit.setText("23,5")
        self.level2_rel_edit.setText("8,0")
        self.level3_edit.setText("")
        self.t1_edit.setText("2")
        self.t2_edit.setText("11")
        self.t3_edit.setText("")
        self.last_infusion_dt.setDateTime(QDateTime(2026, 3, 22, 8, 0, 0))
        self.sample1_dt.setDateTime(QDateTime(2026, 3, 22, 10, 0, 0))
        self.sample2_dt.setDateTime(QDateTime(2026, 3, 22, 19, 0, 0))
        self.icu_check.setChecked(False)
        self.hematology_check.setChecked(False)
        self.unstable_renal_check.setChecked(False)
        self.obesity_check.setChecked(False)
        self.neutropenia_check.setChecked(False)
        self.empirical_mode_combo.setCurrentIndex(0)
        self.results = {}
        self.latest_report = ""
        self.result_text.setPlainText("")
        self.export_status.setText("Még nincs mentett riport.")
        for card in [self.card_primary, self.card_secondary, self.card_regimen, self.card_status]:
            card.update_card("—", "")
        self.refresh_context_panels()
        self.tabs.setCurrentWidget(self.input_tab)

    @staticmethod
    def cockcroft_gault(age: float, sex: str, weight_kg: float, scr_mg_dl: float) -> float:
        crcl = ((140.0 - age) * weight_kg) / (72.0 * scr_mg_dl)
        if sex == "nő":
            crcl *= 0.85
        return crcl

    @staticmethod
    def posterior_blend(prior: float, observed: float, weight_obs: float = 0.60) -> float:
        return prior * (1.0 - weight_obs) + observed * weight_obs

    @staticmethod
    def practical_intervals_by_crcl(crcl: float):
        if crcl >= 90:
            return [8, 12]
        if crcl >= 60:
            return [12]
        if crcl >= 40:
            return [12, 24]
        if crcl >= 20:
            return [24, 36, 48]
        return [48]

    @staticmethod
    def infusion_time_from_dose_hours(dose_mg: float) -> float:
        if dose_mg <= 1000:
            return 1.0
        if dose_mg <= 1500:
            return 1.5
        if dose_mg <= 2000:
            return 2.0
        return 2.5

    @staticmethod
    def calc_auc_trapezoid(dose_mg, tau_h, tinf_h, c1, t1_start_h, c2, t2_start_h):
        ke = math.log(c1 / c2) / (t2_start_h - t1_start_h)
        true_peak = c1 * math.exp(ke * (t1_start_h - tinf_h))
        true_trough = c2 * math.exp(-ke * (tau_h - t2_start_h))
        auc_inf = tinf_h * (true_trough + true_peak) / 2.0
        auc_elim = (true_peak - true_trough) / ke
        auc_tau = auc_inf + auc_elim
        auc24 = auc_tau * (24.0 / tau_h)
        daily_dose = dose_mg * (24.0 / tau_h)
        cl_l_h = daily_dose / auc24
        vd_l = cl_l_h / ke
        half_life = math.log(2) / ke
        return {"ke": ke, "true_peak": true_peak, "true_trough": true_trough, "auc_inf": auc_inf, "auc_elim": auc_elim, "auc_tau": auc_tau, "auc24": auc24, "daily_dose": daily_dose, "cl_l_h": cl_l_h, "vd_l": vd_l, "half_life": half_life}

    @staticmethod
    def predict_regimen(vd_l: float, cl_l_h: float, dose_mg: float, tau_h: float, tinf_h: float):
        ke = cl_l_h / vd_l
        r0 = dose_mg / tinf_h
        peak_ss = (r0 / cl_l_h) * (1.0 - math.exp(-ke * tinf_h)) / (1.0 - math.exp(-ke * tau_h))
        trough_ss = peak_ss * math.exp(-ke * (tau_h - tinf_h))
        auc24 = dose_mg * (24.0 / tau_h) / cl_l_h
        return {"peak_ss": peak_ss, "trough_ss": trough_ss, "auc24": auc24, "ke": ke}

    def suggest_regimen(self, cl_l_h: float, vd_l: float, target_auc: float, crcl: float, rounding_mg: float):
        daily_needed = cl_l_h * target_auc
        low_daily = cl_l_h * TARGET_AUC_LOW
        high_daily = cl_l_h * TARGET_AUC_HIGH
        interval_options = self.practical_intervals_by_crcl(crcl)
        candidates = []
        for tau in interval_options:
            raw_dose = daily_needed * (tau / 24.0)
            rounded_dose = max(rounding_mg, round(raw_dose / rounding_mg) * rounding_mg)
            tinf = self.infusion_time_from_dose_hours(rounded_dose)
            pred = self.predict_regimen(vd_l, cl_l_h, rounded_dose, tau, tinf)
            trough_penalty = 0.0
            if pred["trough_ss"] < TARGET_TROUGH_LOW:
                trough_penalty = (TARGET_TROUGH_LOW - pred["trough_ss"]) * 8.0
            elif pred["trough_ss"] > TARGET_TROUGH_HIGH:
                trough_penalty = (pred["trough_ss"] - TARGET_TROUGH_HIGH) * 8.0
            peak_penalty = max(0.0, pred["peak_ss"] - 40.0) * 3.0
            auc_gap = abs(pred["auc24"] - target_auc)
            score = auc_gap + trough_penalty + peak_penalty
            candidates.append({
                "dose": rounded_dose, "tau": tau, "tinf": tinf,
                "auc24": pred["auc24"], "peak": pred["peak_ss"], "trough": pred["trough_ss"],
                "score": score,
            })
        candidates.sort(key=lambda x: x["score"])
        return {"daily_needed": daily_needed, "daily_low": low_daily, "daily_high": high_daily, "interval_options": interval_options, "candidates": candidates, "best": candidates[0]}

    @staticmethod
    def predict_one_compartment(dose_mg: float, tau_h: float, tinf_h: float, cl_l_h: float, vd_l: float) -> dict:
        ke = cl_l_h / vd_l
        tinf_h = max(tinf_h, 0.5)
        r0 = dose_mg / tinf_h
        peak = (r0 / cl_l_h) * (1.0 - math.exp(-ke * tinf_h)) / (1.0 - math.exp(-ke * tau_h))
        trough = peak * math.exp(-ke * (tau_h - tinf_h))
        auc24 = dose_mg * (24.0 / tau_h) / cl_l_h
        return {"peak": peak, "trough": trough, "auc24": auc24, "ke": ke, "half_life": math.log(2)/ke}

    def collect_common(self) -> dict:
        sex = self.sex_combo.currentText()
        age = parse_float(self.age_edit.text())
        weight = parse_float(self.weight_edit.text())
        height = parse_float(self.height_edit.text())
        scr_umol = parse_float(self.scr_edit.text())
        scr_mg_dl = scr_umol / UMOL_PER_MGDL_CREATININE
        crcl = self.cockcroft_gault(age, sex, weight, scr_mg_dl)
        mic = parse_float(self.mic_edit.text(), optional=True)
        dose = parse_float(self.dose_edit.text())
        tau = parse_float(self.tau_edit.text())
        tinf = parse_float(self.tinf_edit.text())
        target_auc = parse_float(self.target_auc_edit.text(), optional=True) or 500.0
        rounding = parse_float(self.rounding_edit.text(), optional=True) or 250.0

        if self.antibiotic_combo.currentText() == "Vancomycin" and self.sample_mode_combo.currentIndex() == 0:
            last_start = self.last_infusion_dt.dateTime().toPython()
            s1 = self.sample1_dt.dateTime().toPython()
            s2 = self.sample2_dt.dateTime().toPython()
            t1 = (s1 - last_start).total_seconds() / 3600.0
            t2 = (s2 - last_start).total_seconds() / 3600.0
            c1 = parse_float(self.level1_clin_edit.text())
            c2 = parse_float(self.level2_clin_edit.text())
            c3 = None
            t3 = None
            sample_mode = "clinical"
        else:
            c1 = parse_float(self.level1_rel_edit.text())
            t1 = parse_float(self.t1_edit.text())
            c2 = parse_float(self.level2_rel_edit.text())
            t2 = parse_float(self.t2_edit.text())
            c3 = parse_float(self.level3_edit.text(), optional=True)
            t3 = parse_float(self.t3_edit.text(), optional=True)
            sample_mode = "relative"

        if not self.current_user:
            raise ValueError("Számítás előtt jelentkezz be hitelesített orvos felhasználóval.")

        return {
            "user": self.current_user.get("email", ""), "patient_id": self.patient_edit.text().strip(),
            "decision": self.decision_edit.toPlainText().strip(),
            "sex": sex, "age": age, "weight": weight, "height": height,
            "scr_umol": scr_umol, "scr_mg_dl": scr_mg_dl, "crcl": crcl,
            "mic": mic, "dose": dose, "tau": tau, "tinf": tinf,
            "target_auc": target_auc, "rounding": rounding,
            "c1": c1, "c2": c2, "c3": c3,
            "t1": t1, "t2": t2, "t3": t3,
            "icu": self.icu_check.isChecked(), "hematology": self.hematology_check.isChecked(),
            "unstable_renal": self.unstable_renal_check.isChecked(), "obesity": self.obesity_check.isChecked(),
            "neutropenia": self.neutropenia_check.isChecked(), "sample_mode": sample_mode,
        }

    @staticmethod
    def validate_two_point(pk: dict):
        if pk["c1"] is None or pk["c2"] is None or pk["t1"] is None or pk["t2"] is None:
            raise ValueError("Ehhez a módhoz legalább két koncentráció és két időpont kell.")
        if pk["t2"] <= pk["t1"]:
            raise ValueError("A 2. mintavételnek később kell lennie, mint az 1.-nek.")
        if pk["c1"] <= 0 or pk["c2"] <= 0:
            raise ValueError("A koncentrációknak pozitívnak kell lenniük.")
        if pk["c1"] <= pk["c2"]:
            raise ValueError("Az 1. szintnek magasabbnak kell lennie, mint a 2. szintnek.")

    def calc_vancomycin(self, pk: dict, method: str) -> dict:
        self.validate_two_point(pk)
        if pk["t1"] <= pk["tinf"]:
            raise ValueError("Vancomycinnél az 1. minta az infúzió vége után legyen.")
        if pk["t2"] >= pk["tau"]:
            raise ValueError("Vancomycinnél a 2. minta a következő dózis előtt legyen (T2 < τ).")

        base = self.calc_auc_trapezoid(pk["dose"], pk["tau"], pk["tinf"], pk["c1"], pk["t1"], pk["c2"], pk["t2"])
        auc_mic_base = None if pk["mic"] is None else base["auc24"] / pk["mic"]

        if method == "Klasszikus":
            model_label = "Klasszikus steady-state, kétpontos, trapezoidális becslés"
            cl_used = base["cl_l_h"]
            vd_used = base["vd_l"]
            pred = {
                "peak": base["true_peak"],
                "trough": base["true_trough"],
                "auc24": base["auc24"],
                "half_life": base["half_life"],
                "ke": base["ke"],
            }
        else:
            vd_prior = pk["weight"] * (0.7 if method == "Bayesian" else 0.9)
            if pk["obesity"]:
                vd_prior *= 1.15
            if pk["icu"]:
                vd_prior *= 1.10
            if pk["unstable_renal"]:
                vd_prior *= 1.08
            ke_obs = math.log(pk["c1"] / pk["c2"]) / (pk["t2"] - pk["t1"])
            cl_prior = max(1.0, pk["crcl"] * 0.06)
            cl_obs = max(0.5, ke_obs * vd_prior)
            obs_weight = 0.65 if method == "Bayesian" else 0.50
            cl_used = self.posterior_blend(cl_prior, cl_obs, obs_weight)
            vd_used = self.posterior_blend(vd_prior, cl_obs / ke_obs, 0.40)
            pred = self.predict_one_compartment(pk["dose"], pk["tau"], pk["tinf"], cl_used, vd_used)
            pred["ke"] = cl_used / vd_used
            model_label = "Bayesian prior + megfigyelés posterior blend" if method == "Bayesian" else "ICU/haladó prior + megfigyelés posterior blend"

        auc_mic = None if pk["mic"] is None else pred["auc24"] / pk["mic"]
        suggestion = self.suggest_regimen(cl_used, vd_used, pk["target_auc"], pk["crcl"], pk["rounding"])
        best = suggestion["best"]
        status = "Célzónában" if TARGET_AUC_LOW <= pred["auc24"] <= TARGET_AUC_HIGH else ("Alulexpozíció" if pred["auc24"] < TARGET_AUC_LOW else "Túlexpozíció")
        status_sub = (
            "AUC24 a cél alatt" if pred["auc24"] < TARGET_AUC_LOW else
            "AUC24 a cél felett" if pred["auc24"] > TARGET_AUC_HIGH else
            "AUC24 400–600 mg·h/L"
        )

        assessment = []
        if status == "Célzónában":
            assessment.append("A jelenlegi expozíció a 400–600 mg·h/L célzónában van.")
        elif status == "Alulexpozíció":
            assessment.append("Valószínű alulexpozíció: emelés vagy rövidebb intervallum mérlegelendő.")
        else:
            assessment.append("Valószínű túlexpozíció: nephrotoxicitási kockázat nőhet, dóziscsökkentés vagy hosszabb intervallum mérlegelendő.")
        if pk["crcl"] < 50:
            assessment.append("Csökkent vesefunkció: az intervallum megnyújtása gyakran szükséges.")
        if method == "ICU / Haladó":
            assessment.append("ICU/haladó módban az eredményt napi klinikai újraértékeléssel és ismételt TDM-mel kell értelmezni.")

        lines = [
            f"VANCOMYCIN – {method}",
            f"Modell: {model_label}",
            f"Mintavételi mód: {'klinikai dátum-idő' if pk['sample_mode']=='clinical' else 'relatív órák'}",
            "",
            "Beteg és séma",
            f"- Nem: {pk['sex']} | Életkor: {pk['age']:.0f} év | Testsúly: {pk['weight']:.1f} kg | Magasság: {pk['height']:.1f} cm",
            f"- SCr: {pk['scr_umol']:.1f} µmol/L ({pk['scr_mg_dl']:.2f} mg/dL) | Cockcroft–Gault CrCl: {pk['crcl']:.1f} mL/perc",
            f"- Dózis: {pk['dose']:.0f} mg q{pk['tau']:.0f}h | infúzió: {pk['tinf']:.2f} h",
            "",
            "Mintavétel",
            f"- 1. minta: T1 = {pk['t1']:.2f} h | C1 = {pk['c1']:.2f} mg/L",
            f"- 2. minta: T2 = {pk['t2']:.2f} h | C2 = {pk['c2']:.2f} mg/L",
            "",
            "PK eredmények",
            f"- ke: {pred['ke']:.4f} 1/h | felezési idő: {pred['half_life']:.2f} h",
            f"- Clearance: {cl_used:.2f} L/h | Vd: {vd_used:.2f} L",
            f"- Peak: {pred['peak']:.2f} mg/L | trough: {pred['trough']:.2f} mg/L",
            f"- AUC24: {pred['auc24']:.2f} mg·h/L",
            f"- AUC24/MIC: {'nincs számolva' if auc_mic is None else f'{auc_mic:.2f}'}",
            "",
            "Értelmezés",
            f"- Státusz: {status}",
        ]
        lines.extend([f"- {x}" for x in assessment])
        lines.extend([
            "",
            "Ajánlott új séma",
            f"- Elsődleges javaslat: {best['dose']:.0f} mg q{best['tau']:.0f}h",
            f"- Prediktált AUC24: {best['auc24']:.1f} mg·h/L | peak: {best['peak']:.1f} mg/L | trough: {best['trough']:.1f} mg/L",
        ])
        if suggestion.get("candidates"):
            lines.append("- További jelöltek:")
            for i, cand in enumerate(suggestion["candidates"][:3], 1):
                lines.append(f"  {i}. {cand['dose']:.0f} mg q{cand['tau']:.0f}h | AUC24 {cand['auc24']:.1f} | trough {cand['trough']:.1f}")

        plot = self._plot_series_vanco(pk, {"true_peak": pred["peak"], "true_trough": pred["trough"]}, best)
        return {
            "drug": "Vancomycin",
            "method": method,
            "status": status,
            "primary": f"AUC24 {pred['auc24']:.1f}",
            "secondary": f"CL {cl_used:.2f} L/h",
            "regimen": f"{best['dose']:.0f} mg q{best['tau']:.0f}h",
            "status_sub": status_sub,
            "report": "\n".join(lines),
            "pk": {**base, **pred, "cl": cl_used, "vd": vd_used, "auc24_base": base["auc24"], "auc_mic_base": auc_mic_base},
            "suggestion": suggestion,
            "plot": plot,
        }
    def calc_linezolid(self, pk: dict, method: str) -> dict:
        target_low, target_high = (2, 8) if method != "Bayesian (hematológia)" else (2, 7)
        prior_cl = 4.8
        if method == "Bayesian (hematológia)":
            prior_cl = 4.0
        if pk["crcl"] < 40:
            prior_cl *= 0.80
        if pk["age"] > 70:
            prior_cl *= 0.85
        prior_vd = 45 + (5 if pk["obesity"] else 0)
        if method == "Gyors TDM":
            trough = pk["c1"] if pk["c1"] is not None else pk["c2"]
            if trough is None:
                raise ValueError("Gyors linezolid módhoz legalább egy trough szükséges.")
            auc24 = (pk["dose"] * 24.0 / pk["tau"]) / prior_cl
            status = "Célzónában" if target_low <= trough <= target_high else ("Alulexpozíció" if trough < target_low else "Túlexpozíció")
            regimen = "600 mg q12h" if status == "Célzónában" else ("600 mg q8-12h" if status == "Alulexpozíció" else "600 mg q24h vagy 300 mg q12h")
            return {
                "drug": "Linezolid", "method": method,
                "pk": {"trough": trough, "auc24": auc24, "cl": prior_cl, "vd": prior_vd},
                "suggestion": {"best": {"dose": 600 if "600" in regimen else 300, "tau": 12 if "q12" in regimen else 24, "auc24": auc24, "trough": trough}},
                "status": status, "primary": f"Cmin {trough:.1f}", "secondary": f"AUC24 {auc24:.1f}", "regimen": regimen,
                "status_sub": f"Gyors trough-cél: {target_low}–{target_high} mg/L",
                "report": "\n".join([
                    f"LINEZOLID – {method}", f"Gyors trough-alapú interpretáció.", f"Trough: {trough:.1f} mg/L | cél: {target_low}–{target_high} mg/L",
                    f"Becsült AUC24 (prior CL alapján): {auc24:.1f} mg·h/L", f"Javaslat: {regimen}",
                ]),
                "plot": self._plot_series_generic(pk, prior_cl, prior_vd, "Linezolid")
            }
        self.validate_two_point(pk)
        ke_obs = math.log(pk["c1"] / pk["c2"]) / (pk["t2"] - pk["t1"])
        cl_obs = max(1.5, ke_obs * prior_vd)
        obs_w = 0.60 if method == "Bayesian (általános)" else 0.50
        cl = self.posterior_blend(prior_cl, cl_obs, obs_w)
        vd = self.posterior_blend(prior_vd, cl_obs / ke_obs, 0.45)
        pred = self.predict_one_compartment(pk["dose"], pk["tau"], pk["tinf"], cl, vd)
        auc_mic = pred["auc24"] / pk["mic"] if pk.get("mic") else None
        options = [(600, 8), (600, 12), (600, 24), (300, 12)]
        cands = []
        for dose, tau in options:
            p = self.predict_one_compartment(dose, tau, pk["tinf"], cl, vd)
            score = 0
            if p["trough"] < target_low:
                score += (target_low - p["trough"]) * 8
            if p["trough"] > target_high:
                score += (p["trough"] - target_high) * 8
            if pk.get("mic"):
                target_auc = 100 * pk["mic"]
                score += abs(p["auc24"] - target_auc) * 0.4
            cands.append({"dose": dose, "tau": tau, **p, "score": score})
        cands.sort(key=lambda x: x["score"])
        status = "Célzónában" if target_low <= pred["trough"] <= target_high else ("Alulexpozíció" if pred["trough"] < target_low else "Túlexpozíció")
        report = [
            f"LINEZOLID – {method}",
            "Modell: egykompartmentes prior + megfigyelés posterior blend (prototípus)",
            f"CL: {cl:.2f} L/h | Vd: {vd:.2f} L | Cmin: {pred['trough']:.2f} mg/L | AUC24: {pred['auc24']:.1f} mg·h/L",
            f"AUC24/MIC: {'n.a.' if auc_mic is None else f'{auc_mic:.1f}'} | trough-cél: {target_low}–{target_high} mg/L",
            f"Javaslat: {cands[0]['dose']:.0f} mg q{cands[0]['tau']:.0f}h (pred trough {cands[0]['trough']:.1f}, AUC24 {cands[0]['auc24']:.1f})",
        ]
        return {
            "drug": "Linezolid", "method": method, "pk": {"cl": cl, "vd": vd, **pred}, "suggestion": {"best": cands[0], "candidates": cands},
            "status": status, "primary": f"Cmin {pred['trough']:.1f}", "secondary": f"AUC24 {pred['auc24']:.1f}",
            "regimen": f"{cands[0]['dose']:.0f} mg q{cands[0]['tau']:.0f}h", "status_sub": f"Cél trough {target_low}–{target_high} mg/L",
            "report": "\n".join(report), "plot": self._plot_series_generic(pk, cl, vd, "Linezolid")
        }

    def calc_amikacin(self, pk: dict, method: str) -> dict:
        self.validate_two_point(pk)
        vd_prior = pk["weight"] * (0.30 if method == "Konvencionális Bayesian" else 0.35)
        ke_obs = math.log(pk["c1"] / pk["c2"]) / (pk["t2"] - pk["t1"])
        cl_obs = max(0.5, ke_obs * vd_prior)
        cl_prior = pk["crcl"] * 0.06
        cl = self.posterior_blend(cl_prior, cl_obs, 0.60 if method == "Extended-interval Bayesian" else 0.65)
        vd = self.posterior_blend(vd_prior, cl_obs / ke_obs, 0.45)
        pred = self.predict_one_compartment(pk["dose"], pk["tau"], max(pk["tinf"], 0.5), cl, vd)
        if method == "Extended-interval Bayesian":
            target_peak = (50, 64)
            target_trough_max = 2.0
            options = [(1000, 24), (1250, 24), (1500, 24), (1750, 24), (2000, 24), (1500, 36)]
        else:
            target_peak = (20, 30)
            target_trough_max = 5.0
            options = [(500, 12), (750, 12), (1000, 12), (500, 8), (750, 8)]
        cands = []
        for dose, tau in options:
            p = self.predict_one_compartment(dose, tau, max(pk["tinf"], 0.5), cl, vd)
            score = 0
            if p["peak"] < target_peak[0]:
                score += (target_peak[0] - p["peak"]) * 3
            if p["peak"] > target_peak[1]:
                score += (p["peak"] - target_peak[1]) * 2
            if p["trough"] > target_trough_max:
                score += (p["trough"] - target_trough_max) * 8
            cands.append({"dose": dose, "tau": tau, **p, "score": score})
        cands.sort(key=lambda x: x["score"])
        status = "Célzónában" if target_peak[0] <= pred["peak"] <= target_peak[1] and pred["trough"] <= target_trough_max else ("Alulexpozíció" if pred["peak"] < target_peak[0] else "Túlexpozíció")
        report = [
            f"AMIKACIN – {method}",
            "Modell: prior + megfigyelés posterior blend (prototípus), a kétkompartmentes valóság bedside egyszerűsítése.",
            f"CL: {cl:.2f} L/h | Vd: {vd:.2f} L | peak: {pred['peak']:.1f} mg/L | trough: {pred['trough']:.1f} mg/L",
            f"Cél peak: {target_peak[0]}–{target_peak[1]} mg/L | trough < {target_trough_max} mg/L",
            f"Javaslat: {cands[0]['dose']:.0f} mg q{cands[0]['tau']:.0f}h (pred peak {cands[0]['peak']:.1f}, trough {cands[0]['trough']:.1f})",
        ]
        return {
            "drug": "Amikacin", "method": method, "pk": {"cl": cl, "vd": vd, **pred}, "suggestion": {"best": cands[0], "candidates": cands},
            "status": status, "primary": f"Peak {pred['peak']:.1f}", "secondary": f"Trough {pred['trough']:.1f}",
            "regimen": f"{cands[0]['dose']:.0f} mg q{cands[0]['tau']:.0f}h", "status_sub": f"CL {cl:.2f} L/h", "report": "\n".join(report),
            "plot": self._plot_series_generic(pk, cl, vd, "Amikacin")
        }

    def _plot_series_vanco(self, pk: dict, current: dict, best: dict) -> dict:
        return {
            "title": "Vancomycin koncentráció-idő profil",
            "current_x": [0, pk["tinf"], pk["tau"]],
            "current_y": [current["true_trough"], current["true_peak"], current["true_trough"]],
            "best_x": [0, best["tinf"], best["tau"]],
            "best_y": [best["trough"], best["peak"], best["trough"]],
            "obs_x": [pk["t1"], pk["t2"]],
            "obs_y": [pk["c1"], pk["c2"]],
        }

    def _plot_series_generic(self, pk: dict, cl: float, vd: float, title: str) -> dict:
        steps = 100
        xs = [pk["tau"] * i / steps for i in range(steps + 1)]
        ke = cl / vd
        r0 = pk["dose"] / max(pk["tinf"], 0.5)
        ys = []
        peak = (r0 / cl) * (1 - math.exp(-ke * max(pk["tinf"], 0.5))) / (1 - math.exp(-ke * pk["tau"]))
        for x in xs:
            if x <= max(pk["tinf"], 0.5):
                c = (r0 / cl) * (1 - math.exp(-ke * x)) / (1 - math.exp(-ke * pk["tau"]))
            else:
                c = peak * math.exp(-ke * (x - max(pk["tinf"], 0.5)))
            ys.append(c)
        obs_x = [v for v in [pk.get("t1"), pk.get("t2"), pk.get("t3")] if v is not None]
        obs_y = [v for v in [pk.get("c1"), pk.get("c2"), pk.get("c3")] if v is not None]
        return {"title": title, "current_x": xs, "current_y": ys, "best_x": [], "best_y": [], "obs_x": obs_x, "obs_y": obs_y}

    def render_plot(self, spec: dict):
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=spec["current_x"], y=spec["current_y"], mode="lines", name="Jelenlegi / becsült profil"))
        if spec.get("best_x"):
            fig.add_trace(go.Scatter(x=spec["best_x"], y=spec["best_y"], mode="lines", name="Ajánlott profil", line=dict(dash="dash")))
        if spec.get("obs_x"):
            fig.add_trace(go.Scatter(x=spec["obs_x"], y=spec["obs_y"], mode="markers", name="Mért pontok", marker=dict(size=10)))
        fig.update_layout(title=spec["title"], xaxis_title="Óra", yaxis_title="Koncentráció (mg/L)", template="plotly_white", margin=dict(l=30, r=30, t=50, b=30))
        html = pio.to_html(fig, include_plotlyjs="cdn", full_html=False)
        if WEB_OK:
            self.plot_view.setHtml(html)
        else:
            self.plot_view.setHtml(html)

    def refresh_context_panels(self):
        if not hasattr(self, "antibiotic_combo"):
            return
        abx = self.antibiotic_combo.currentText()
        method = self.method_combo.currentText()
        self.quick_context.setHtml(self.build_quick_context_html(abx, method))
        self.guide_browser.setHtml(self.build_guide_html(abx, method))
        self.evidence_browser.setHtml(self.build_evidence_html(abx, method))
        self.empirical_browser.setHtml(self.build_empirical_html(abx, method))

    def build_quick_context_html(self, abx: str, method: str) -> str:
        reason = METHOD_RECOMMENDATION.get(abx, {}).get(method, "")
        refs = EVIDENCE.get(abx, {}).get(method, [])
        ref_short = "<br>".join(
            [f"• <b>{r.year}</b> – {r.journal} (PMID: {r.pmid or 'n.a.'})" for r in refs[:2]]
        ) or "Nincs kiválasztott referencia."
        return (
            f"<h2>{abx} – {method}</h2>"
            f"<p><b>Ajánlott helyzet:</b> {reason}</p>"
            f"<p><b>Miért ezt válaszd?</b> Lásd az Info és citációk fület.</p>"
            f"<h3>Gyors referenciák</h3><p>{ref_short}</p>"
        )

    def build_guide_html(self, abx: str, method: str) -> str:
        meta = GUIDE_TEXT.get((abx, method), {"why": [], "avoid": []})
        why = "".join(f"<li>{x}</li>" for x in meta.get("why", []))
        avoid = "".join(f"<li>{x}</li>" for x in meta.get("avoid", []))
        extra = ""
        if abx == "Vancomycin":
            extra = "<p><b>Empirikus worst-case szemlélet:</b> amíg nincs MIC, gyakran MIC=1 mg/L feltételezéssel indulunk, de a túlzott AUC kerülendő.</p>"
        elif abx == "Linezolid":
            extra = "<p><b>Fontos:</b> a linezolidnál a TDM célja nemcsak a hatásosság, hanem az overexposure és hematológiai toxicitás kerülése is.</p>"
        else:
            extra = "<p><b>Fontos:</b> amikacinnál a peak/trough interpretáció és az adagolási stratégia (extended vs conventional) külön választandó.</p>"
        return (
            f"<h2>Info – {abx} / {method}</h2>"
            f"<h3>Mikor használd</h3><ul>{why}</ul>"
            f"<h3>Mikor értelmezd óvatosan / mikor ne ezt válaszd</h3><ul>{avoid}</ul>"
            f"{extra}"
        )

    def build_evidence_html(self, abx: str, method: str) -> str:
        refs = EVIDENCE.get(abx, {}).get(method, [])
        parts = [f"<h2>Látható citációk – {abx} / {method}</h2>"]
        if not refs:
            parts.append("<p>Nincs rögzített referencia ehhez a módhoz.</p>")
        for i, ref in enumerate(refs, 1):
            pubmed_link = f"https://pubmed.ncbi.nlm.nih.gov/{ref.pmid}/" if ref.pmid else ""
            parts.append(
                f"<div style='margin-bottom:14px;padding:10px;border:1px solid #94a3b8;border-radius:10px;'>"
                f"<b>{i}. {ref.title}</b><br>"
                f"<span>{ref.journal}, {ref.year}</span><br>"
                f"<span>PMID: {ref.pmid or 'n.a.'}</span>"
                + (f" | DOI: {ref.doi}" if ref.doi else "")
                + (f" | <a href='{pubmed_link}'>PubMed</a>" if pubmed_link else "")
                + f"<br><i>{ref.note}</i></div>"
            )
        parts.append("<p><b>Megjegyzés:</b> a programon belüli citációk módszerválasztást támogatnak, nem helyettesítik a lokális protokollt vagy a teljes guideline-olvasást.</p>")
        return "".join(parts)

    def build_empirical_html(self, abx: str, selected_method: str) -> str:
        mode = self.empirical_mode_combo.currentText()
        rows = [r for r in self.empirical_data if str(r.get("drug", "")).strip().lower() == abx.lower()]
        parts = [f"<h2>Empirikus támogatás – {abx}</h2>"]
        parts.append(f"<p><b>Kiválasztott stratégia:</b> {mode}</p>")
        parts.append(f"<p><b>Aktuális TDM-módszer:</b> {selected_method}</p>")
        if mode.startswith("Worst"):
            parts.append("<p><b>Worst-case logika:</b> nagy rizikójú beteg, neutropenia, septic shock, korábbi MDR-kolonizáció vagy mély fertőzés esetén használható konzervatívabb cél.</p>")
        elif mode.startswith("Irányított"):
            parts.append("<p><b>Irányított mód:</b> ha már ismert a kórokozó/MIC, válts át valódi egyéni célzásra, az empirikus cél csak kiindulópont.</p>")
        else:
            parts.append("<p><b>Empirikus mód:</b> az empirikus cél csak kiindulópont; amint ismert a kórokozó vagy MIC, válts egyéni célzásra.</p>")
        if not rows:
            parts.append("<p>Nincs lokális empirikus tábla ehhez az antibiotikumhoz.</p>")
            return "".join(parts)

        def score_row(r: dict) -> int:
            blob = " ".join([
                str(r.get("method", "")),
                str(r.get("toxicity_method", "")),
                str(r.get("parameter", "")),
                str(r.get("target", "")),
                str(r.get("note", "")),
            ]).lower()
            method = selected_method.lower()
            score = 0
            if "klasszikus" in method:
                if "trough" in blob or "völgy" in blob:
                    score += 4
                if "auc" in blob:
                    score += 2
            if "bayesian" in method:
                if "auc" in blob:
                    score += 4
                if "bayes" in blob:
                    score += 2
            if "icu" in method or "haladó" in method:
                if "auc" in blob:
                    score += 3
                if "trough" in blob or "völgy" in blob:
                    score += 1
            if "gyors" in method:
                if "trough" in blob or "völgy" in blob:
                    score += 4
            if "hemat" in method:
                if "hemat" in blob or "toxicit" in blob:
                    score += 3
            if "extended" in method:
                if "peak" in blob or "csúcs" in blob or "pae" in blob:
                    score += 4
            if "konvencionális" in method:
                if "trough" in blob or "völgy" in blob:
                    score += 2
                if "peak" in blob or "csúcs" in blob:
                    score += 2
            return score

        scored = sorted(rows, key=score_row, reverse=True)
        top_score = score_row(scored[0]) if scored else 0
        best_rows = [r for r in scored if score_row(r) == top_score and top_score > 0] or scored[:1]

        parts.append("<h3>Az aktuális módszerhez legjobban illeszkedő empirikus célok</h3>")
        for r in best_rows:
            parts.append(
                "<div style='margin-bottom:14px;padding:10px;border:2px solid #2563eb;border-radius:10px;background:#eff6ff;'>"
                f"<b>Célkórokozó / coverage:</b> {r.get('coverage','—')}<br>"
                f"<b>Mért paraméter:</b> {r.get('parameter','—')}<br>"
                f"<b>Empirikus target:</b> {r.get('target','—')}<br>"
                f"<b>Elsődlegesen illeszkedő módszer:</b> {r.get('method','—')}<br>"
                f"<b>Toxicitási követés:</b> {r.get('toxicity_method','—')}<br>"
                f"<b>Megjegyzés:</b> {r.get('note','—')}"
                "</div>"
            )

        if len(scored) > len(best_rows):
            parts.append("<h3>További lehetséges empirikus célok</h3>")
            for r in scored[len(best_rows):]:
                parts.append(
                    "<div style='margin-bottom:14px;padding:10px;border:1px solid #94a3b8;border-radius:10px;'>"
                    f"<b>Célkórokozó / coverage:</b> {r.get('coverage','—')}<br>"
                    f"<b>Mért paraméter:</b> {r.get('parameter','—')}<br>"
                    f"<b>Empirikus target:</b> {r.get('target','—')}<br>"
                    f"<b>Toxicitási határ / megfontolás:</b> {r.get('toxicity','—')}<br>"
                    f"<b>Metódus:</b> {r.get('method','—')}<br>"
                    f"<b>Megjegyzés:</b> {r.get('note','—')}"
                    "</div>"
                )
        return "".join(parts)

    def calculate(self):
        try:
            pk = self.collect_common()
            abx = self.antibiotic_combo.currentText()
            method = self.method_combo.currentText()
            if abx == "Vancomycin":
                res = self.calc_vancomycin(pk, method)
            elif abx == "Linezolid":
                res = self.calc_linezolid(pk, method)
            else:
                res = self.calc_amikacin(pk, method)
            self.results = res
            self.latest_report = res["report"]
            self.result_text.setPlainText(res["report"])
            self.card_primary.update_card(res["primary"], f"{abx} – {method}")
            self.card_secondary.update_card(res["secondary"], res.get("status_sub", ""))
            self.card_regimen.update_card(res["regimen"], "Elsődleges javaslat")
            self.card_status.update_card(res["status"], res.get("status_sub", ""))
            self.render_plot(res["plot"])
            self.append_history_record(pk, res)
            self.export_status.setText("Riport elkészült és naplózva lett. Menthető TXT vagy JSON formában.")
            self.tabs.setCurrentWidget(self.results_tab)
        except Exception as e:
            QMessageBox.critical(self, "Hiba", str(e))


    def _build_plot_spec(self) -> dict:
        if isinstance(self.results, dict):
            spec = self.results.get('plot') or {}
            if isinstance(spec, dict):
                return deepcopy(spec)
        return {}

    def _export_plot_to_png(self) -> Optional[str]:
        if not self.results or not MATPLOTLIB_OK:
            return None
        spec = self.results.get("plot") or {}
        xs = spec.get("current_x") or []
        ys = spec.get("current_y") or []
        if not xs or not ys:
            return None
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
        tmp.close()
        fig = plt.figure(figsize=(10, 5.6), dpi=160)
        ax = fig.add_subplot(111)
        ax.plot(xs, ys, label="Jelenlegi / becsült profil", linewidth=2)
        if spec.get("best_x") and spec.get("best_y"):
            ax.plot(spec.get("best_x"), spec.get("best_y"), linestyle="--", linewidth=2, label="Ajánlott profil")
        if spec.get("obs_x") and spec.get("obs_y"):
            ax.scatter(spec.get("obs_x"), spec.get("obs_y"), label="Mért pontok", s=45)
        ax.set_title(spec.get("title", "Koncentráció-idő profil"))
        ax.set_xlabel("Óra")
        ax.set_ylabel("Koncentráció (mg/L)")
        ax.grid(True, alpha=0.3)
        ax.legend()
        fig.tight_layout()
        fig.savefig(tmp.name, format="png", bbox_inches="tight")
        plt.close(fig)
        return tmp.name

    def _render_report_pdf_to_path(self, path: str):
        if not self.latest_report or not self.results:
            raise ValueError('Nincs menthető riport.')
        if REPORTLAB_OK:
            c = pdf_canvas.Canvas(path, pagesize=A4)
            page_w, page_h = A4
            margin = 15 * mm
            y_pos = page_h - margin

            def new_page():
                nonlocal y_pos
                c.showPage()
                y_pos = page_h - margin

            def draw_line(line: str, font_name: str = 'Helvetica', font_size: int = 10, step_mm: float = 4.8):
                nonlocal y_pos
                if y_pos < margin + 15 * mm:
                    new_page()
                c.setFont(font_name, font_size)
                c.drawString(margin, y_pos, str(line)[:150])
                y_pos -= step_mm * mm

            c.setTitle('Klinikai TDM riport')
            draw_line('Klinikai TDM riport', 'Helvetica-Bold', 16, 6.5)
            draw_line(f"Antibiotikum: {self.results.get('drug', '—')}", 'Helvetica-Bold', 11, 5)
            draw_line(f"Módszer: {self.results.get('method', '—')}", 'Helvetica-Bold', 11, 6)
            for line in self.latest_report.splitlines():
                safe_line = (line or ' ').replace('\t', '    ')
                parts = [safe_line[i:i+120] for i in range(0, len(safe_line), 120)] or [' ']
                for part in parts:
                    draw_line(part)

            img_path = self._export_plot_to_png()
            if img_path and os.path.exists(img_path):
                try:
                    new_page()
                    draw_line('Vizualizáció', 'Helvetica-Bold', 14, 8)
                    usable_w = page_w - 2 * margin
                    usable_h = page_h - 2 * margin - 10 * mm
                    image = QImage(img_path)
                    img_w = max(1, image.width())
                    img_h = max(1, image.height())
                    scale = min(float(usable_w) / float(img_w), float(usable_h) / float(img_h))
                    draw_w = float(img_w) * scale
                    draw_h = float(img_h) * scale
                    x = float(margin) + (float(usable_w) - draw_w) / 2.0
                    y_img = float(margin) + (float(usable_h) - draw_h) / 2.0
                    c.drawImage(img_path, x, y_img, width=draw_w, height=draw_h, preserveAspectRatio=True, mask='auto')
                finally:
                    try:
                        os.remove(img_path)
                    except Exception:
                        pass
            c.save()
            return
        if MATPLOTLIB_OK and PdfPages is not None:
            with PdfPages(path) as pdf:
                fig1 = plt.figure(figsize=(8.27, 11.69))
                fig1.clf()
                ax1 = fig1.add_axes([0.07, 0.05, 0.86, 0.9])
                ax1.axis('off')
                header = f"Klinikai TDM riport\n\nAntibiotikum: {self.results.get('drug', '—')}\nMódszer: {self.results.get('method', '—')}\n\n"
                text_body = header + (self.latest_report or '')
                wrapped = []
                for raw in text_body.splitlines():
                    raw = raw or ' '
                    wrapped.extend([raw[i:i+110] for i in range(0, len(raw), 110)] or [' '])
                ax1.text(0.0, 1.0, '\n'.join(wrapped), va='top', ha='left', family='monospace', fontsize=9)
                pdf.savefig(fig1)
                plt.close(fig1)
                spec = self._build_plot_spec()
                if spec and spec.get('current_x') and spec.get('current_y'):
                    fig2 = plt.figure(figsize=(8.27, 11.69))
                    ax2 = fig2.add_axes([0.1, 0.12, 0.82, 0.75])
                    ax2.plot(spec.get('current_x') or [], spec.get('current_y') or [], linewidth=2, label='Jelenlegi / becsült profil')
                    if spec.get('best_x') and spec.get('best_y'):
                        ax2.plot(spec.get('best_x'), spec.get('best_y'), linestyle='--', linewidth=2, label='Ajánlott profil')
                    if spec.get('obs_x') and spec.get('obs_y'):
                        ax2.scatter(spec.get('obs_x'), spec.get('obs_y'), s=45, label='Mért pontok')
                    ax2.set_title(spec.get('title', 'Koncentráció-idő profil'))
                    ax2.set_xlabel('Óra')
                    ax2.set_ylabel('Koncentráció (mg/L)')
                    ax2.grid(True, alpha=0.3)
                    ax2.legend()
                    pdf.savefig(fig2)
                    plt.close(fig2)
            return
        raise RuntimeError('A PDF exporthoz sem ReportLab, sem matplotlib PdfPages nem érhető el.')

    def save_report_pdf(self):
        if not self.latest_report or not self.results:
            QMessageBox.information(self, 'Nincs riport', 'Előbb számolj egy eredményt.')
            return
        path, _ = QFileDialog.getSaveFileName(self, 'PDF riport mentése', 'tdm_riport.pdf', 'PDF (*.pdf)')
        if not path:
            return
        if not path.lower().endswith('.pdf'):
            path += '.pdf'
        try:
            self._render_report_pdf_to_path(path)
            if not os.path.exists(path) or os.path.getsize(path) == 0:
                raise RuntimeError('A PDF fájl nem jött létre, vagy üres maradt.')
            QMessageBox.information(self, 'PDF mentés', f'A riport PDF-be mentve:\n{path}')
        except Exception as e:
            QMessageBox.warning(self, 'PDF export hiba', str(e))


    def save_report_txt(self):
        if not self.latest_report:
            QMessageBox.information(self, "Nincs riport", "Előbb számolj egy eredményt.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "TXT riport mentése", "tdm_riport.txt", "Szövegfájl (*.txt)")
        if not path:
            return
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.latest_report)
        self.export_status.setText(f"TXT mentve: {path}")

    def save_result_json(self):
        if not self.results:
            QMessageBox.information(self, "Nincs eredmény", "Előbb számolj egy eredményt.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "JSON mentése", "tdm_eredmeny.json", "JSON (*.json)")
        if not path:
            return
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.results, f, ensure_ascii=False, indent=2, default=str)
        self.export_status.setText(f"JSON mentve: {path}")


def main():
    app = QApplication(sys.argv)
    auth = AuthDialog()
    if auth.exec() != QDialog.Accepted or not auth.current_user:
        sys.exit(0)
    window = TDMMainWindow(current_user=auth.current_user)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
