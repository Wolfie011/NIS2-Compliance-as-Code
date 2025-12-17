from __future__ import annotations

import argparse
import datetime as dt
import json
import socket
import time
from pathlib import Path
from typing import Any, Dict

from nis2_agent.logging_config import setup_logging
from nis2_agent.scanner import scan_system
from nis2_agent.rules_engine import RulesEngine
from nis2_agent.client import send_report, fetch_config, fetch_rules_bundle


DEFAULT_INTERVAL_SECONDS = 6 * 60 * 60  # 6h


def save_json(data: Dict[str, Any], directory: str, prefix: str) -> Path:
    path = Path(directory)
    path.mkdir(parents=True, exist_ok=True)
    ts = dt.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    file_path = path / f"{prefix}_{ts}.json"
    with file_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return file_path


def build_rules_engine(
    logger,
    rules_source: str,
    rules_dir: str,
    server_url: str | None,
) -> RulesEngine:
    """
    Buduje RulesEngine w zależności od źródła reguł:
    - local: YAML z katalogu rules_dir
    - remote: bundle z nis2_server (/api/v1/rules/bundle), z fallbackiem na lokalne pliki
    """
    if rules_source == "remote":
        if not server_url:
            logger.warning(
                "rules_source=remote, ale nie podano server_url – używam lokalnych reguł."
            )
        else:
            try:
                bundle = fetch_rules_bundle(server_url)
                rules = bundle.get("rules") or []
                version = bundle.get("version")
                logger.info(
                    "Loaded %d rules from server (version=%s)",
                    len(rules),
                    version,
                )
                return RulesEngine.from_list(rules)
            except Exception as e:
                logger.error(
                    "Failed to fetch rules bundle from server (%s). "
                    "Falling back to local rules in %s",
                    e,
                    rules_dir,
                )

    engine = RulesEngine(rules_dir=rules_dir)
    logger.info(
        "Loaded %d rules from local directory %s",
        len(engine.rules),
        rules_dir,
    )
    return engine


def run_single_scan(
    logger,
    rules_source: str,
    rules_dir: str,
    log_dir: str,
    server_url: str | None,
    agent_id: str,
) -> None:
    logger.info("Starting scan...")

    scan_result = scan_system()
    scan_dict = scan_result.to_dict()

    scan_file = save_json(scan_dict, log_dir, "scan")
    logger.info("Scan saved to %s", scan_file)

    engine = build_rules_engine(
        logger=logger,
        rules_source=rules_source,
        rules_dir=rules_dir,
        server_url=server_url,
    )
    logger.info("Rules engine initialized with %d rules", len(engine.rules))

    rule_results = engine.evaluate(scan_dict)

    # Zapis wyników do JSON
    results_serialized = [engine.serialize_result(r) for r in rule_results]
    results_file = save_json(
        {"results": results_serialized},
        log_dir,
        "rules",
    )
    logger.info("Rule results saved to %s", results_file)

    # Dodatkowy log w formie JSONL dla findings
    jsonl_path = Path(log_dir) / "findings.jsonl"
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

    # Wysyłka do serwera (jeśli skonfigurowany)
    if server_url:
        payload = {
            "agent_id": agent_id,
            "scan": scan_dict,
            "rules": results_serialized,
        }
        resp = send_report(
            logger=logger,
            server_url=server_url,
            payload=payload,
        )
        if resp is None:
            logger.error("Failed to send report to server.")
        else:
            logger.info(
                "Report accepted by server. Returned timestamp: %s",
                resp.get("timestamp"),
            )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "NIS2 agent (scan + rules + optional HTTP report, loop or once). "
            "Obsługuje reguły lokalne lub zdalne (remote bundle)."
        )
    )
    parser.add_argument(
        "--rules-dir",
        default="rules",
        help="Directory with YAML rules files (dla rules-source=local).",
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
            "Jeśli nie podane, agent działa tylko lokalnie."
        ),
    )
    parser.add_argument(
        "--agent-id",
        default=None,
        help=(
            "Identyfikator agenta. Jeśli nie podany, użyty będzie hostname."
        ),
    )
    parser.add_argument(
        "--mode",
        choices=["once", "loop"],
        default="once",
        help="Tryb pracy agenta: 'once' (jeden skan) albo 'loop' (cyklicznie).",
    )
    parser.add_argument(
        "--rules-source",
        choices=["local", "remote"],
        default="local",
        help=(
            "Źródło reguł: 'local' (pliki YAML z --rules-dir) "
            "lub 'remote' (bundle z nis2_server /api/v1/rules/bundle)."
        ),
    )

    args = parser.parse_args()

    logger = setup_logging(args.log_dir)
    agent_id = args.agent_id or socket.gethostname()
    logger.info(
        "Agent starting with id=%s, mode=%s, rules_source=%s",
        agent_id,
        args.mode,
        args.rules_source,
    )

    if args.mode == "once":
        run_single_scan(
            logger=logger,
            rules_source=args.rules_source,
            rules_dir=args.rules_dir,
            log_dir=args.log_dir,
            server_url=args.server_url,
            agent_id=agent_id,
        )
        return

    # Tryb 'loop'
    interval = DEFAULT_INTERVAL_SECONDS

    try:
        while True:
            # 1. Opcjonalnie pobierz config z serwera (jeśli jest URL)
            if args.server_url:
                cfg = fetch_config(
                    logger=logger,
                    server_url=args.server_url,
                    agent_id=agent_id,
                )
                if cfg:
                    enabled = bool(cfg.get("enabled", True))
                    interval = int(
                        cfg.get("scan_interval_seconds", DEFAULT_INTERVAL_SECONDS)
                    )
                    if not enabled:
                        logger.info(
                            "Agent disabled by config. Sleeping for %s seconds.",
                            interval,
                        )
                        time.sleep(max(interval, 60))
                        continue

            # 2. Wykonaj skan
            run_single_scan(
                logger=logger,
                rules_source=args.rules_source,
                rules_dir=args.rules_dir,
                log_dir=args.log_dir,
                server_url=args.server_url,
                agent_id=agent_id,
            )

            # 3. Poczekaj do kolejnego skanu
            logger.info("Sleeping for %s seconds before next scan...", interval)
            time.sleep(max(interval, 60))

    except KeyboardInterrupt:
        logger.info("Agent interrupted, exiting.")


if __name__ == "__main__":
    main()