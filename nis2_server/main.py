from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse

from .logging_config import setup_logging
from .models import AgentReportCreate, AgentSummary, ReportSummary, AgentConfig
from . import storage
from .config import DOWNLOADS_DIR


logger = setup_logging()

app = FastAPI(
    title="NIS2 Server",
    version="0.1.0",
    description="Minimalny serwer zbierający raporty NIS2 agentów.",
)

# CORS dla wygody w PoC – można zaostrzyć później
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", response_class=HTMLResponse, tags=["dashboard"])
def dashboard() -> str:
    """
    Prosty dashboard HTML:
    - lista agentów
    - po kliknięciu agenta: niespełnione reguły z ostatniego raportu
    """
    # Wstrzykniemy bazowy URL API jako relatywny
    return """
<!DOCTYPE html>
<html lang="pl">
<head>
  <meta charset="UTF-8">
  <title>NIS2 Dashboard</title>
  <style>
    body {
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      margin: 0;
      padding: 0;
      background: #f5f5f7;
      color: #222;
    }
    header {
      background: #111827;
      color: #f9fafb;
      padding: 1rem 1.5rem;
    }
    header h1 {
      margin: 0;
      font-size: 1.4rem;
    }
    main {
      padding: 1.5rem;
      display: grid;
      grid-template-columns: 1.1fr 2fr;
      gap: 1.5rem;
    }
    @media (max-width: 900px) {
      main {
        grid-template-columns: 1fr;
      }
    }
    .card {
      background: #ffffff;
      border-radius: 0.5rem;
      box-shadow: 0 1px 3px rgba(0,0,0,0.08);
      padding: 1rem 1.25rem;
    }
    .card h2 {
      margin-top: 0;
      font-size: 1.1rem;
      margin-bottom: 0.5rem;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 0.9rem;
    }
    th, td {
      padding: 0.4rem 0.5rem;
      border-bottom: 1px solid #e5e7eb;
      text-align: left;
    }
    th {
      background: #f3f4f6;
      font-weight: 600;
    }
    tr.clickable {
      cursor: pointer;
    }
    tr.clickable:hover {
      background: #f9fafb;
    }
    .badge {
      display: inline-flex;
      align-items: center;
      padding: 0.05rem 0.35rem;
      border-radius: 999px;
      font-size: 0.7rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.03em;
    }
    .badge-ok {
      background: #dcfce7;
      color: #166534;
    }
    .badge-failed {
      background: #fee2e2;
      color: #991b1b;
    }
    .badge-high {
      background: #fee2e2;
      color: #b91c1c;
    }
    .badge-medium {
      background: #fef3c7;
      color: #92400e;
    }
    .badge-low {
      background: #e0f2fe;
      color: #075985;
    }
    .muted {
      color: #6b7280;
      font-size: 0.8rem;
    }
    .error {
      color: #b91c1c;
      font-size: 0.85rem;
      margin-top: 0.25rem;
    }
    .pill {
      display: inline-block;
      font-size: 0.75rem;
      padding: 0.1rem 0.35rem;
      border-radius: 999px;
      background: #f3f4f6;
      color: #4b5563;
      margin-right: 0.15rem;
      margin-top: 0.1rem;
    }
    .section-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 0.4rem;
    }
    button {
      border-radius: 999px;
      border: 1px solid #d1d5db;
      padding: 0.2rem 0.7rem;
      font-size: 0.8rem;
      background: #ffffff;
      cursor: pointer;
    }
    button:hover {
      background: #f3f4f6;
    }
    #agents-error, #rules-error {
      display: none;
    }
  </style>
</head>
<body>
  <header>
    <h1>NIS2 – minimalny dashboard agentów</h1>
  </header>
  <main>
    <section class="card">
      <div class="section-header">
        <h2>Agentów</h2>
        <button onclick="loadAgents()">Odśwież</button>
      </div>
      <p class="muted">Kliknij agenta, aby zobaczyć niespełnione reguły z ostatniego raportu.</p>
      <div id="agents-error" class="error"></div>
      <table id="agents-table">
        <thead>
          <tr>
            <th>ID agenta</th>
            <th>Ostatni raport</th>
            <th>Niespełnione reguły</th>
          </tr>
        </thead>
        <tbody>
          <!-- wypełniane dynamicznie -->
        </tbody>
      </table>
    </section>

    <section class="card">
      <div class="section-header">
        <h2>Szczegóły agenta</h2>
        <span id="selected-agent" class="muted">Brak wybranego agenta</span>
      </div>
      <div id="rules-error" class="error"></div>
      <table id="rules-table">
        <thead>
          <tr>
            <th>Reguła</th>
            <th>Opis</th>
            <th>Poziom</th>
            <th>Znacznik czasu</th>
          </tr>
        </thead>
        <tbody>
          <!-- dynamicznie, tylko niespełnione -->
        </tbody>
      </table>
    </section>
  </main>

  <script>
    const apiBase = "";

    async function loadAgents() {
      const tbody = document.querySelector("#agents-table tbody");
      const errorBox = document.getElementById("agents-error");
      tbody.innerHTML = "";
      errorBox.style.display = "none";
      errorBox.textContent = "";

      try {
        const res = await fetch(apiBase + "/api/v1/agents");
        if (!res.ok) {
          throw new Error("HTTP " + res.status);
        }
        const list = await res.json();

        if (!Array.isArray(list) || list.length === 0) {
          const tr = document.createElement("tr");
          const td = document.createElement("td");
          td.colSpan = 3;
          td.className = "muted";
          td.textContent = "Brak agentów. Upewnij się, że agent wysłał co najmniej jeden raport.";
          tr.appendChild(td);
          tbody.appendChild(tr);
          return;
        }

        list.forEach(agent => {
          const tr = document.createElement("tr");
          tr.className = "clickable";
          tr.onclick = () => loadAgentDetails(agent.agent_id);

          const tdId = document.createElement("td");
          tdId.textContent = agent.agent_id;

          const tdLast = document.createElement("td");
          tdLast.textContent = agent.last_report_at || "-";

          const tdFailed = document.createElement("td");
          const span = document.createElement("span");
          if (agent.failed_rules_count && agent.failed_rules_count > 0) {
            span.className = "badge badge-failed";
            span.textContent = agent.failed_rules_count + " FAIL";
          } else {
            span.className = "badge badge-ok";
            span.textContent = "OK";
          }
          tdFailed.appendChild(span);

          tr.appendChild(tdId);
          tr.appendChild(tdLast);
          tr.appendChild(tdFailed);

          tbody.appendChild(tr);
        });
      } catch (err) {
        errorBox.style.display = "block";
        errorBox.textContent = "Błąd ładowania listy agentów: " + err;
      }
    }

    async function loadAgentDetails(agentId) {
      const tbody = document.querySelector("#rules-table tbody");
      const errorBox = document.getElementById("rules-error");
      const selected = document.getElementById("selected-agent");

      tbody.innerHTML = "";
      errorBox.style.display = "none";
      errorBox.textContent = "";
      selected.textContent = "Agent: " + agentId;

      try {
        const res = await fetch(apiBase + "/api/v1/agents/" + encodeURIComponent(agentId) + "/latest");
        if (!res.ok) {
          if (res.status === 404) {
            const tr = document.createElement("tr");
            const td = document.createElement("td");
            td.colSpan = 4;
            td.className = "muted";
            td.textContent = "Brak raportów dla tego agenta.";
            tr.appendChild(td);
            tbody.appendChild(tr);
            return;
          }
          throw new Error("HTTP " + res.status);
        }
        const summary = await res.json();
        const failed = summary.failed_rules || [];

        if (failed.length === 0) {
          const tr = document.createElement("tr");
          const td = document.createElement("td");
          td.colSpan = 4;
          td.className = "muted";
          td.textContent = "Brak niespełnionych reguł w ostatnim raporcie.";
          tr.appendChild(td);
          tbody.appendChild(tr);
          return;
        }

        failed.forEach(rule => {
          const tr = document.createElement("tr");

          const tdId = document.createElement("td");
          tdId.textContent = rule.rule_id;

          const tdDesc = document.createElement("td");
          const pDesc = document.createElement("div");
          pDesc.textContent = rule.description || "";
          tdDesc.appendChild(pDesc);

          if (rule.details) {
            const pDetails = document.createElement("div");
            pDetails.className = "muted";
            pDetails.textContent = rule.details;
            tdDesc.appendChild(pDetails);
          }

          const tdSev = document.createElement("td");
          const sevSpan = document.createElement("span");
          const sev = (rule.severity || "").toLowerCase();
          if (sev === "high") {
            sevSpan.className = "badge badge-high";
          } else if (sev === "medium") {
            sevSpan.className = "badge badge-medium";
          } else {
            sevSpan.className = "badge badge-low";
          }
          sevSpan.textContent = sev || "unknown";
          tdSev.appendChild(sevSpan);

          const tdTs = document.createElement("td");
          tdTs.textContent = rule.timestamp || "-";

          tr.appendChild(tdId);
          tr.appendChild(tdDesc);
          tr.appendChild(tdSev);
          tr.appendChild(tdTs);

          tbody.appendChild(tr);
        });

      } catch (err) {
        errorBox.style.display = "block";
        errorBox.textContent = "Błąd ładowania szczegółów agenta: " + err;
      }
    }

    // Auto-load na starcie
    window.addEventListener("DOMContentLoaded", () => {
      loadAgents();
    });
  </script>
</body>
</html>
"""



