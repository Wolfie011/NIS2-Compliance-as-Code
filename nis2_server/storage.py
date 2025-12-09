from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .config import AGENTS_DIR
from .models import AgentReportCreate, AgentSummary, ReportSummary, RuleResultModel, AgentConfig


def _agent_dir(agent_id: str) -> Path:
    d = AGENTS_DIR / agent_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "reports").mkdir(parents=True, exist_ok=True)
    return d


def _index_path(agent_id: str) -> Path:
    return _agent_dir(agent_id) / "index.json"


def _load_index(agent_id: str) -> Dict:
    path = _index_path(agent_id)
    if not path.exists():
        return {"agent_id": agent_id, "reports": []}
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if "reports" not in data:
        data["reports"] = []
    return data


def _save_index(agent_id: str, data: Dict) -> None:
    path = _index_path(agent_id)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def save_report(report: AgentReportCreate) -> str:
    """
    Zapisuje raport agenta do pliku:
    server_data/agents/<agent_id>/reports/<timestamp>.json
    oraz aktualizuje index.json.
    Zwraca timestamp użyty w nazwie pliku.
    """
    agent_id = report.agent_id
    ts = dt.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")

    agent_dir = _agent_dir(agent_id)
    reports_dir = agent_dir / "reports"
    file_path = reports_dir / f"{ts}.json"

    payload = {
        "agent_id": agent_id,
        "received_at": ts,
        "scan": report.scan.model_dump(),
        "rules": [r.model_dump() for r in report.rules],
    }

    with file_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    # zaktualizuj index
    index = _load_index(agent_id)
    failed_count = sum(1 for r in report.rules if not r.passed)

    index_entry = {
        "report_timestamp": ts,
        "file": f"reports/{ts}.json",
        "hostname": report.scan.hostname,
        "failed_rules_count": failed_count,
    }

    index["reports"].append(index_entry)
    # sortuj rosnąco po timestamp na wszelki wypadek
    index["reports"].sort(key=lambda x: x["report_timestamp"])
    _save_index(agent_id, index)

    return ts


def list_agents() -> List[AgentSummary]:
    if not AGENTS_DIR.exists():
        return []

    summaries: List[AgentSummary] = []

    for entry in sorted(AGENTS_DIR.iterdir()):
        if not entry.is_dir():
            continue
        agent_id = entry.name
        index = _load_index(agent_id)
        reports = index.get("reports", [])
        if not reports:
            summaries.append(
                AgentSummary(
                    agent_id=agent_id,
                    last_report_at=None,
                    failed_rules_count=0,
                )
            )
            continue

        last = reports[-1]
        summaries.append(
            AgentSummary(
                agent_id=agent_id,
                last_report_at=last.get("report_timestamp"),
                failed_rules_count=last.get("failed_rules_count", 0),
            )
        )

    return summaries


def _load_latest_report_raw(agent_id: str) -> Optional[Dict]:
    index = _load_index(agent_id)
    reports = index.get("reports", [])
    if not reports:
        return None
    last = reports[-1]
    file_rel = last["file"]
    file_path = _agent_dir(agent_id) / file_rel
    if not file_path.exists():
        return None
    with file_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def get_latest_report_summary(agent_id: str) -> Optional[ReportSummary]:
    data = _load_latest_report_raw(agent_id)
    if not data:
        return None

    failed_rules = [
        RuleResultModel(**r)
        for r in data.get("rules", [])
        if not r.get("passed", False)
    ]

    return ReportSummary(
        agent_id=data["agent_id"],
        report_timestamp=data["received_at"],
        hostname=data["scan"].get("hostname", ""),
        failed_rules=failed_rules,
    )


def get_latest_raw_report(agent_id: str) -> Optional[Dict]:
    """
    Pełny surowy raport (scan + rules) – do debugowania lub dalszej analizy.
    """
    return _load_latest_report_raw(agent_id)


def _agent_config_path(agent_id: str) -> Path:
    return _agent_dir(agent_id) / "config.json"


def get_agent_config(agent_id: str) -> AgentConfig:
    """
    Zwraca konfigurację agenta.
    Na razie: jeśli nie istnieje osobny plik, zwracamy domyślną wartość.
    """
    path = _agent_config_path(agent_id)
    if not path.exists():
        # domyślna konfiguracja: skan co 6 godzin, włączony
        return AgentConfig(
            agent_id=agent_id,
            scan_interval_seconds=21600,
            enabled=True,
        )

    with path.open("r", encoding="utf-8") as f:
        raw = json.load(f)

    # Upewniamy się, że agent_id jest ustawiony
    raw.setdefault("agent_id", agent_id)

    return AgentConfig(**raw)