# Nexus Pokrok (Quantum VIP V2)

Moderný a optimalizovaný systém pre správu a streamovanie videa s integrovaným systémom extraktorov. Verzia V2 (God-Tier Architecture) prináša prechod na Clean Architecture, spracovanie na pozadí pomocou Celery a Redisu, a úplne novú funkciu pre P2P Torrent Streaming.

## Novinky vo verzi V2
- **Clean Architecture:** Kód API je rozdelený do viacerých logických modulov.
- **Spracovanie na pozadí (Celery + Redis):** Náročné úlohy ako sťahovanie, kontrola linkov, a sťahovanie náhľadov už neblokujú hlavný webový server. Prebiehajú v samostatnom okne (workeri).
- **P2P Torrent Streaming:** Podpora pre priame vkladanie `magnet:` linkov s možnosťou ich okamžite začať streamovať počas toho, ako sa na pozadí sťahujú a trvalo uložia do lokálnej knižnice.
- **AI Semantic Search (Qdrant):** Systém využíva model `SentenceTransformers` na tvorbu vektorových vnorení (embeddings) a vyhľadávanie obsahu podľa sémantického kontextu.

---

## 🚀 Inštalácia a Spustenie (Návod pre Windows)

### Krok 1: Príprava externých programov
Aby všetko bežalo ako po masle, potrebuješ mať nainštalované tieto programy (ak ich ešte nemáš):
1. **Python 3.10+** (Pri inštalácii nezabudni zaškrtnúť "Add Python to PATH").
2. **Node.js:** Stiahni si ho z [nodejs.org](https://nodejs.org/). Následne otvor Príkazový riadok (cmd) a spusti:
   ```cmd
   npm install -g webtorrent-cli
   ```
   (Toto nám zabezpečí okamžité streamovanie Torrentov).
3. **Redis pre Windows:** Stiahni a nainštaluj si port Redisu, napríklad z [GitHubu (Memurai)](https://github.com/microsoftarchive/redis/releases). Musí bežať na pozadí.
4. **FFmpeg:** Stiahni zip archív FFmpeg, rozbaľ ho, a priečinok `bin` pridaj do systémových premenných (PATH). Aplikácia si vie niektoré binárky stiahnuť aj sama, ale je lepšie ho mať v systéme.

### Krok 2: Nastavenie kľúčov (.env)
V hlavnej zložke nájdeš súbor `.env` (ak tam nie je, vytvor si ho). Nastav si doň svoje heslá:
```env
DASHBOARD_PASSWORD=TvojeTajneHeslo123!
SECRET_KEY=VygenerujSiNejakyDlheeeeeeeesiKlucTu
DATABASE_URL=sqlite:///./videos.db
REDIS_URL=redis://localhost:6379/0
QDRANT_HOST=localhost
QDRANT_PORT=6333
```

### Krok 3: Spustenie jedným klikom!
Namiesto ručného vypisovania príkazov ti stačí v zložke projektu **dvakrát kliknúť na súbor `start.bat`**.

Tento magický skript urobí všetko za teba:
- Vytvorí izolované Python prostredie (venv).
- Nainštaluje všetky balíčky z `requirements.txt`.
- Pripraví databázu.
- Otvorí ti **nové čierne okno** pre Celery Workera (to minimalizuj, to len sťahuje veci na pozadí).
- V aktuálnom okne ti naštartuje Webový Server.

Akonáhle vypíše, že `Uvicorn running on http://127.0.0.1:8000`, otvor si svoj internetový prehliadač, choď na danú adresu a môžeš fungovať!
