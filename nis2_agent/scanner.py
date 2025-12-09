from __future__ import annotations

import platform
import socket
import subprocess
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class ScanResult:
    hostname: str
    os: Dict[str, Any]
    network: Dict[str, Any]
    ssh: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def get_os_info() -> Dict[str, Any]:
    return {
        "system": platform.system(),
        "release": platform.release(),
        "version": platform.version(),
        "machine": platform.machine(),
        "python_version": platform.python_version(),
    }


def _parse_ss_output(output: str) -> List[int]:
    """
    Parsuje wynik 'ss -tuln' do listy portów TCP.
    """
    ports: List[int] = []
    for line in output.splitlines():
        line = line.strip()
        if not line or line.startswith("Netid"):
            continue
        parts = line.split()
        if len(parts) < 5:
            continue
        local_addr = parts[4]
        # Format: 0.0.0.0:22 albo [::]:80
        if ":" not in local_addr:
            continue
        try:
            port_str = local_addr.rsplit(":", 1)[1]
            port = int(port_str)
            ports.append(port)
        except ValueError:
            continue
    return sorted(set(ports))


def get_open_tcp_ports() -> List[int]:
    """
    Próbuje użyć 'ss -tuln'; jeśli brak, zwraca pustą listę.
    """
    try:
        proc = subprocess.run(
            ["ss", "-tuln"],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            return []
        return _parse_ss_output(proc.stdout)
    except FileNotFoundError:
        # Brak 'ss' (np. Windows) – minimalny PoC
        return []


def parse_sshd_config(path: str = "/etc/ssh/sshd_config") -> Dict[str, Any]:
    """
    Parsuje tylko kilka podstawowych opcji z sshd_config.
    Jeśli plik nie istnieje, zwraca pusty słownik.
    """
    cfg_path = Path(path)
    result: Dict[str, Any] = {}

    if not cfg_path.exists():
        return result

    try:
        with cfg_path.open("r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split(None, 1)
                if len(parts) != 2:
                    continue
                key, value = parts
                key_lower = key.lower()
                value_stripped = value.strip()
                if key_lower == "permitrootlogin":
                    result["permit_root_login"] = value_stripped
                elif key_lower == "passwordauthentication":
                    result["password_authentication"] = value_stripped
    except Exception:
        # W PoC nie panikujemy – po prostu zwracamy to, co mamy
        pass

    return result


def scan_system() -> ScanResult:
    hostname = socket.gethostname()
    os_info = get_os_info()
    open_tcp_ports = get_open_tcp_ports()
    ssh_cfg = parse_sshd_config()

    network_info: Dict[str, Any] = {
        "open_tcp_ports": open_tcp_ports,
    }

    return ScanResult(
        hostname=hostname,
        os=os_info,
        network=network_info,
        ssh=ssh_cfg,
    )