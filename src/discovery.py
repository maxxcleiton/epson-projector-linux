"""
Módulo de Descoberta e Verificação de Status de Projetores na Rede Local.
"""

import socket
import struct
import concurrent.futures
import ipaddress
import logging
from typing import Callable
from .escvp import EscvpClient

log = logging.getLogger(__name__)


def check_is_busy_eemp(ip: str, timeout: float = 0.5) -> bool:
    """
    Consulta o status de sessão nativo EEMP na porta TCP 3620.
    Envia pacote 0x0002 (Query Status).
    No payload da resposta (offset 56 do pacote completo / offset 36 do payload):
      0x01 = LIVRE / DISPONÍVEL (nenhum cliente projetando)
      0x02 = OCUPADO / EM USO (sessão ativa de projeção)
    """
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect((ip, 3620))
        local_ip = s.getsockname()[0]
        lip_bytes = socket.inet_aton(local_ip)
        pkt = b"EEMP0100" + lip_bytes + struct.pack("<II", 0x0002, 0)
        s.sendall(pkt)
        resp = s.recv(512)
        s.close()
        if len(resp) >= 57:
            return resp[56] == 0x02
    except Exception:
        pass
    return False


def check_projector_status(proj: dict) -> dict:
    """Verifica se o projetor está online, ligado, em standby, ou ocupado."""
    ip = proj["ip"]
    client = EscvpClient(ip, timeout=0.8)
    result = dict(proj)
    result["online"] = False
    result["power"] = "OFFLINE"
    result["is_busy"] = False

    if client.connect():
        result["online"] = True
        power = client.get_power()
        result["power"] = power if power else "UNKNOWN"

        # Se o projetor estiver LIGADO (ON): consulta via EEMP se há sessão ativa de outro usuário
        if power == "ON":
            if check_is_busy_eemp(ip):
                result["power"] = "BUSY"
                result["is_busy"] = True

        client.close()
    else:
        # Se a porta 3629 não respondeu, testa se a porta EasyMP 3620 responde
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.4)
            s.connect((ip, proj.get("port_easymp", 3620)))
            local_ip = s.getsockname()[0]
            lip_bytes = socket.inet_aton(local_ip)
            pkt = b"EEMP0100" + lip_bytes + struct.pack("<II", 0x0002, 0)
            s.sendall(pkt)
            resp = s.recv(512)
            s.close()
            result["online"] = True
            if len(resp) >= 57 and resp[56] == 0x02:
                result["power"] = "BUSY"
                result["is_busy"] = True
            else:
                result["power"] = "ON"
                result["is_busy"] = False
        except Exception:
            pass

    return result


def update_all_projector_statuses(projectors: list) -> list:
    """Atualiza o status de todos os projetores cadastrados em paralelo."""
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        future_map = {executor.submit(check_projector_status, p): p for p in projectors}
        for future in concurrent.futures.as_completed(future_map):
            try:
                res = future.result()
                results.append(res)
            except Exception as e:
                log.error(f"Erro checando status de projetor: {e}")
    # Ordena pelo nome para manter ordem estável
    results.sort(key=lambda x: x.get("name", ""))
    return results


def scan_network_for_projectors(subnet: str = "192.168.1.0/24", on_found: Callable[[dict], None] | None = None) -> list:
    """Varre a sub-rede procurando portas 3629 / 3620 ativas da Epson."""
    found = []
    try:
        network = ipaddress.ip_network(subnet, strict=False)
    except Exception:
        network = [ipaddress.ip_address(f"192.168.1.{i}") for i in range(1, 255)]

    def probe_ip(ip_str: str):
        # Verifica porta 3629 (ESC/VP.net)
        client = EscvpClient(ip_str, timeout=0.6)
        if client.connect():
            sno = client.get_serial_number() or ""
            lamp = client.get_lamp_hours()
            power = client.get_power()
            client.close()
            item = {
                "name": f"Epson-{ip_str.split('.')[-1]}",
                "ip": ip_str,
                "mac": "",
                "serial": sno,
                "power": power,
                "lamp": lamp,
                "online": True,
            }
            if on_found:
                on_found(item)
            return item
        return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=30) as executor:
        futures = [executor.submit(probe_ip, str(ip)) for ip in network.hosts()]
        for f in concurrent.futures.as_completed(futures):
            res = f.result()
            if res:
                found.append(res)

    return found