@app.get("/health", tags=["meta"])
def health() -> dict:
    return {"status": "ok"}


@app.post("/api/v1/reports", tags=["reports"])
def ingest_report(report: AgentReportCreate) -> dict:
    """
    Przyjmuje raport z agenta (scan + wyniki reguł),
    zapisuje go w storage plikowym, zwraca timestamp.
    """
    logger.info(
        "Received report from agent '%s', hostname='%s', rules=%d",
        report.agent_id,
        report.scan.hostname,
        len(report.rules),
    )
    ts = storage.save_report(report)
    logger.info("Report saved with timestamp %s", ts)
    return {"status": "ok", "timestamp": ts}


@app.get(
    "/api/v1/agents",
    response_model=list[AgentSummary],
    tags=["agents"],
)
def list_agents_endpoint():
    """
    Lista znanych agentów + info o ostatnim raporcie.
    """
    agents = storage.list_agents()
    return agents


@app.get(
    "/api/v1/agents/{agent_id}/latest",
    response_model=ReportSummary,
    tags=["agents"],
)
def get_latest(agent_id: str):
    """
    Podsumowanie ostatniego raportu: host, timestamp, niespełnione reguły.
    """
    summary = storage.get_latest_report_summary(agent_id)
    if not summary:
        raise HTTPException(status_code=404, detail="No reports for this agent")
    return summary


