from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import requests


def send_report(
    logger: logging.Logger,
    server_url: str,
    payload: Dict[str, Any],
    timeout: float = 5.0,
) -> Optional[Dict[str, Any]]:
    """
    Wysyła raport agenta do nis2_server.

    server_url: bazowy URL serwera, np. http://127.0.0.1:8000
    payload: słownik z polami:
        - agent_id: str
        - scan: dict
        - rules: list[dict]
    Zwraca zdekodowane JSON (dict) przy powodzeniu albo None przy błędzie.
    """
    url = server_url.rstrip("/") + "/api/v1/reports"

    try:
        logger.info("Sending report to %s ...", url)
        resp = requests.post(url, json=payload, timeout=timeout)
    except Exception as e:
        logger.error("Error while sending report to server: %s", e)
        return None

    if resp.status_code >= 400:
        logger.error(
            "Server responded with error status %s: %s",
            resp.status_code,
            resp.text,
        )
        return None

    try:
        data = resp.json()
    except ValueError:
        logger.error("Server response is not valid JSON: %r", resp.text)
        return None

    logger.info("Report successfully sent, server response: %s", data)
    return data