from __future__ import annotations

from pathlib import Path
from typing import Dict, List

import yaml

from .config import BASE_DIR
from .models import RuleDefinition

RULES_DIR = BASE_DIR / "rules"


def load_rules_catalog() -> List[RuleDefinition]:
    rules: List[RuleDefinition] = []
    if not RULES_DIR.exists():
        return rules

    for path in sorted(RULES_DIR.glob("*.yml")):
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or []
        if not isinstance(data, list):
            continue
        for item in data:
            rules.append(
                RuleDefinition(
                    id=item["id"],
                    description=item.get("description", ""),
                    severity=item.get("severity", "low"),
                    tags=(item.get("tags") or []),
                    frameworks=(item.get("frameworks") or []),
                )
            )
    return rules


def get_framework_index(rules: List[RuleDefinition]) -> Dict[str, List[RuleDefinition]]:
    index: Dict[str, List[RuleDefinition]] = {}
    for r in rules:
        for fw in r.frameworks:
            index.setdefault(fw, []).append(r)
    return index