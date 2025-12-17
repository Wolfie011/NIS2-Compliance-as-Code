from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Dict, List, Optional

from .config import AGENTS_DIR
from .models import (
    AgentReportCreate,
    AgentSummary,
    ReportSummary,
    RuleResultModel,
    AgentConfig,
    ReportHistoryPoint,
    RuleTimeMeta,
    ReportSummaryEnriched,
    WhatIfResult,
    WhatIfRuleStatus,
)
from .rules_catalog import load_rules_catalog, get_framework_index


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


def _agent_config_path(agent_id: str) -> Path:
    return _agent_dir(agent_id) / "config.json"


def get_agent_config(agent_id: str) -> AgentConfig:
    """
    Zwraca konfigurację agenta.
    Jeśli brak config.json, zwraca domyślną konfigurację.
    """
    path = _agent_config_path(agent_id)
    if not path.exists():
        return AgentConfig(
            agent_id=agent_id,
            scan_interval_seconds=21600,
            enabled=True,
        )

    with path.open("r", encoding="utf-8") as f:
        raw = json.load(f)

    raw.setdefault("agent_id", agent_id)
    return AgentConfig(**raw)


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
    index["reports"].sort(key=lambda x: x["report_timestamp"])
    _save_index(agent_id, index)

    return ts


def _load_report_file(agent_id: str, file_rel: str) -> Optional[Dict]:
    file_path = _agent_dir(agent_id) / file_rel
    if not file_path.exists():
        return None
    with file_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _load_latest_report_raw(agent_id: str) -> Optional[Dict]:
    index = _load_index(agent_id)
    reports = index.get("reports", [])
    if not reports:
        return None
    last = reports[-1]
    return _load_report_file(agent_id, last["file"])


def _load_all_reports_raw(agent_id: str) -> List[Dict]:
    index = _load_index(agent_id)
    reports = index.get("reports", [])
    out: List[Dict] = []
    for entry in reports:
        data = _load_report_file(agent_id, entry["file"])
        if data:
            out.append(data)
    return out


def _severity_weight(severity: str) -> float:
    s = severity.lower()
    mapping = {
        "low": 1.0,
        "medium": 3.0,
        "high": 5.0,
        "critical": 8.0,
    }
    return mapping.get(s, 1.0)


def _criticality_factor(criticality: str) -> float:
    c = criticality.lower()
    mapping = {
        "low": 0.5,
        "normal": 1.0,
        "high": 1.5,
        "critical": 2.0,
    }
    return mapping.get(c, 1.0)


def compute_risk_for_report(report_dict: Dict, cfg: Optional[AgentConfig]) -> float:
    """
    Risk score zależny od:
    - severity reguły,
    - liczby frameworków przypiętych do reguły,
    - krytyczności assetu (z configu agenta).
    """
    if not report_dict:
        return 0.0

    rules = report_dict.get("rules", []) or []
    crit_factor = _criticality_factor(cfg.criticality if cfg else "normal")

    risk = 0.0
    for r in rules:
        if r.get("passed", False):
            continue
        sev = str(r.get("severity", "low"))
        sev_w = _severity_weight(sev)
        frameworks = r.get("frameworks") or []
        fw_factor = max(1, len(frameworks))
        risk += sev_w * fw_factor * crit_factor

    return risk


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
                    risk_score=0.0,
                )
            )
            continue

        last = reports[-1]
        last_raw = _load_report_file(agent_id, last["file"])
        cfg = get_agent_config(agent_id)
        risk = compute_risk_for_report(last_raw, cfg) if last_raw else 0.0

        summaries.append(
            AgentSummary(
                agent_id=agent_id,
                last_report_at=last.get("report_timestamp"),
                failed_rules_count=last.get("failed_rules_count", 0),
                risk_score=risk,
            )
        )

    return summaries


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


