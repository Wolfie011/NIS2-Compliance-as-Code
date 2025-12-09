````markdown
# NIS2-COMPLIENCE-AS-CODE

Minimalny PoC systemu do zbierania danych o infrastrukturze i oceny podstawowych reguł bezpieczeństwa pod NIS2:

- **nis2_agent** – lokalny agent:
  - skanuje system (OS, otwarte porty TCP, wybrane opcje SSH),
  - ocenia wynik skanu względem reguł zapisanych w YAML,
  - loguje wyniki lokalnie,
  - opcjonalnie wysyła raport do serwera HTTP,
  - może działać w trybie jednorazowym (`once`) lub cyklicznym (`loop`, np. co 6h).
- **nis2_server** – prosty serwer:
  - przyjmuje raporty z agentów,
  - zapisuje je w strukturze plikowej,
  - udostępnia API do przeglądania agentów i ich ostatnich wyników,
  - wystawia prosty dashboard webowy,
  - udostępnia bootstrap do instalacji agenta na Windows (`/register`).

---

## Struktura katalogów

Root: `NIS2-COMPLIENCE-AS-CODE/`

```text
NIS2-COMPLIENCE-AS-CODE/
├── nis2_agent/
│   ├── __init__.py
│   ├── client.py
│   ├── logging_config.py
│   ├── main.py
│   ├── rules_engine.py
│   └── scanner.py
├── nis2_server/
│   ├── __init__.py
│   ├── config.py
│   ├── logging_config.py
│   ├── main.py
│   ├── models.py
│   └── storage.py
├── rules/
│   └── basic.yml
├── downloads/           # tutaj ląduje zbudowany nis2_agent_win.exe
├── logs/                # tworzone/autouzupełniane przez agenta (niekonieczne w repo)
├── server_data/         # tworzone przez serwer (niekonieczne w repo)
├── requirements-agent.txt
├── requirements-server.txt
├── requirements.txt
├── Dockerfile           # obraz serwera
└── docker-compose.yml   # serwer jako usługa (nis2_server)
````

Katalogi `logs/`, `server_data/`, `downloads/` oraz `.venv/` warto dodać do `.gitignore`.

---

## Wymagania

* Python 3.10+
* Zależności z plików `requirements*.txt`

Instalacja (wirtualne środowisko zalecane):

```bash
cd NIS2-COMPLIENCE-AS-CODE
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate

# całość (dev)
pip install -r requirements.txt
```

Alternatywnie osobno:

```bash
pip install -r requirements-server.txt
pip install -r requirements-agent.txt
```

Dodatkowo na maszynie buildowej dla Windows EXE:

```bash
pip install pyinstaller
```

---

## Reguły – przykład (`rules/basic.yml`)

Minimalny zestaw przykładowych reguł:

```yaml
- id: "NIS2-SSH-001"
  description: "Root login po SSH powinien być wyłączony (PermitRootLogin)."
  severity: "high"
  condition: >
    ssh.get("permit_root_login", "").lower() not in ("yes", "without-password")
  tags: ["ssh", "access_control"]

- id: "NIS2-SSH-002"
  description: "SSH nie powinien pozwalać na logowanie hasłem."
  severity: "medium"
  condition: >
    ssh.get("password_authentication", "").lower() == "no"
  tags: ["ssh", "authentication"]

- id: "NIS2-NET-001"
  description: "Port 23 (telnet) nie powinien być otwarty."
  severity: "high"
  condition: >
    23 not in network.get("open_tcp_ports", [])
  tags: ["network", "legacy", "hardening"]
```

Agent przekazuje dane ze skanera do silnika reguł jako słownik (np. `ssh`, `network`), a warunki w YAML są na tym słowniku ewaluowane.

---

## Uruchomienie serwera (tryb dev)

W root projektu:

```bash
uvicorn nis2_server.main:app --reload
```

Domyślnie:

* healthcheck: `GET http://127.0.0.1:8000/health`
* Swagger UI: `http://127.0.0.1:8000/docs`
* dashboard: `http://127.0.0.1:8000/` (lista agentów + niespełnione reguły)
* rejestracja agenta (instrukcja PowerShell): `http://127.0.0.1:8000/register`
* bootstrap PowerShell: `http://127.0.0.1:8000/register/bootstrap.ps1`
* pobieranie EXE agenta: `http://127.0.0.1:8000/downloads/nis2_agent_win.exe`

Po przyjęciu pierwszego raportu serwer tworzy katalog:

```text
server_data/
└── agents/
    └── <agent_id>/
        ├── index.json
        ├── config.json        # opcjonalna konfiguracja agenta
        └── reports/
            └── <timestamp>.json
```

