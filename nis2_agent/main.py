from __future__ import annotations

import argparse
import datetime as dt
import json
import socket
from pathlib import Path
from typing import Any, Dict, List

from .logging_config import setup_logging
from .scanner import scan_system
from .rules_engine import RulesEngine
from .client import send_report  # NOWE


def save_json(data: Dict[str, Any], directory: str, prefix: str) -> Path:
    path = Path(directory)
    path.mkdir(parents=True, exist_ok=True)
    ts = dt.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    file_path = path / f"{prefix}_{ts}.json"
    with file_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return file_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Minimal NIS2 compliance agent (scan + rules + optional HTTP report)."
    )
    parser.add_argument(
        "--rules-dir",
        default="rules",
        help="Directory with YAML rules files.",
    )
    parser.add_argument(
        "--log-dir",
        default="logs",
        help="Directory for log files and JSON outputs.",
    )
    parser.add_argument(
        "--server-url",
        default=None,
        help=(
            "Base URL nis2_server (np. http://127.0.0.1:8000). "
            "Jeśli nie podane, agent nie wysyła raportu do serwera."
        ),
    )
    parser.add_argument(
        "--agent-id",
        default=None,
        help=(
            "Identyfikator agenta. Jeśli nie podany, użyty będzie hostname."
        ),
    )

    args = parser.parse_args()

    logger = setup_logging(args.log_dir)
    logger.info("Starting scan...")

    scan_result = scan_system()
    scan_dict = scan_result.to_dict()

    scan_file = save_json(scan_dict, args.log_dir, "scan")
    logger.info("Scan saved to %s", scan_file)

    engine = RulesEngine(rules_dir=args.rules_dir)
    logger.info("Loaded %d rules", len(engine.rules))

    rule_results = engine.evaluate(scan_dict)

    # Zapis wyników do JSON
    results_serialized = [
        engine.serialize_result(r) for r in rule_results
    ]
    results_file = save_json(
        {"results": results_serialized}, args.log_dir, "rules"
    )
    logger.info("Rule results saved to %s", results_file)

    # Dodatkowy log w formie JSONL dla findings
    jsonl_path = Path(args.log_dir) / "findings.jsonl"
    with jsonl_path.open("a", encoding="utf-8") as f:
        for r in rule_results:
            if not r.passed:
                json.dump(engine.serialize_result(r), f, ensure_ascii=False)
                f.write("\n")

    # Podsumowanie lokalne
    total = len(rule_results)
    failed = sum(1 for r in rule_results if not r.passed)
    passed = total - failed

    logger.info(
        "Rules summary: %d total, %d passed, %d failed",
        total,
        passed,
        failed,
    )

    if failed:
        logger.info("Failed rules:")
        for r in rule_results:
            if not r.passed:
                logger.info(
                    "- %s (%s): %s",
                    r.rule_id,
                    r.severity.upper(),
                    r.description,
                )

    if args.server_url:
        agent_id = args.agent_id or socket.gethostname()
        payload = {
            "agent_id": agent_id,
            "scan": scan_dict,
            "rules": results_serialized,
        }
        resp = send_report(
            logger=logger,
            server_url=args.server_url,
            payload=payload,
        )
        if resp is None:
            logger.error("Failed to send report to server.")
        else:
            logger.info(
                "Report accepted by server. Returned timestamp: %s",
                resp.get("timestamp"),
            )


if __name__ == "__main__":
    main()