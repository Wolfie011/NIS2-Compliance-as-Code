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
    tags: Optional[List[str]] = None
    frameworks: Optional[List[str]] = None
    details: Optional[str] = None
    timestamp: str


class AgentReportCreate(BaseModel):
    agent_id: str = Field(
        ...,
        description="Unikalny identyfikator agenta (np. hostname lub UUID).",
    )
    scan: ScanModel
    rules: List[RuleResultModel]


class RuleDefinition(BaseModel):
    id: str
    description: str
    severity: str
    tags: List[str] = Field(default_factory=list)
    frameworks: List[str] = Field(default_factory=list)


class AgentSummary(BaseModel):
    agent_id: str
    last_report_at: Optional[str] = None
    failed_rules_count: int = 0
    risk_score: float = 0.0


class ReportSummary(BaseModel):
    agent_id: str
    report_timestamp: str
    hostname: str
    failed_rules: List[RuleResultModel]


class AgentConfig(BaseModel):
    agent_id: str
    scan_interval_seconds: int = Field(
        21600,
        description="Częstotliwość skanu w sekundach (domyślnie 6h).",
    )
    enabled: bool = Field(
        True,
        description="Czy agent ma wykonywać skany.",
    )
    criticality: str = Field(
        "normal",
        description="Krytyczność assetu: low|normal|high|critical (wpływa na risk score).",
    )
    asset_tags: List[str] = Field(
        default_factory=list,
        description="Tagi assetu, np. ['DC', 'HIS', 'DB'].",
    )


class ReportHistoryPoint(BaseModel):
    report_timestamp: str
    hostname: str
    total_rules: int
    failed_rules: int
    risk_score: float


class RuleTimeMeta(BaseModel):
    rule_id: str
    failing_since_report_timestamp: str
    failing_scans: int


class ReportSummaryEnriched(BaseModel):
    agent_id: str
    report_timestamp: str
    hostname: str
    failed_rules: List[RuleResultModel]
    failed_rules_meta: List[RuleTimeMeta]
    risk_score: float


class WhatIfRuleStatus(BaseModel):
    id: str
    description: str
    severity: str
    frameworks: List[str] = Field(default_factory=list)
    status: str  # "passed" | "failed" | "not_implemented"


class WhatIfResult(BaseModel):
    agent_id: str
    framework: str
    total_rules: int
    passed: int
    failed: int
    not_implemented: int
    rules: List[WhatIfRuleStatus]