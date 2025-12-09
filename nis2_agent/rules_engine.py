from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


@dataclass
class Rule:
    id: str
    description: str
    severity: str
    condition: str
    tags: List[str]


@dataclass
class RuleResult:
    rule_id: str
    passed: bool
    severity: str
    description: str
    details: Optional[str]
    timestamp: str


class RulesEngine:
    def __init__(self, rules_dir: str = "rules") -> None:
        self.rules_dir = Path(rules_dir)
        self.rules: List[Rule] = []
        self._load_rules()

    def _load_rules(self) -> None:
        if not self.rules_dir.exists():
            return

        for path in sorted(self.rules_dir.glob("*.yml")):
            with path.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or []
            if not isinstance(data, list):
                continue
            for item in data:
                self.rules.append(
                    Rule(
                        id=item["id"],
                        description=item.get("description", ""),
                        severity=item.get("severity", "low"),
                        condition=item["condition"],
                        tags=item.get("tags", []),
                    )
                )

    def evaluate(self, data: Dict[str, Any]) -> List[RuleResult]:
        results: List[RuleResult] = []
        now = dt.datetime.utcnow().isoformat() + "Z"

        # Kontekst dla expresji: top-level pola + całe 'data'
        ctx: Dict[str, Any] = {"data": data}
        ctx.update(data)

        for rule in self.rules:
            try:
                passed = bool(eval(rule.condition, {"__builtins__": {}}, ctx))
                details = None
            except Exception as e:
                passed = False
                details = f"Rule evaluation error: {e}"

            results.append(
                RuleResult(
                    rule_id=rule.id,
                    passed=passed,
                    severity=rule.severity,
                    description=rule.description,
                    details=details,
                    timestamp=now,
                )
            )

        return results

    @staticmethod
    def serialize_result(result: RuleResult) -> Dict[str, Any]:
        return {
            "rule_id": result.rule_id,
            "passed": result.passed,
            "severity": result.severity,
            "description": result.description,
            "details": result.details,
            "timestamp": result.timestamp,
        }