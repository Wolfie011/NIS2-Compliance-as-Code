from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .logging_config import setup_logging
from .models import AgentReportCreate, AgentSummary, ReportSummary
from . import storage


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