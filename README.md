# Klinikai TDM Platform

GitHub-ready refaktor scaffold a `tdm_platform_v0_9_3_beta_fixed.py` monolitból.

Ez a csomag két célt szolgál:
1. **stabil visszamenőleges működés** a `legacy/tdm_platform_v0_9_3_beta_fixed.py` fájllal
2. **kontrollált architektúra-refaktor** előkészítése

## Javasolt workflow

- `main.py` → belépési pont
- `legacy/` → a jelenlegi stabil monolit
- `tdm_platform/` → új architektúra fokozatosan ide kerül át

## Gyors indítás

```bash
pip install -r requirements.txt
python main.py
```

## Mappa-struktúra

- `tdm_platform/app_meta.py` – verzió, build, séma
- `tdm_platform/storage/paths.py` – adatfájl útvonalak
- `tdm_platform/storage/json_store.py` – biztonságos JSON load/save
- `tdm_platform/core/models.py` – User / HistoryRecord / SMTPSettings
- `tdm_platform/core/permissions.py` – szerepkör logika
- `tdm_platform/services/smtp_service.py` – levélküldés
- `tdm_platform/services/pdf_service.py` – PDF generálás
- `tdm_platform/pk/vancomycin_engine.py` – elsőként kiemelt tudományos mag
- `legacy/tdm_platform_v0_9_3_beta_fixed.py` – jelenlegi működő build

## Refaktor sorrend

1. app meta + paths
2. SMTP service
3. PDF service
4. vancomycin PK engine
5. auth dialog
6. history tab
7. linezolid / amikacin engine
8. main window szétszedése

## GitHub javaslat

- első commit: scaffold + legacy import
- második commit: storage/services
- harmadik commit: vancomycin engine
- negyedik commit: auth/history UI szétválasztás