def compute_time_to_fix_meta(agent_id: str) -> Dict[str, RuleTimeMeta]:
    """
    Na podstawie historii raportów danego agenta liczy:
    - od którego raportu dana reguła jest w stanie FAIL (streak),
    - ile skanów z rzędu jest FAIL.

    Zwraca mapę rule_id -> RuleTimeMeta dla reguł, które
    są niespełnione w NAJNOWSZYM raporcie.
    """
    all_reports = _load_all_reports_raw(agent_id)
    if not all_reports:
        return {}

    last_status: Dict[str, bool] = {}
    failing_since_ts: Dict[str, str] = {}
    failing_scans_count: Dict[str, int] = {}

    for data in all_reports:
        ts = data.get("received_at")
        rules = data.get("rules", []) or []

        for r in rules:
            rid = r.get("rule_id")
            passed = bool(r.get("passed", False))
            prev = last_status.get(rid)

            if prev is None:
                if not passed:
                    failing_since_ts[rid] = ts
                    failing_scans_count[rid] = 1
            else:
                if not passed:
                    if prev:
                        failing_since_ts[rid] = ts
                        failing_scans_count[rid] = 1
                    else:
                        failing_scans_count[rid] = failing_scans_count.get(rid, 0) + 1
                else:
                    failing_since_ts.pop(rid, None)
                    failing_scans_count.pop(rid, None)

            last_status[rid] = passed

    latest = all_reports[-1]
    latest_ts = latest.get("received_at")
    meta: Dict[str, RuleTimeMeta] = {}

    for r in latest.get("rules", []) or []:
        rid = r.get("rule_id")
        if r.get("passed", False):
            continue
        since = failing_since_ts.get(rid, latest_ts)
        scans = failing_scans_count.get(rid, 1)
        meta[rid] = RuleTimeMeta(
            rule_id=rid,
            failing_since_report_timestamp=since,
            failing_scans=scans,
        )

    return meta


def get_latest_report_summary_enriched(agent_id: str) -> Optional[ReportSummaryEnriched]:
    base = get_latest_report_summary(agent_id)
    if not base:
        return None

    raw = _load_latest_report_raw(agent_id)
    cfg = get_agent_config(agent_id)
    risk = compute_risk_for_report(raw, cfg) if raw else 0.0
    meta_map = compute_time_to_fix_meta(agent_id)
    meta_list = list(meta_map.values())

    return ReportSummaryEnriched(
        agent_id=base.agent_id,
        report_timestamp=base.report_timestamp,
        hostname=base.hostname,
        failed_rules=base.failed_rules,
        failed_rules_meta=meta_list,
        risk_score=risk,
    )


def get_latest_raw_report(agent_id: str) -> Optional[Dict]:
    return _load_latest_report_raw(agent_id)


def get_report_history(agent_id: str, limit: int = 20) -> List[ReportHistoryPoint]:
    """
    Zwraca ostatnie 'limit' raportów jako punkty historyczne
    (z risk score).
    """
    index = _load_index(agent_id)
    reports = index.get("reports", [])
    if not reports:
        return []

    selected = reports[-limit:]

    history: List[ReportHistoryPoint] = []

    cfg = get_agent_config(agent_id)

    for entry in selected:
        data = _load_report_file(agent_id, entry["file"])
        if not data:
            continue
        rules = data.get("rules", []) or []
        total_rules = len(rules)
        failed_rules = sum(1 for r in rules if not r.get("passed", False))
        risk = compute_risk_for_report(data, cfg)

        history.append(
            ReportHistoryPoint(
                report_timestamp=data.get("received_at", entry["report_timestamp"]),
                hostname=data.get("scan", {}).get("hostname", ""),
                total_rules=total_rules,
                failed_rules=failed_rules,
                risk_score=risk,
            )
        )

    return history


def get_what_if(agent_id: str, framework: str) -> WhatIfResult:
    """
    What-if: dla danego agenta i frameworka (np. 'CIS:IG1', 'NIS2:art21')
    zwraca status wszystkich reguł oznaczonych tym frameworkiem:
    - passed / failed / not_implemented
    """
    rules = load_rules_catalog()
    fw_index = get_framework_index(rules)
    fw_rules = fw_index.get(framework, [])

    data = _load_latest_report_raw(agent_id)
    if not data:
        return WhatIfResult(
            agent_id=agent_id,
            framework=framework,
            total_rules=len(fw_rules),
            passed=0,
            failed=0,
            not_implemented=len(fw_rules),
            rules=[
                WhatIfRuleStatus(
                    id=r.id,
                    description=r.description,
                    severity=r.severity,
                    frameworks=r.frameworks,
                    status="not_implemented",
                )
                for r in fw_rules
            ],
        )

    rule_status_map: Dict[str, str] = {}
    for r in data.get("rules", []) or []:
        rid = r.get("rule_id")
        status = "passed" if r.get("passed", False) else "failed"
        rule_status_map[rid] = status

    out_rules: List[WhatIfRuleStatus] = []
    passed = failed = not_impl = 0

    for r in fw_rules:
        status = rule_status_map.get(r.id, "not_implemented")
        if status == "passed":
            passed += 1
        elif status == "failed":
            failed += 1
        else:
            not_impl += 1

        out_rules.append(
            WhatIfRuleStatus(
                id=r.id,
                description=r.description,
                severity=r.severity,
                frameworks=r.frameworks,
                status=status,
            )
        )

    return WhatIfResult(
        agent_id=agent_id,
        framework=framework,
        total_rules=len(fw_rules),
        passed=passed,
        failed=failed,
        not_implemented=not_impl,
        rules=out_rules,
    )