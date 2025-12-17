from __future__ import annotations

import hashlib
import json

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    FileResponse,
)
import yaml

from .logging_config import setup_logging
from .models import (
    AgentReportCreate,
    AgentSummary,
    ReportSummary,
    AgentConfig,
    ReportHistoryPoint,
    ReportSummaryEnriched,
    RuleDefinition,
    WhatIfResult,
)
from . import storage
from .config import DOWNLOADS_DIR, BASE_DIR, PUBLIC_BASE_URL
from .rules_catalog import load_rules_catalog, get_framework_index


logger = setup_logging()

app = FastAPI(
    title="NIS2 Server",
    version="0.3.0",
    description=(
        "Minimalny serwer zbierający raporty NIS2 agentów "
        "(multi-framework, risk score, what-if)."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _get_base_url(request: Request) -> str:
    """
    Zwraca bazowy publiczny URL serwera używany w bootstrapie /register.
    Jeśli ustawiono PUBLIC_BASE_URL w ENV, używa go.
    W przeciwnym razie bazuje na request.base_url.
    """
    if PUBLIC_BASE_URL:
        return PUBLIC_BASE_URL.rstrip("/")
    return str(request.base_url).rstrip("/")


@app.get("/health", tags=["meta"])
def health() -> dict:
    return {"status": "ok"}


@app.post("/api/v1/reports", tags=["reports"])
def ingest_report(report: AgentReportCreate) -> dict:
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
    return storage.list_agents()


@app.get(
    "/api/v1/agents/{agent_id}/latest",
    response_model=ReportSummary,
    tags=["agents"],
)
def get_latest(agent_id: str):
    summary = storage.get_latest_report_summary(agent_id)
    if not summary:
        raise HTTPException(status_code=404, detail="No reports for this agent")
    return summary


@app.get(
    "/api/v1/agents/{agent_id}/latest/enriched",
    response_model=ReportSummaryEnriched,
    tags=["agents"],
)
def get_latest_enriched(agent_id: str):
    summary = storage.get_latest_report_summary_enriched(agent_id)
    if not summary:
        raise HTTPException(status_code=404, detail="No reports for this agent")
    return summary


@app.get(
    "/api/v1/agents/{agent_id}/latest/raw",
    tags=["agents"],
)
def get_latest_raw(agent_id: str):
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
    return storage.get_agent_config(agent_id)


@app.get(
    "/api/v1/agents/{agent_id}/history",
    response_model=list[ReportHistoryPoint],
    tags=["agents"],
)
def get_agent_history(agent_id: str, limit: int = 20):
    return storage.get_report_history(agent_id, limit=limit)


@app.get(
    "/api/v1/agents/{agent_id}/what-if",
    response_model=WhatIfResult,
    tags=["rules"],
)
def what_if(agent_id: str, framework: str):
    return storage.get_what_if(agent_id, framework)


@app.get(
    "/api/v1/rules",
    response_model=list[RuleDefinition],
    tags=["rules"],
)
def list_rules():
    return load_rules_catalog()


@app.get("/api/v1/frameworks", tags=["rules"])
def list_frameworks():
    rules = load_rules_catalog()
    index = get_framework_index(rules)
    result = [
        {"framework": fw, "rules_count": len(rs)}
        for fw, rs in sorted(index.items(), key=lambda x: x[0])
    ]
    return result


@app.get(
    "/api/v1/frameworks/{framework}/rules",
    response_model=list[RuleDefinition],
    tags=["rules"],
)
def list_framework_rules(framework: str):
    rules = load_rules_catalog()
    index = get_framework_index(rules)
    return index.get(framework, [])


@app.get("/downloads/nis2_agent_win.exe", tags=["downloads"])
def download_agent_exe():
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
    base_url = _get_base_url(request)

    script = f"""\
# NIS2 agent bootstrap script
# UWAGA: uruchamiaj w PowerShell jako administrator

$ServerUrl = "{base_url}"
$AgentExeUrl = "$ServerUrl/downloads/nis2_agent_win.exe"
$InstallDir = "$env:ProgramFiles\\NIS2Agent"
$AgentExePath = Join-Path $InstallDir "nis2_agent_win.exe"
$AgentId = $env:COMPUTERNAME

Write-Host "NIS2 Agent installer"
Write-Host "Server URL: $ServerUrl"
Write-Host "Agent ID  : $AgentId"
Write-Host ""

Write-Host "[1/4] Tworzenie katalogu instalacyjnego: $InstallDir"
New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null

Write-Host "[2/4] Pobieranie agenta z $AgentExeUrl..."
Invoke-WebRequest -Uri $AgentExeUrl -OutFile $AgentExePath -UseBasicParsing

Write-Host "[3/4] Rejestracja zadania 'NIS2Agent' w Harmonogramie Zadań..."

$Action = New-ScheduledTaskAction -Execute $AgentExePath -Argument "--server-url `"$ServerUrl`" --mode loop --agent-id `"$AgentId`" --rules-source remote --rules-dir rules --log-dir logs"

$Trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Hours 6) -RepetitionDuration ([TimeSpan]::MaxValue)

Register-ScheduledTask -TaskName "NIS2Agent" -Action $Action -Trigger $Trigger -RunLevel Highest -User "SYSTEM" -Force

Write-Host "[4/4] Gotowe. Agent będzie uruchamiany co 6 godzin."
"""
    return script


@app.get("/register", response_class=HTMLResponse, tags=["register"])
def register_page(request: Request) -> str:
    base_url = _get_base_url(request)
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
      <li>zainstaluje go w <code>C:\\\\Program Files\\\\NIS2Agent</code>,</li>
      <li>zarejestruje zadanie <code>NIS2Agent</code> uruchamiane co 6 godzin,</li>
      <li>agent będzie łączył się z serwerem pod adresem: <code>{base_url}</code>.</li>
    </ol>

    <p class="muted">
      Upewnij się, że firewall na tym hoście pozwala na połączenie HTTP/HTTPS do serwera.
    </p>
  </div>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse, tags=["dashboard"])
def dashboard() -> str:
    """
    Dashboard HTML:
    - lista agentów z risk score
    - niespełnione reguły + time-to-fix
    - historia skanów (trend risk score)
    - what-if dla wybranego frameworka
    """
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
      grid-template-columns: 1.1fr 2.6fr;
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
    .badge-risk-low {
      background: #dcfce7;
      color: #166534;
    }
    .badge-risk-med {
      background: #fef3c7;
      color: #92400e;
    }
    .badge-risk-high {
      background: #fee2e2;
      color: #b91c1c;
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
      gap: 0.6rem;
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
    #agents-error, #rules-error, #history-error, #whatif-error {
      display: none;
    }
    .tabs {
      display: flex;
      gap: 0.5rem;
      margin-bottom: 0.5rem;
      flex-wrap: wrap;
    }
    .tab-btn {
      padding: 0.2rem 0.7rem;
      border-radius: 999px;
      border: 1px solid #d1d5db;
      background: #ffffff;
      cursor: pointer;
      font-size: 0.8rem;
    }
    .tab-btn.active {
      background: #111827;
      color: #f9fafb;
      border-color: #111827;
    }
    .tab-content {
      display: none;
    }
    .tab-content.active {
      display: block;
    }
    #history-chart {
      width: 100%;
      height: 120px;
    }
    .status-badge {
      display: inline-flex;
      align-items: center;
      padding: 0.05rem 0.35rem;
      border-radius: 999px;
      font-size: 0.7rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.03em;
    }
    .status-passed {
      background: #dcfce7;
      color: #166534;
    }
    .status-failed {
      background: #fee2e2;
      color: #b91c1c;
    }
    .status-not-implemented {
      background: #e5e7eb;
      color: #374151;
    }
    select {
      font-size: 0.8rem;
      padding: 0.2rem 0.4rem;
      border-radius: 999px;
      border: 1px solid #d1d5db;
      background: #fff;
    }
  </style>
