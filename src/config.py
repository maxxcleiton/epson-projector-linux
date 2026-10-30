"""
Gerenciamento de configurações e lista de projetores.
Armazena a lista em ~/.config/epson-projector/projectors.json
"""

import json
import os
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "epson-projector"
CONFIG_FILE = CONFIG_DIR / "projectors.json"

DEFAULT_PROJECTORS = [
    {
        "id": "proj-01",
        "name": "Projetor Sala Principal",
        "ip": "192.168.1.100",
        "mac": "",
        "port_escvp": 3629,
        "port_easymp": 3620,
        "port_stream": 3621,
    },
]


def load_config() -> dict:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if not CONFIG_FILE.exists():
        cfg = {"projectors": DEFAULT_PROJECTORS, "last_selected": "proj-01", "fps": 20, "quality": 90}
        save_config(cfg)
        return cfg
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        if "projectors" not in cfg or not cfg["projectors"]:
            cfg["projectors"] = DEFAULT_PROJECTORS
            save_config(cfg)
        return cfg
    except Exception:
        return {"projectors": DEFAULT_PROJECTORS, "last_selected": "proj-01", "fps": 20, "quality": 90}


def save_config(config: dict):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def get_projectors() -> list:
    cfg = load_config()
    return cfg.get("projectors", DEFAULT_PROJECTORS)


def add_or_update_projector(name: str, ip: str, mac: str = "") -> dict:
    cfg = load_config()
    projs = cfg.get("projectors", [])
    for p in projs:
        if p["ip"] == ip:
            p["name"] = name
            if mac:
                p["mac"] = mac
            save_config(cfg)
            return p
    new_p = {
        "id": f"proj-{len(projs)+1}",
        "name": name,
        "ip": ip,
        "mac": mac,
        "port_escvp": 3629,
        "port_easymp": 3620,
        "port_stream": 3621,
    }
    projs.append(new_p)
    cfg["projectors"] = projs
    save_config(cfg)
    return new_p


def update_projector_details(orig_ip: str, new_name: str, new_ip: str) -> bool:
    """Atualiza o nome e/ou endereço IP de um projetor existente."""
    cfg = load_config()
    projs = cfg.get("projectors", [])
    found = False
    for p in projs:
        if p.get("ip") == orig_ip:
            p["name"] = new_name
            p["ip"] = new_ip
            p["custom_name"] = True
            found = True
            break
    if found:
        save_config(cfg)
    return found


def remove_projector(ip: str) -> bool:
    """Remove um projetor da lista de configurações pelo IP."""
    cfg = load_config()
    projs = cfg.get("projectors", [])
    initial_len = len(projs)
    projs = [p for p in projs if p.get("ip") != ip]
    if len(projs) < initial_len:
        cfg["projectors"] = projs
        save_config(cfg)
        return True
    return False
