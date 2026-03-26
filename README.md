# Klinikai TDM Platform

GitHub-ready, kontrollált refaktor scaffold a `legacy/tdm_platform_v0_9_3_beta_fixed.py` monolitból.

A projekt két célt szolgál egyszerre:
1. **stabil visszamenőleges működés** a `legacy/tdm_platform_v0_9_3_beta_fixed.py` referenciafájllal
2. **biztonságos, kis lépésekben történő modularizáció** a `tdm_platform/` csomag alá

## Gyors indítás

```bash
pip install -r requirements.txt
python main.py
```

Hasznos ellenőrzések:

```bash
python smoke.py
python -m pytest -q
python -m compileall main.py tdm_platform tests
```

## Architecture

### Legacy layer
A `legacy/tdm_platform_v0_9_3_beta_fixed.py` továbbra is a stabil referencia-implementáció. A cél nem az azonnali törlése, hanem az, hogy a kipróbált működés megmaradjon, miközben a felelősségi körök fokozatosan modulokra válnak szét.

### Modular PK engines
A farmakokinetikai számítások külön engine-ekben élnek:
- `tdm_platform/pk/vancomycin_engine.py`
- `tdm_platform/pk/linezolid_engine.py`
- `tdm_platform/pk/amikacin_engine.py`
- `tdm_platform/pk/common.py`

Ez biztosítja, hogy a klinikai számítási logika a UI-tól és a perzisztenciától elkülönítve maradjon.

### Services layer
A technikai integrációk a `tdm_platform/services/` rétegben vannak:
- `smtp_service.py` – SMTP konfiguráció és e-mail küldés
- `pdf_service.py` – PDF riport helper-ek

### Core domain layer
A `tdm_platform/core/` réteg tartalmazza a domain- és üzleti logika moduljait:
- `models.py` – strukturált adatmodellek
- `auth.py` – auth és felhasználó store segédfüggvények
- `history.py` – history store és metaadat-hozzáfűzés
- `permissions.py` – szerepkörök és jogosultsági helper-ek

### UI layer separation
A UI réteg a `tdm_platform/ui/` csomagban épül tovább:
- `main_window.py` – a főablak kompozíciós és wiring belépési pontja
- `auth_dialog.py` – auth dialog wrapper
- `history_tab.py` – history tab UI-only segédlogika
- `components/` – közös widgetek, dialog helper-ek, státuszsáv

Ebben a lépésben a UI réteg még **legacy-kompatibilis wrapperként** működik: a vizuális működés és UX változatlan marad, de a betöltés, mentés és szolgáltatás-hívások már moduláris store/service rétegekre támaszkodnak.

### Entry point flow
Az alkalmazás futási útja:
1. `python main.py`
2. `main.py` meghívja a `tdm_platform.ui.main_window.run_app()` belépési pontot
3. a `ui.auth_dialog.AuthDialog` indul el
4. sikeres belépés után a `ui.main_window.MainWindow` nyílik meg
5. a főablak a PK engine-eket, a `core` store-okat és a `services` modulokat hívja
6. a legacy fájl változatlan referencia marad, de a wiring már a moduláris csomagokon keresztül történik

## Refactor Roadmap

### Completed extractions
Az eddig kiszervezett részek:
- app metadata és build/schema információk
- storage path helper-ek
- JSON load/save helper-ek
- SMTP service réteg
- PDF service réteg
- auth core logika és `UserStore`
- history core logika és `HistoryStore`
- vancomycin, linezolid és amikacin PK engine-ek

### Current UI extraction step
A mostani lépés célja a UI réteg strukturálása:
- `ui` package létrehozása
- auth dialog wrapper modul létrehozása
- history tab UI-only logika külön modulba emelése
- főablak moduláris wiring rétegének bevezetése
- `main.py` átállítása az új UI entry pointra

### Next planned steps
A következő refaktor célok:
- feature panel separation
- legacy logic removal
- Bayesian engine stabilization
- extended regression tests

## Development Workflow

### Run
Fejlesztői futtatás:

```bash
pip install -r requirements.txt
python main.py
```

### Test
Minimális regressziós csomag:

```bash
python smoke.py
python -m pytest -q
python -m compileall main.py tdm_platform tests
```

### Safe refactor rules
Biztonságos refaktor során javasolt szabályok:
- a PK számítási logikát ne módosítsd UI refaktor miatt
- a JSON perzisztencia sémát ne változtasd
- a `legacy/` fájlt referencia célra hagyd érintetlenül
- először wrapper/adapter modult hozz létre, csak utána válts át hívásokat
- minden extraction után futtasd a smoke/pytest/compileall ellenőrzéseket
- a `python main.py` indítási útvonalat folyamatosan tartsd működőképesen

## Jelenlegi mappaszerkezet

- `main.py` – moduláris belépési pont
- `legacy/tdm_platform_v0_9_3_beta_fixed.py` – stabil referencia monolit
- `tdm_platform/app_meta.py` – verzió/build/schema metadata
- `tdm_platform/storage/paths.py` – adatfájl útvonalak
- `tdm_platform/storage/json_store.py` – JSON load/save helper-ek
- `tdm_platform/core/models.py` – domain modellek
- `tdm_platform/core/auth.py` – auth store és helper-ek
- `tdm_platform/core/history.py` – history store
- `tdm_platform/core/permissions.py` – jogosultsági logika
- `tdm_platform/services/smtp_service.py` – SMTP service
- `tdm_platform/services/pdf_service.py` – PDF service
- `tdm_platform/pk/*.py` – PK engine-ek
- `tdm_platform/ui/*.py` – UI wrapper és komponens modulok
- `tdm_platform/ui/components/*.py` – közös UI elemek
- `tests/` – regressziós tesztek

## Refaktor állapot röviden

A scaffold már túl van az alap modularizáción, és a UI refaktor első kontrollált lépése is megtörtént: a belépési pont már az új `ui` csomagot használja, miközben a legacy viselkedés változatlan referencia marad.