</head>
<body>
  <header>
    <h1>NIS2 – dashboard agentów</h1>
  </header>
  <main>
    <section class="card">
      <div class="section-header">
        <h2>Agenci</h2>
        <button onclick="loadAgents()">Odśwież</button>
      </div>
      <p class="muted">Kliknij agenta, aby zobaczyć niespełnione reguły, historię i symulację what-if.</p>
      <div id="agents-error" class="error"></div>
      <table id="agents-table">
        <thead>
          <tr>
            <th>ID agenta</th>
            <th>Ostatni raport</th>
            <th>Niespełnione reguły</th>
            <th>Risk score</th>
          </tr>
        </thead>
        <tbody>
        </tbody>
      </table>
    </section>

    <section class="card">
      <div class="section-header">
        <div>
          <h2>Szczegóły agenta</h2>
          <span id="selected-agent" class="muted">Brak wybranego agenta</span>
        </div>
        <div id="agent-risk" class="muted">Risk: -</div>
      </div>

      <div class="tabs">
        <button class="tab-btn active" data-tab="rules-tab" onclick="switchTab('rules-tab')">Niespełnione reguły</button>
        <button class="tab-btn" data-tab="history-tab" onclick="switchTab('history-tab')">Historia</button>
        <button class="tab-btn" data-tab="whatif-tab" onclick="switchTab('whatif-tab')">What-if / Frameworks</button>
      </div>

      <div id="rules-error" class="error"></div>
      <div id="history-error" class="error"></div>
      <div id="whatif-error" class="error"></div>

      <div id="rules-tab" class="tab-content active">
        <table id="rules-table">
          <thead>
            <tr>
              <th>Reguła</th>
              <th>Opis</th>
              <th>Poziom</th>
              <th>Frameworki</th>
              <th>Failing od</th>
            </tr>
          </thead>
          <tbody>
          </tbody>
        </table>
      </div>

      <div id="history-tab" class="tab-content">
        <svg id="history-chart"></svg>
        <table id="history-table">
          <thead>
            <tr>
              <th>Raport</th>
              <th>Niespełnione / Wszystkie</th>
              <th>Risk</th>
            </tr>
          </thead>
          <tbody>
          </tbody>
        </table>
      </div>

      <div id="whatif-tab" class="tab-content">
        <div class="section-header" style="margin-bottom:0.5rem;">
          <span class="muted">Wybierz framework:</span>
          <select id="framework-select" onchange="onFrameworkChange()">
            <option value="">-- wybierz --</option>
          </select>
        </div>
        <p id="whatif-summary" class="muted"></p>
        <table id="whatif-table">
          <thead>
            <tr>
              <th>Reguła</th>
              <th>Severity</th>
              <th>Status</th>
              <th>Frameworki</th>
            </tr>
          </thead>
          <tbody></tbody>
        </table>
      </div>
    </section>
  </main>

  <script>
    const apiBase = "";
    let selectedAgentId = null;
    let frameworksCache = [];

    function switchTab(tabId) {
      document.querySelectorAll(".tab-btn").forEach(btn => {
        btn.classList.toggle("active", btn.dataset.tab === tabId);
      });
      document.querySelectorAll(".tab-content").forEach(div => {
        div.classList.toggle("active", div.id === tabId);
      });
    }

    function riskClass(score) {
      if (score <= 0.0) return "badge-risk-low";
      if (score < 50) return "badge-risk-med";
      return "badge-risk-high";
    }

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
          td.colSpan = 4;
          td.className = "muted";
          td.textContent = "Brak agentów. Upewnij się, że agent wysłał co najmniej jeden raport.";
          tr.appendChild(td);
          tbody.appendChild(tr);
          return;
        }

        list.forEach(agent => {
          const tr = document.createElement("tr");
          tr.className = "clickable";
          tr.onclick = () => loadAgent(agent.agent_id);

          const tdId = document.createElement("td");
          tdId.textContent = agent.agent_id;

          const tdLast = document.createElement("td");
          tdLast.textContent = agent.last_report_at || "-";

          const tdFailed = document.createElement("td");
          const spanFailed = document.createElement("span");
          if (agent.failed_rules_count && agent.failed_rules_count > 0) {
            spanFailed.className = "badge badge-failed";
            spanFailed.textContent = agent.failed_rules_count + " FAIL";
          } else {
            spanFailed.className = "badge badge-ok";
            spanFailed.textContent = "OK";
          }
          tdFailed.appendChild(spanFailed);

          const tdRisk = document.createElement("td");
          const spanRisk = document.createElement("span");
          const risk = agent.risk_score || 0;
          spanRisk.className = "badge " + riskClass(risk);
          spanRisk.textContent = risk.toFixed(1);
          tdRisk.appendChild(spanRisk);

          tr.appendChild(tdId);
          tr.appendChild(tdLast);
          tr.appendChild(tdFailed);
          tr.appendChild(tdRisk);

          tbody.appendChild(tr);
        });
      } catch (err) {
        errorBox.style.display = "block";
        errorBox.textContent = "Błąd ładowania listy agentów: " + err;
      }
    }

    async function loadAgent(agentId) {
      selectedAgentId = agentId;
      const selected = document.getElementById("selected-agent");
      selected.textContent = "Agent: " + agentId;

      await Promise.all([
        loadAgentDetails(agentId),
        loadAgentHistory(agentId),
        ensureFrameworksLoaded(),
      ]);
    }

    async function loadAgentDetails(agentId) {
      const tbody = document.querySelector("#rules-table tbody");
      const errorBox = document.getElementById("rules-error");
      const riskBox = document.getElementById("agent-risk");

      tbody.innerHTML = "";
      errorBox.style.display = "none";
      errorBox.textContent = "";
      riskBox.textContent = "Risk: -";

      try {
        const res = await fetch(apiBase + "/api/v1/agents/" + encodeURIComponent(agentId) + "/latest/enriched");
        if (!res.ok) {
          if (res.status === 404) {
            const tr = document.createElement("tr");
            const td = document.createElement("td");
            td.colSpan = 5;
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
        const meta = summary.failed_rules_meta || [];
        const metaMap = new Map(meta.map(m => [m.rule_id, m]));

        const risk = summary.risk_score || 0;
        riskBox.textContent = "Risk: " + risk.toFixed(1);
        riskBox.className = "badge " + riskClass(risk);

        if (failed.length === 0) {
          const tr = document.createElement("tr");
          const td = document.createElement("td");
          td.colSpan = 5;
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
          if (sev === "high" || sev === "critical") {
            sevSpan.className = "badge badge-high";
          } else if (sev === "medium") {
            sevSpan.className = "badge badge-medium";
          } else {
            sevSpan.className = "badge badge-low";
          }
          sevSpan.textContent = sev || "unknown";
          tdSev.appendChild(sevSpan);

          const tdFw = document.createElement("td");
          const frameworks = rule.frameworks || [];
          if (frameworks.length) {
            frameworks.forEach(fw => {
              const spanFw = document.createElement("span");
              spanFw.className = "pill";
              spanFw.textContent = fw;
              tdFw.appendChild(spanFw);
            });
          } else {
            const spanFw = document.createElement("span");
            spanFw.className = "muted";
            spanFw.textContent = "-";
            tdFw.appendChild(spanFw);
          }

          const tdSince = document.createElement("td");
          const m = metaMap.get(rule.rule_id);
          if (m) {
            tdSince.textContent = m.failing_since_report_timestamp + " (" + m.failing_scans + " skanów)";
          } else {
            tdSince.textContent = rule.timestamp || "-";
          }

          tr.appendChild(tdId);
          tr.appendChild(tdDesc);
          tr.appendChild(tdSev);
          tr.appendChild(tdFw);
          tr.appendChild(tdSince);

          tbody.appendChild(tr);
        });

      } catch (err) {
        errorBox.style.display = "block";
        errorBox.textContent = "Błąd ładowania szczegółów agenta: " + err;
      }
    }

    async function loadAgentHistory(agentId) {
      const tbody = document.querySelector("#history-table tbody");
      const errorBox = document.getElementById("history-error");
      const svg = document.getElementById("history-chart");

      tbody.innerHTML = "";
      errorBox.style.display = "none";
      errorBox.textContent = "";
      svg.innerHTML = "";

      try {
        const res = await fetch(apiBase + "/api/v1/agents/" + encodeURIComponent(agentId) + "/history?limit=20");
        if (!res.ok) {
          throw new Error("HTTP " + res.status);
        }
        const history = await res.json();

        if (!Array.isArray(history) || history.length === 0) {
          const tr = document.createElement("tr");
          const td = document.createElement("td");
          td.colSpan = 3;
          td.className = "muted";
          td.textContent = "Brak historii raportów dla tego agenta.";
          tr.appendChild(td);
          tbody.appendChild(tr);
          return;
        }

        history.forEach(point => {
          const tr = document.createElement("tr");

          const tdTs = document.createElement("td");
          tdTs.textContent = point.report_timestamp;

          const tdCounts = document.createElement("td");
          tdCounts.textContent = point.failed_rules + " / " + point.total_rules;

          const tdRisk = document.createElement("td");
          const spanRisk = document.createElement("span");
          const risk = point.risk_score || 0;
          spanRisk.className = "badge " + riskClass(risk);
          spanRisk.textContent = risk.toFixed(1);
          tdRisk.appendChild(spanRisk);

          tr.appendChild(tdTs);
          tr.appendChild(tdCounts);
          tr.appendChild(tdRisk);
          tbody.appendChild(tr);
        });

        const w = svg.clientWidth || 600;
        const h = svg.clientHeight || 120;
        const padding = 10;

        const maxRisk = history.reduce((max, p) => Math.max(max, p.risk_score || 0), 0) || 1;
        const stepX = (w - 2 * padding) / Math.max(history.length - 1, 1);

        let path = "";
        history.forEach((p, idx) => {
          const x = padding + idx * stepX;
          const y = h - padding - ((p.risk_score || 0) / maxRisk) * (h - 2 * padding);
          path += (idx === 0 ? "M" : " L") + x + " " + y;
        });

        svg.setAttribute("viewBox", `0 0 ${w} ${h}`);

        const axis = document.createElementNS("http://www.w3.org/2000/svg", "line");
        axis.setAttribute("x1", padding);
        axis.setAttribute("y1", h - padding);
        axis.setAttribute("x2", w - padding);
        axis.setAttribute("y2", h - padding);
        axis.setAttribute("stroke", "#d1d5db");
        axis.setAttribute("stroke-width", "1");
        svg.appendChild(axis);

        const pathEl = document.createElementNS("http://www.w3.org/2000/svg", "path");
        pathEl.setAttribute("d", path);
        pathEl.setAttribute("fill", "none");
        pathEl.setAttribute("stroke", "#111827");
        pathEl.setAttribute("stroke-width", "1.5");
        svg.appendChild(pathEl);

      } catch (err) {
        errorBox.style.display = "block";
        errorBox.textContent = "Błąd ładowania historii agenta: " + err;
      }
    }

    async function ensureFrameworksLoaded() {
      if (frameworksCache.length > 0) return;

      try {
        const res = await fetch(apiBase + "/api/v1/frameworks");
        if (!res.ok) {
          throw new Error("HTTP " + res.status);
        }
        const list = await res.json();
        frameworksCache = list || [];
        const select = document.getElementById("framework-select");
        frameworksCache.forEach(item => {
          const opt = document.createElement("option");
          opt.value = item.framework;
          opt.textContent = item.framework + " (" + item.rules_count + ")";
          select.appendChild(opt);
        });
      } catch (err) {
        const errorBox = document.getElementById("whatif-error");
        errorBox.style.display = "block";
        errorBox.textContent = "Błąd ładowania frameworków: " + err;
      }
    }

    function onFrameworkChange() {
      const select = document.getElementById("framework-select");
      const fw = select.value;
      const summary = document.getElementById("whatif-summary");
      const tbody = document.querySelector("#whatif-table tbody");
      const errorBox = document.getElementById("whatif-error");

      summary.textContent = "";
      tbody.innerHTML = "";
      errorBox.style.display = "none";
      errorBox.textContent = "";

      if (!selectedAgentId || !fw) {
        return;
      }
      loadWhatIf(selectedAgentId, fw);
    }

    async function loadWhatIf(agentId, framework) {
      const summary = document.getElementById("whatif-summary");
      const tbody = document.querySelector("#whatif-table tbody");
      const errorBox = document.getElementById("whatif-error");

      tbody.innerHTML = "";
      errorBox.style.display = "none";
      errorBox.textContent = "";
      summary.textContent = "Ładowanie what-if dla " + framework + "...";

      try {
        const res = await fetch(
          apiBase + "/api/v1/agents/" + encodeURIComponent(agentId) +
          "/what-if?framework=" + encodeURIComponent(framework)
        );
        if (!res.ok) {
          throw new Error("HTTP " + res.status);
        }
        const data = await res.json();

        summary.textContent =
          "Framework " + data.framework +
          ": passed=" + data.passed +
          ", failed=" + data.failed +
          ", not implemented=" + data.not_implemented +
          " (łącznie " + data.total_rules + " reguł).";

        if (!Array.isArray(data.rules) || data.rules.length === 0) {
          const tr = document.createElement("tr");
          const td = document.createElement("td");
          td.colSpan = 4;
          td.className = "muted";
          td.textContent = "Brak reguł powiązanych z tym frameworkiem.";
          tr.appendChild(td);
          tbody.appendChild(tr);
          return;
        }

        data.rules.forEach(r => {
          const tr = document.createElement("tr");

          const tdId = document.createElement("td");
          tdId.textContent = r.id;

          const tdSev = document.createElement("td");
          const spanSev = document.createElement("span");
          const sev = (r.severity || "").toLowerCase();
          if (sev === "high" || sev === "critical") {
            spanSev.className = "badge badge-high";
          } else if (sev === "medium") {
            spanSev.className = "badge badge-medium";
          } else {
            spanSev.className = "badge badge-low";
          }
          spanSev.textContent = sev || "unknown";
          tdSev.appendChild(spanSev);

          const tdStatus = document.createElement("td");
          const spanStatus = document.createElement("span");
          const status = r.status || "not_implemented";
          if (status === "passed") spanStatus.className = "status-badge status-passed";
          else if (status === "failed") spanStatus.className = "status-badge status-failed";
          else spanStatus.className = "status-badge status-not-implemented";
          spanStatus.textContent = status;
          tdStatus.appendChild(spanStatus);

          const tdFw = document.createElement("td");
          const frameworks = r.frameworks || [];
          if (frameworks.length) {
            frameworks.forEach(fw => {
              const spanFw = document.createElement("span");
              spanFw.className = "pill";
              spanFw.textContent = fw;
              tdFw.appendChild(spanFw);
            });
          } else {
            const spanFw = document.createElement("span");
            spanFw.className = "muted";
            spanFw.textContent = "-";
            tdFw.appendChild(spanFw);
          }

          tr.appendChild(tdId);
          tr.appendChild(tdSev);
          tr.appendChild(tdStatus);
          tr.appendChild(tdFw);

          tbody.appendChild(tr);
        });

      } catch (err) {
        summary.textContent = "";
        errorBox.style.display = "block";
        errorBox.textContent = "Błąd ładowania what-if: " + err;
      }
    }

    window.addEventListener("DOMContentLoaded", () => {
      loadAgents();
      ensureFrameworksLoaded();
    });
  </script>
</body>
</html>
"""


@app.get("/api/v1/rules/bundle", tags=["rules"])
def get_rules_bundle():
    """
    Zwraca komplet reguł dla agenta:
    - version: hash reguł (do porównywania po stronie agenta)
    - rules: lista słowników z polami id/description/severity/condition/tags/frameworks
    """
    rules_dir = BASE_DIR / "rules"

    all_rules: list[dict] = []
    if rules_dir.exists():
        for path in sorted(rules_dir.glob("*.yml")):
            data = path.read_text(encoding="utf-8")
            parsed = yaml.safe_load(data) or []
            if isinstance(parsed, list):
                all_rules.extend(parsed)

    raw_bytes = json.dumps(
        all_rules,
        sort_keys=True,
        ensure_ascii=False,
    ).encode("utf-8")
    version = hashlib.sha256(raw_bytes).hexdigest()

    return JSONResponse(
        content={
            "version": version,
            "rules": all_rules,
        }
    )