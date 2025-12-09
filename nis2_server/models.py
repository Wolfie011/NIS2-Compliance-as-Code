from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ScanModel(BaseModel):
    hostname: str
    os: Dict[str, Any]
    network: Dict[str, Any]
    ssh: Dict[str, Any]


class RuleResultModel(BaseModel):
    rule_id: str
    passed: bool
    severity: str
    description: str
    details: Optional[str] = None
    timestamp: str


class AgentReportCreate(BaseModel):
    agent_id: str = Field(
        ...,
        description="Unikalny identyfikator agenta (np. hostname lub UUID).",
    )
    scan: ScanModel
    rules: List[RuleResultModel]


class AgentSummary(BaseModel):
    agent_id: str
    last_report_at: Optional[str] = None
    failed_rules_count: int = 0


class ReportSummary(BaseModel):
    agent_id: str
    report_timestamp: str
    hostname: str
    failed_rules: List[RuleResultModel]