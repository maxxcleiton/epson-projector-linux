"""
Módulo de Comunicação ESC/VP.net (Epson Secure Control / Video Protocol .net)
Porta TCP padrão: 3629
Permite ligar, desligar, verificar horas de lâmpada, selecionar entrada LAN e pausar/congelar tela.
"""

import socket
import logging

log = logging.getLogger(__name__)

ESCVP_PORT = 3629
HANDSHAKE_REQUEST = b"ESC/VP.net\x10\x03\x00\x00\x00\x00"
HANDSHAKE_ACK = b"ESC/VP.net"
CMD_TERMINATOR = b"\r"
PROMPT = b":"


class EscvpClient:
    def __init__(self, host: str, port: int = ESCVP_PORT, timeout: float = 5.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.sock: socket.socket | None = None
        self.connected = False

    def connect(self) -> bool:
        try:
            self.close()
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(self.timeout)
            s.connect((self.host, self.port))
            # Handshake oficial ESC/VP.net
            s.sendall(HANDSHAKE_REQUEST)
            resp = s.recv(1024)
            if not resp.startswith(HANDSHAKE_ACK):
                s.close()
                self.connected = False
                return False
            self.sock = s
            self.connected = True
            return True
        except Exception as e:
            log.debug(f"Erro conectando ESC/VP em {self.host}:{self.port} -> {e}")
            self.close()
            return False

    def close(self):
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None
        self.connected = False

    def send_command(self, cmd: str) -> str | None:
        if not self.connected:
            if not self.connect():
                return None
        try:
            data = cmd.encode("ascii") + CMD_TERMINATOR
            self.sock.sendall(data)
            self.sock.settimeout(self.timeout)
            resp = b""
            while not resp.endswith(PROMPT):
                chunk = self.sock.recv(512)
                if not chunk:
                    break
                resp += chunk
            text = resp.decode("ascii", errors="replace").strip()
            if text.endswith(":"):
                text = text[:-1].strip()
            return text
        except socket.timeout:
            log.warning(f"Timeout aguardando resposta do comando {cmd} em {self.host}")
            return None
        except Exception as e:
            log.warning(f"Falha ao enviar comando {cmd} para {self.host} -> {e}")
            self.close()
            return None

    def get_power(self) -> str | None:
        """
        Retorna:
          'ON' (01)
          'STANDBY' (04)
          'WARMUP' (02)
          'COOLDOWN' (03)
          'OFF' (00)
        """
        resp = self.send_command("PWR?")
        if not resp:
            return None
        if "PWR=01" in resp:
            return "ON"
        elif "PWR=04" in resp:
            return "STANDBY"
        elif "PWR=02" in resp:
            return "WARMUP"
        elif "PWR=03" in resp:
            return "COOLDOWN"
        elif "PWR=00" in resp:
            return "OFF"
        return resp

    def set_power(self, power_on: bool) -> bool:
        cmd = "PWR ON" if power_on else "PWR OFF"
        resp = self.send_command(cmd)
        return resp is not None and "ERR" not in resp

    def get_lamp_hours(self) -> int | None:
        resp = self.send_command("LAMP?")
        if resp and "LAMP=" in resp:
            try:
                return int(resp.split("LAMP=")[1].split(":")[0])
            except ValueError:
                pass
        return None

    def get_source(self) -> str | None:
        resp = self.send_command("SOURCE?")
        if resp and "SOURCE=" in resp:
            return resp.split("SOURCE=")[1].split(":")[0]
        return None

    def set_source_lan(self) -> bool:
        """Seleciona a entrada de rede LAN (EasyMP / Network Projection)"""
        resp = self.send_command("SOURCE 53")
        return resp is not None and "ERR" not in resp

    def set_freeze(self, freeze: bool) -> bool:
        cmd = "FREEZE ON" if freeze else "FREEZE OFF"
        resp = self.send_command(cmd)
        return resp is not None and "ERR" not in resp

    def set_mute(self, mute: bool) -> bool:
        cmd = "MUTE ON" if mute else "MUTE OFF"
        resp = self.send_command(cmd)
        return resp is not None and "ERR" not in resp

    def get_serial_number(self) -> str | None:
        resp = self.send_command("SNO?")
        if resp and "SNO=" in resp:
            return resp.split("SNO=")[1].split(":")[0]
        return None

    def get_volume(self) -> int | None:
        resp = self.send_command("VOL?")
        if resp and "VOL=" in resp:
            try:
                return int(resp.split("VOL=")[1].split(":")[0])
            except ValueError:
                pass
        return None

    def set_volume(self, volume: int = 0) -> bool:
        """Define o volume do projetor. Padrão 0 para silêncio absoluto."""
        resp = self.send_command(f"VOL {volume}")
        return resp is not None and "ERR" not in resp