@app.get(
    "/api/v1/agents/{agent_id}/latest/raw",
    tags=["agents"],
)
def get_latest_raw(agent_id: str):
    """
    Pełny surowy JSON ostatniego raportu (scan + rules).
    """
    data = storage.get_latest_raw_report(agent_id)
    if not data:
        raise HTTPException(status_code=404, detail="No reports for this agent")
    return data


@app.get(
    "/api/v1/agents/{agent_id}/config",
    response_model=AgentConfig,
    tags=["agents"],
)
def get_agent_config(agent_id: str):
    """
    Konfiguracja agenta:
    - scan_interval_seconds: co ile sekund ma robić skan
    - enabled: czy skanowanie jest włączone
    """
    cfg = storage.get_agent_config(agent_id)
    return cfg


@app.get("/downloads/nis2_agent_win.exe", tags=["downloads"])
def download_agent_exe():
    """
    Zwraca skompilowanego agenta dla Windows.
    Plik powinien znajdować się w katalogu downloads/ w root projektu.
    """
    exe_path = DOWNLOADS_DIR / "nis2_agent_win.exe"
    if not exe_path.exists():
        raise HTTPException(status_code=404, detail="Agent EXE not found on server")
    return FileResponse(
        path=exe_path,
        media_type="application/vnd.microsoft.portable-executable",
        filename="nis2_agent_win.exe",
    )


