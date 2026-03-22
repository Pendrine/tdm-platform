# Klinikai TDM Platform

GitHub-ready refaktor scaffold a `tdm_platform_v0_9_3_beta_fixed.py` monolitból.

Ez a csomag két célt szolgál:
1. **stabil visszamenőleges működés** a `legacy/tdm_platform_v0_9_3_beta_fixed.py` fájllal
2. **kontrollált architektúra-refaktor** előkészítése és fokozatos kiváltása moduláris csomagokra

## Javasolt workflow

- `main.py` → belépési pont
- `legacy/` → a jelenlegi stabil monolit / referencia implementáció
- `tdm_platform/` → ide kerülnek át fokozatosan a kiszervezett modulok

## Gyors indítás

```bash
pip install -r requirements.txt
python main.py
python smoke.py
python -m pytest -q
```

## Jelenlegi refaktor állapot

A repo már nem csak scaffold:

- az app metadata és a storage útvonalak külön modulokban vannak
- a JSON perzisztencia külön helper réteget kapott
- az SMTP és PDF funkciók önálló service modulokban vannak
- a vancomycin, linezolid és amikacin PK számítások külön engine-ekbe kerültek
- a felhasználó/auth és history mentési alaplogika külön core modulokba lett kiemelve

## Mappa-struktúra

- `tdm_platform/app_meta.py` – verzió, build, séma és strukturált metadata objektum
- `tdm_platform/storage/paths.py` – adatfájl útvonalak és `StoragePaths`
- `tdm_platform/storage/json_store.py` – biztonságos JSON load/save, list/dict helperrel
- `tdm_platform/core/models.py` – `User` / `HistoryRecord` / `SMTPSettings`
- `tdm_platform/core/permissions.py` – szerepkör logika
- `tdm_platform/core/auth.py` – auth segédfüggvények és `UserStore`
- `tdm_platform/core/history.py` – history perzisztencia és metadata append
- `tdm_platform/services/smtp_service.py` – SMTP beállítások + levélküldés
- `tdm_platform/services/pdf_service.py` – PDF generálás és tördelés
- `tdm_platform/pk/common.py` – közös PK matematikai helper-ek
- `tdm_platform/pk/vancomycin_engine.py` – vancomycin számoló és dózisjavaslat
- `tdm_platform/pk/linezolid_engine.py` – linezolid TDM / Bayesian prototípus
- `tdm_platform/pk/amikacin_engine.py` – amikacin TDM / Bayesian prototípus
- `tdm_platform/resources/citations.py` – strukturált irodalmi hivatkozások
- `legacy/tdm_platform_v0_9_3_beta_fixed.py` – jelenlegi működő build / referencia

## Refaktor sorrend

### Már előkészítve / kiszervezve
1. app meta + paths
2. JSON storage helper-ek
3. SMTP service
4. PDF service
5. vancomycin PK engine
6. auth alaplogika
7. history alaplogika
8. linezolid / amikacin engine

### Következő lépések
1. auth dialog tényleges UI kiszervezése
2. history tab UI kiszervezése
3. main window szétszedése kisebb komponensekre
4. a `legacy/` fokozatos kiváltása a modularizált rétegekkel

## Tesztelés

Jelenleg a minimális regressziós ellenőrzés fut:

```bash
python -m pytest -q
python -m compileall tdm_platform tests
```

## GitHub javaslat

- foundation: scaffold + legacy import
- services/storage: app meta + paths + JSON + SMTP + PDF
- pk: vancomycin + linezolid + amikacin engine-ek
- core: auth/history logika
- ui: auth/history/main window szétválasztás
