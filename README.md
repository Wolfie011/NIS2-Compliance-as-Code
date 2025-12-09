````markdown
# NIS2-COMPLIENCE-AS-CODE

Minimalny PoC systemu do zbierania danych o infrastrukturze i oceny podstawowych reguł bezpieczeństwa pod NIS2:

- **nis2_agent** – lokalny agent:
  - skanuje system (OS, otwarte porty TCP, wybrane opcje SSH),
  - ocenia wynik skanu względem reguł zapisanych w YAML,
  - loguje wyniki lokalnie,
  - opcjonalnie wysyła raport do serwera HTTP.
- **nis2_server** – prosty serwer:
  - przyjmuje raporty z agentów,
  - zapisuje je w strukturze plikowej,
  - udostępnia API do przeglądania agentów i ich ostatnich wyników.

Projekt jest celowo prosty – jako baza pod dalszy rozwój.

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
├── logs/                # tworzone/autouzupełniane przez agenta (niekonieczne w repo)
├── server_data/         # tworzone przez serwer (niekonieczne w repo)
├── requirements-agent.txt
├── requirements-server.txt
└── requirements.txt
````

Katalogi `logs/` i `server_data/` warto dodać do `.gitignore`.

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

## Uruchomienie serwera

W root projektu:

```bash
uvicorn nis2_server.main:app --reload
```

Domyślnie:

* healthcheck: `GET http://127.0.0.1:8000/health`
* swagger UI: `http://127.0.0.1:8000/docs`

Po przyjęciu pierwszego raportu serwer tworzy katalog:

```text
server_data/
└── agents/
    └── <agent_id>/
        ├── index.json
        └── reports/
            └── <timestamp>.json
```

---

## Uruchomienie agenta

W drugim terminalu (z aktywnym venv), nadal w root projektu:

```bash
python -m nis2_agent.main \
  --rules-dir rules \
  --log-dir logs \
  --server-url http://127.0.0.1:8000 \
  --agent-id test-agent-01
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

---

## Następne kroki (do dalszego rozwoju)

* rozbudowa skanera (więcej collectorów: użytkownicy, backupy, konfiguracje usług),
* rozszerzenie DSL reguł (bezpośrednie parsowanie, bez `eval`),
* auth + TLS między agentem a serwerem,
* prosty frontend (dashboard) nad API serwera,
* centralne wersjonowanie paczek reguł („policy packs” dla różnych typów organizacji).

```
::contentReference[oaicite:0]{index=0}
```
