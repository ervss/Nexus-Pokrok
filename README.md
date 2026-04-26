# Nexus Pokrok

Moderný a optimalizovaný systém pre správu a streamovanie videa s integrovaným systémom extraktorov.

## Štruktúra projektu
- `app/`: Hlavná FastAPI aplikácia (asynchrónna).
- `extractors/`: Kolekcia synchrónnych extraktorov pre samostatné skripty.
- `extensions/`: Prehliadačové rozšírenia pre automatizovaný import (Chrome/Firefox).
- `scripts/`: Užitočné utility pre údržbu databázy a hromadné vyhľadávanie.
- `alembic/`: Databázové migrácie.

## Rýchly štart
1. Skopíruj `bridge.env.example` na `.env` a nastav potrebné premenné.
2. Nainštaluj závislosti:
   ```bash
   pip install -r requirements.txt
   ```
3. Spusti server:
   ```bash
   python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
   ```

## Poznámky
- SQLite databáza (`videos.db`) a náhľady sú ignorované pomocou `.gitignore`.
- Pre plnú funkčnosť je potrebné mať nainštalovaný `ffmpeg`.
