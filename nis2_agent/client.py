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


def fetch_config(
    logger: logging.Logger,
    server_url: str,
    agent_id: str,
    timeout: float = 5.0,
) -> Optional[Dict[str, Any]]:
    """
    Pobiera konfigurację dla danego agenta z serwera.
    Zwraca dict z polami m.in.:
      - agent_id
      - scan_interval_seconds
      - enabled
    albo None przy błędzie.
    """
    url = server_url.rstrip("/") + f"/api/v1/agents/{agent_id}/config"
    try:
        logger.info("Fetching config from %s ...", url)
        resp = requests.get(url, timeout=timeout)
    except Exception as e:
        logger.error("Error while fetching config: %s", e)
        return None

    if resp.status_code >= 400:
        logger.error(
            "Server responded with error status %s while fetching config: %s",
            resp.status_code,
            resp.text,
        )
        return None

    try:
        data = resp.json()
    except ValueError:
        logger.error("Config response is not valid JSON: %r", resp.text)
        return None

    logger.info(
        "Config fetched: enabled=%s, scan_interval_seconds=%s",
        data.get("enabled"),
        data.get("scan_interval_seconds"),
    )
    return data


def fetch_rules_bundle(server_url: str) -> Dict[str, Any]:
    """
    Pobiera z serwera komplet reguł dla agenta z endpointu /api/v1/rules/bundle.
    Oczekuje struktury:
      {
        "version": "<hash>",
        "rules": [ {...}, ... ]
      }
    """
    url = server_url.rstrip("/") + "/api/v1/rules/bundle"
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    data: Dict[str, Any] = resp.json()
    return data