@app.get(
    "/register/bootstrap.ps1",
    response_class=PlainTextResponse,
    tags=["register"],
)
def register_bootstrap(request: Request):
    """
    Skrypt instalacyjny PowerShell dla agenta.
    Do uruchomienia na Windowsie z uprawnieniami administratora.

    Przykład:
    iwr http://<server>/register/bootstrap.ps1 -UseBasicParsing | iex
    """
    base_url = str(request.base_url).rstrip("/")

    script = f"""\
# NIS2 agent bootstrap script
# UWAGA: uruchamiaj w PowerShell jako administrator

$ServerUrl = "{base_url}"
$AgentExeUrl = "$ServerUrl/downloads/nis2_agent_win.exe"
$InstallDir = "$env:ProgramFiles\\NIS2Agent"
$AgentExePath = Join-Path $InstallDir "nis2_agent_win.exe"
$AgentId = $env:COMPUTERNAME
$LogDir = Join-Path $env:ProgramData "NIS2Agent\\logs"

Write-Host "NIS2 Agent installer"
Write-Host "Server URL: $ServerUrl"
Write-Host "Agent ID  : $AgentId"
Write-Host ""

# 1. Utworzenie katalogu instalacyjnego
Write-Host "[1/4] Tworzenie katalogu instalacyjnego: $InstallDir"
New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
New-Item -ItemType Directory -Path $LogDir -Force | Out-Null

# 2. Pobranie EXE agenta
Write-Host "[2/4] Pobieranie agenta z $AgentExeUrl..."
Invoke-WebRequest -Uri $AgentExeUrl -OutFile $AgentExePath -UseBasicParsing

# 3. Rejestracja zadania w Harmonogramie Zadań (co 6h)
Write-Host "[3/4] Rejestracja zadania 'NIS2Agent' w Harmonogramie Zadań..."

$Action = New-ScheduledTaskAction -Execute $AgentExePath -Argument "--server-url `"$ServerUrl`" --mode loop --agent-id `"$AgentId`" --rules-dir rules --log-dir `"$LogDir`""

$StartTime = (Get-Date).AddMinutes(1)
$Trigger = New-ScheduledTaskTrigger -Once -At $StartTime
$Trigger.Repetition.Interval = New-TimeSpan -Hours 6
$Trigger.Repetition.Duration = New-TimeSpan -Days 365

Register-ScheduledTask -TaskName "NIS2Agent" -Action $Action -Trigger $Trigger -RunLevel Highest -User "SYSTEM" -Force

Write-Host "[4/4] Gotowe. Agent będzie uruchamiany co 6 godzin."
"""

    return script


@app.get("/register", response_class=HTMLResponse, tags=["register"])
def register_page(request: Request) -> str:
    base_url = str(request.base_url).rstrip("/")
    bootstrap_url = f"{base_url}/register/bootstrap.ps1"

    return f"""<!DOCTYPE html>
<html lang="pl">
<head>
  <meta charset="UTF-8">
  <title>Rejestracja agenta NIS2</title>
  <style>
    body {{
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #f5f5f7;
      margin: 0;
      padding: 0;
    }}
    .container {{
      max-width: 800px;
      margin: 2rem auto;
      background: #ffffff;
      border-radius: 0.5rem;
      padding: 1.5rem 2rem;
      box-shadow: 0 1px 3px rgba(0,0,0,0.1);
    }}
    h1 {{
      margin-top: 0;
      font-size: 1.4rem;
    }}
    code {{
      background: #111827;
      color: #e5e7eb;
      padding: 0.25rem 0.4rem;
      border-radius: 0.25rem;
      font-size: 0.9rem;
    }}
    pre {{
      background: #111827;
      color: #e5e7eb;
      padding: 0.75rem;
      border-radius: 0.4rem;
      overflow-x: auto;
      font-size: 0.85rem;
    }}
    .muted {{
      color: #6b7280;
      font-size: 0.85rem;
    }}
    ol {{
      padding-left: 1.2rem;
    }}
  </style>
</head>
<body>
  <div class="container">
    <h1>Rejestracja agenta NIS2 (Windows)</h1>
    <p class="muted">
      Aby automatycznie zainstalować i zarejestrować agenta na tym hoście (jako zadanie w Harmonogramie Zadań),
      uruchom poniższą komendę w <strong>PowerShell z uprawnieniami administratora</strong>:
    </p>
    <pre>iwr {bootstrap_url} -UseBasicParsing | iex</pre>

    <p>
      Skrypt:
    </p>
    <ol>
      <li>pobierze <code>nis2_agent_win.exe</code> z serwera,</li>
      <li>zainstaluje go w <code>C:\\Program Files\\NIS2Agent</code>,</li>
      <li>zarejestruje zadanie <code>NIS2Agent</code> uruchamiane co 6 godzin,</li>
      <li>agent będzie łączył się z serwerem pod adresem: <code>{base_url}</code>.</li>
    </ol>

    <p class="muted">
      Upewnij się, że firewall na tym hoście pozwala na połączenie HTTP do serwera.
    </p>
  </div>
</body>
</html>
"""