---

## Uruchomienie serwera w Dockerze

W root projektu:

```bash
docker-compose up -d
```

Domyślnie serwis `nis2_server` będzie dostępny na `http://localhost:8000`, z wolumenami:

* `./server_data:/app/server_data`
* `./rules:/app/rules`

Katalog `downloads/` z EXE jest kopiowany do obrazu przy budowie.

---

## Agent – tryb jednorazowy (`once`)

W drugim terminalu (z aktywnym venv), nadal w root projektu:

```bash
python -m nis2_agent.main \
  --rules-dir rules \
  --log-dir logs \
  --server-url http://127.0.0.1:8000 \
  --agent-id test-agent-01 \
  --mode once
```

Agent:

* wykonuje skan lokalnego hosta,
* ładuje reguły z `rules/basic.yml`,
* ocenia reguły i loguje wyniki,
* wysyła raport do `nis2_server` pod `/api/v1/reports`.

Lokalnie zapisuje:

```text
logs/
├── agent.log
├── scan_<timestamp>.json
├── rules_<timestamp>.json
└── findings.jsonl      # tylko niespełnione reguły (JSONL)
```

---

## Agent – tryb cykliczny (`loop`) z configiem z serwera

Tryb `loop` powoduje, że agent:

1. (jeśli ma ustawiony `--server-url`) pobiera konfigurację z:

   * `GET /api/v1/agents/{agent_id}/config`
   * pola: `scan_interval_seconds` (domyślnie 21600 = 6h), `enabled` (bool),
2. jeśli `enabled == True` – robi skan + wysyłka raportu,
3. śpi `scan_interval_seconds` i powtarza.

Uruchomienie:

```bash
python -m nis2_agent.main \
  --rules-dir rules \
  --log-dir logs \
  --server-url http://127.0.0.1:8000 \
  --agent-id test-agent-01 \
  --mode loop
```

Jeżeli serwer nie zwróci configu, agent używa domyślnego interwału 6h.

---

## Windows EXE – build i nadpisywanie w `downloads/`

Na maszynie Windows (z repo `NIS2-COMPLIENCE-AS-CODE` i zainstalowanym PyInstallerem):

```bash
cd NIS2-COMPLIENCE-AS-CODE
pyinstaller --onefile -n nis2_agent_win --distpath downloads -m nis2_agent.main
```

To:

* buduje agenta jako pojedynczy plik exe,
* zapisuje go do `downloads/nis2_agent_win.exe`,
* przy kolejnym buildzie nadpisuje istniejący plik (zawsze aktualny binarek w `downloads/`).

Serwer zakłada, że EXE jest dostępny pod ścieżką:

```text
downloads/nis2_agent_win.exe
```

i serwuje go jako:

```text
GET /downloads/nis2_agent_win.exe
```

---

## Rejestracja agenta na Windows przez `/register`

Serwer udostępnia stronę ułatwiającą instalację agenta:

* `GET /register` – HTML z instrukcją i komendą PowerShell,
* `GET /register/bootstrap.ps1` – skrypt instalacyjny PowerShell.

Przykładowa komenda do uruchomienia na Windows (PowerShell jako Administrator):

```powershell
iwr http://<SERVER_HOST>:8000/register/bootstrap.ps1 -UseBasicParsing | iex
```

Skrypt:

1. ustala `ServerUrl` na adres serwera (z nagłówka żądania),
2. pobiera `nis2_agent_win.exe` z `/downloads/nis2_agent_win.exe`,
3. zapisuje go w `C:\Program Files\NIS2Agent\`,
4. rejestruje zadanie Harmonogramu Zadań `NIS2Agent`, które:

   * uruchamia EXE w trybie `--mode loop`,
   * ustawia `--server-url` na adres serwera,
   * ustawia `--agent-id` na `COMPUTERNAME`,
   * startuje raz i powtarza się co 6 godzin.

---

## API serwera – podstawowe endpointy

Przykładowe komendy `curl`:

Lista agentów:

```bash
curl http://127.0.0.1:8000/api/v1/agents
```

Podsumowanie ostatniego raportu:

```bash
curl http://127.0.0.1:8000/api/v1/agents/test-agent-01/latest
```

Pełny surowy JSON ostatniego raportu:

```bash
curl http://127.0.0.1:8000/api/v1/agents/test-agent-01/latest/raw
```

Konfiguracja agenta:

```bash
curl http://127.0.0.1:8000/api/v1/agents/test-agent-01/config
```

Pobranie EXE agenta:

```bash
curl -O http://127.0.0.1:8000/downloads/nis2_agent_win.exe
```