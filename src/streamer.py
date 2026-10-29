"""
Módulo de Transmissão e Sessão de Projeção Nativa Linux.
Implementa o protocolo nativo Epson EasyMP (portas 3620 e 3621) e controle ESC/VP.net (porta 3629).
Garante silêncio absoluto (Volume 0 constante) e estabilidade de transmissão em tempo real.
Utiliza decodificador nativo Tight JPEG (0x90) em 4 quadrantes sincronizados.
"""

import socket
import struct
import time
import threading
import logging
from typing import Callable, Optional

from .escvp import EscvpClient
from .capture import ScreenCapturer, CANVAS_W, CANVAS_H

log = logging.getLogger(__name__)


def make_tight_jpeg_desc(tx: int, ty: int, tw: int, th: int, data_len: int) -> bytes:
    """
    Descritor Tight JPEG nativo de 16 bytes (extraído de EMP_PJCON.dll / modo 0):
    - 0..7:   x, y, w, h (>HHHH)
    - 8..11:  encoding 7 (>I)
    - 12:     0x90 (JPEG control byte)
    - 13..15: 3 bytes de tamanho compacto Tight
    """
    b0 = (data_len & 0x7F) | 0x80
    b1 = ((data_len >> 7) & 0x7F) | 0x80
    b2 = (data_len >> 14) & 0xFF
    return struct.pack(">HHHH", tx, ty, tw, th) + struct.pack(">I", 7) + bytes([0x90, b0, b1, b2])


class ProjectorSession:
    def __init__(self, host: str, name: str = "", mac: str = "", monitor_index: int = 0, fps: int = 20, quality: int = 90, width: int = 1024, height: int = 768):
        self.host = host
        self.name = name or host
        self.mac_str = mac.replace(":", "").replace("-", "") if mac else ""
        self.monitor_index = monitor_index
        self.fps = fps
        self.quality = quality
        self.width = width
        self.height = height

        self.escvp = EscvpClient(self.host)
        self.capturer = ScreenCapturer(
            monitor_index=self.monitor_index,
            fps=self.fps,
            quality=self.quality,
            canvas_w=self.width,
            canvas_h=self.height
        )
        self.active = False
        self.paused = False
        self.black_screen = False

        self.sock_video: Optional[socket.socket] = None
        self.sock_audio: Optional[socket.socket] = None
        self.control_sock: Optional[socket.socket] = None
        self.local_ip: bytes = b"\x00\x00\x00\x00"
        self.local_ip_str: str = ""

        self._running = False
        self._threads: list[threading.Thread] = []
        self.frames_sent = 0
        self.bytes_sent = 0
        self.on_remote_disconnect: Optional[Callable[[str], None]] = None

    def _get_local_ip(self) -> bytes:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect((self.host, 3620))
            self.local_ip_str = s.getsockname()[0]
            self.local_ip = socket.inet_aton(self.local_ip_str)
            s.close()
        except Exception:
            self.local_ip_str = "127.0.0.1"
            self.local_ip = socket.inet_aton("127.0.0.1")
        return self.local_ip

    def start(self, on_status_change: Optional[Callable[[str], None]] = None) -> tuple[bool, str]:
        def update_status(msg: str):
            if on_status_change:
                on_status_change(msg)

        # --- Fase 1: Conectar ESC/VP.net (porta 3629) com retries ---
        update_status("Conectando ao controle do projetor (ESC/VP)...")
        escvp_connected = False
        for attempt in range(3):
            if self.escvp.connect():
                escvp_connected = True
                break
            log.info(f"Tentativa ESC/VP {attempt+1}/3 falhou, aguardando...")
            time.sleep(1.5)

        if not escvp_connected:
            return False, "Não foi possível conectar na porta de controle (3629) do projetor."

        # --- Fase 2: Verificar e ligar o projetor se necessário ---
        pwr = self.escvp.get_power()
        log.info(f"Estado de energia do projetor: {pwr}")

        if pwr in ("STANDBY", "OFF", None):
            update_status("Ligando o projetor (saindo do modo Standby)...")
            self.escvp.set_power(True)

            # Após enviar PWR ON, o projetor pode desconectar o ESC/VP.
            # Aguarda 3s e reconecta para acompanhar o warmup.
            time.sleep(3)

            warmup_ok = False
            for i in range(45):  # Até 45 segundos de warmup
                # Reconecta ESC/VP se necessário (projetor reinicia a conexão ao ligar)
                if not self.escvp.connected:
                    self.escvp.connect()

                current_pwr = self.escvp.get_power()
                if current_pwr == "ON":
                    warmup_ok = True
                    break
                elif current_pwr == "WARMUP":
                    secs = 45 - i
                    update_status(f"Projetor aquecendo... (aguardando até {secs}s)")
                elif current_pwr in ("STANDBY", "OFF", None):
                    # Ainda não respondeu ao power on, reenvia
                    if i % 5 == 4:
                        log.info("Reenviando PWR ON...")
                        if not self.escvp.connected:
                            self.escvp.connect()
                        self.escvp.set_power(True)
                    update_status(f"Aguardando projetor ligar... ({i+1}s)")
                else:
                    update_status(f"Estado: {current_pwr} - aguardando...")
                time.sleep(1)

            if not warmup_ok:
                # Tenta uma última verificação
                if not self.escvp.connected:
                    self.escvp.connect()
                final_pwr = self.escvp.get_power()
                if final_pwr != "ON":
                    return False, f"Projetor não ligou a tempo (último estado: {final_pwr}). Tente novamente."

        elif pwr == "WARMUP":
            update_status("Projetor está aquecendo, aguardando ficar pronto...")
            for i in range(30):
                time.sleep(1)
                if not self.escvp.connected:
                    self.escvp.connect()
                if self.escvp.get_power() == "ON":
                    break
                update_status(f"Aquecendo... ({i+1}s)")

        elif pwr == "COOLDOWN":
            update_status("Projetor está esfriando. Aguardando finalizar para religar...")
            for i in range(60):
                time.sleep(1)
                if not self.escvp.connected:
                    self.escvp.connect()
                current = self.escvp.get_power()
                if current in ("STANDBY", "OFF"):
                    # Agora pode ligar novamente
                    update_status("Religando o projetor...")
                    self.escvp.set_power(True)
                    time.sleep(3)
                    for j in range(45):
                        if not self.escvp.connected:
                            self.escvp.connect()
                        if self.escvp.get_power() == "ON":
                            break
                        time.sleep(1)
                        update_status(f"Aquecendo... ({j+1}s)")
                    break
                update_status(f"Esfriando... ({i+1}s)")

        # --- Fase 3: Reconecta ESC/VP para garantir sessão limpa após power-on ---
        if not self.escvp.connected:
            self.escvp.connect()

        # SILÊNCIO ABSOLUTO: Volume 0 garantido no hardware
        try:
            self.escvp.set_volume(0)
        except Exception as e:
            log.warning(f"Aviso volume 0: {e}")

        # Comuta para LAN (SOURCE 53) — precisa que o projetor esteja ON
        update_status("Selecionando entrada de rede (LAN)...")
        for attempt in range(3):
            if not self.escvp.connected:
                self.escvp.connect()
            result = self.escvp.set_source_lan()
            if result:
                break
            log.info(f"Tentativa SOURCE LAN {attempt+1}/3 falhou, reconectando...")
            time.sleep(1)
            self.escvp.close()
            self.escvp.connect()

        # Determina IP local de rota
        self._get_local_ip()

        # Garante MAC address do projetor correto (autodescoberta se não informado)
        if not self.mac_str or len(self.mac_str) != 12:
            try:
                s_probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s_probe.settimeout(0.8)
                s_probe.connect((self.host, 3620))
                lip_bytes = socket.inet_aton(s_probe.getsockname()[0])
                s_probe.sendall(b"EEMP0100" + lip_bytes + struct.pack("<II", 0x0002, 0))
                resp_probe = s_probe.recv(512)
                s_probe.close()
                if len(resp_probe) >= 74:
                    self.mac_str = resp_probe[68:74].hex()
            except Exception:
                pass
        if not self.mac_str:
            self.mac_str = "000000000000"

        # 1. Handshake de Controle na porta TCP 3620
        update_status("Negociando sessão de projeção na porta 3620...")
        try:
            s_ctrl = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s_ctrl.settimeout(5.0)
            s_ctrl.connect((self.host, 3620))
            self.control_sock = s_ctrl

            mac_bytes = bytes.fromhex(self.mac_str.ljust(12, "0"))
            base_hdr = bytes.fromhex("0100000000000000000020f37fffff0000000000000201030004000320200001ff00ff00ff00000810000000010c0000")
            payload = base_hdr + mac_bytes + (b"\x00" * 16) + self.local_ip
            reqconnect = b"EEMP0100" + self.local_ip + struct.pack("<II", 0x0004, len(payload)) + payload

            s_ctrl.sendall(reqconnect)
            resp = s_ctrl.recv(4096)
            if len(resp) < 20:
                return False, "Projetor não respondeu ao handshake."

            cmd = struct.unpack_from("<I", resp, 12)[0]
            if cmd != 0x0005:
                return False, f"Projetor recusou sessão (código 0x{cmd:04x})."

            log.info("Canal de controle TCP 3620 estabelecido com sucesso.")
        except Exception as e:
            return False, f"Falha na negociação de controle 3620: {e}"

        self._running = True

        # Thread de monitoramento e detecção de Takeover (desconexão remota)
        def ctrl_reader():
            s_ctrl.settimeout(0.5)
            while self._running:
                try:
                    data = s_ctrl.recv(4096)
                    if not data:
                        log.info("Canal de controle 3620 encerrado pelo servidor.")
                        self._trigger_disconnect("Outro usuário ou o projetor encerrou a sessão.")
                        break
                    if len(data) >= 16:
                        cmd = struct.unpack_from("<I", data, 12)[0]
                        if cmd in (0x0006, 0x0007):
                            log.info(f"Comando de encerramento recebido do projetor (0x{cmd:04x}).")
                            self._trigger_disconnect("A sessão foi encerrada pelo projetor ou assumida por outro usuário.")
                            break
                        elif cmd == 0x0016:
                            # 0x0016 é a confirmação de resolução/geometria enviada pelo projetor ao conectar (ex: 1024x768)
                            log.debug("Aviso de geometria/resolução de tela (0x0016) recebido do projetor.")
                        elif cmd == 0x000a:
                            log.debug("Keepalive ack (0x000a) recebido do projetor.")
                        else:
                            log.debug(f"Pacote EEMP 0x{cmd:04x} recebido no canal de controle.")
                except socket.timeout:
                    pass
                except Exception as e:
                    if self._running:
                        log.info(f"Canal 3620 desconectado: {e}")
                        self._trigger_disconnect("A conexão com o projetor foi interrompida.")
                    break
        t_cr = threading.Thread(target=ctrl_reader, daemon=True)
        t_cr.start()
        self._threads.append(t_cr)

        # Thread de keepalive a cada 1.0s
        def keepalive_loop():
            while self._running:
                try:
                    ka = b"EEMP0100" + self.local_ip + struct.pack("<II", 0x000a, 0)
                    s_ctrl.sendall(ka)
                    time.sleep(1.0)
                except Exception:
                    break
        t_ka = threading.Thread(target=keepalive_loop, daemon=True)
        t_ka.start()
        self._threads.append(t_ka)

        time.sleep(0.3)

        # 2. Conectar Canais de Vídeo e Auxiliar na porta 3621
        update_status("Iniciando canais de streaming de vídeo (porta 3621)...")
        try:
            self.sock_video = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock_video.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self.sock_video.connect((self.host, 3621))

            self.sock_audio = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock_audio.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self.sock_audio.connect((self.host, 3621))

            # Thread para drenar canal auxiliar/áudio
            def audio_reader():
                self.sock_audio.settimeout(0.5)
                while self._running:
                    try:
                        self.sock_audio.recv(4096)
                    except Exception:
                        pass
            t_ar = threading.Thread(target=audio_reader, daemon=True)
            t_ar.start()
            self._threads.append(t_ar)

            # Enviar Pacote 1 (Display Config com resolução negociada)
            disp_payload = (
                b"\xc8\x00\x00\x00" +
                struct.pack(">HH", self.width, self.height) +
                b"\x20\x20\x00\x01\xff\x00\xff\x00\xff\x00\x10\x08\x00\x00\x00\x00"
            )
            pkt1 = b"EPRD0600" + self.local_ip + b"\x00\x00\x00\x00" + struct.pack("<I", len(disp_payload)) + disp_payload
            self.sock_video.sendall(pkt1)
            time.sleep(0.3)
            log.info(f"Canal de vídeo inicializado com sucesso ({self.width}x{self.height}).")
        except Exception as e:
            self.stop()
            return False, f"Falha ao conectar no canal de vídeo 3621: {e}"

        self.active = True
        self.paused = False
        self.black_screen = False
        self.frames_sent = 0
        self.bytes_sent = 0

        # Loop de entrega dos 4 quadrantes agrupados num único envio atômico
        def send_tiles(tiles_data: list[tuple[int, int, int, int, bytes]]):
            if not self.active or not self.sock_video:
                return
            try:
                parts = []
                for tx, ty, tw, th, jdata in tiles_data:
                    desc = make_tight_jpeg_desc(tx, ty, tw, th, len(jdata))
                    parts.append(desc + jdata)
                payload = struct.pack(">I", len(tiles_data)) + b"".join(parts)
                pkt = b"EPRD0600" + self.local_ip + b"\x00\x00\x00\x00" + struct.pack(">I", len(payload)) + payload
                self.sock_video.sendall(pkt)
                self.bytes_sent += len(pkt)
                self.frames_sent += 1
            except Exception as e:
                log.error(f"Erro transmitindo frame para o projetor: {e}")
                if self._running:
                    self._trigger_disconnect("Falha de transmissão no canal de vídeo.")

        self.capturer.start_streaming(send_tiles)
        update_status("Projetando com sucesso!")
        return True, "Sessão iniciada."

    def toggle_pause(self) -> bool:
        """Pausa ou despausa a projeção congelando o quadro atual."""
        self.paused = not self.paused
        self.capturer.set_pause(self.paused)
        return self.paused

    def toggle_black_screen(self) -> bool:
        """Ativa/Desativa o modo tela preta via software (mantendo a lâmpada e a sessão ativas)."""
        self.black_screen = not self.black_screen
        self.capturer.set_black_screen(self.black_screen)
        return self.black_screen

    def _trigger_disconnect(self, reason: str = ""):
        """Acionado quando o projetor é desligado ou outro usuário na rede encerra esta sessão."""
        if not self.active and not self._running:
            return

        # Verifica o estado real de energia para saber se foi desligado ou assumido por outro usuário
        disconnect_type = "TAKEOVER"
        try:
            client = EscvpClient(self.host, timeout=1.0)
            if client.connect():
                pwr = client.get_power()
                client.close()
                if pwr in ("STANDBY", "COOLDOWN", "OFF"):
                    disconnect_type = "POWER_OFF"
                elif pwr == "ON":
                    disconnect_type = "TAKEOVER"
            else:
                disconnect_type = "POWER_OFF"
        except Exception as e:
            log.debug(f"Erro verificando energia no encerramento: {e}")

        log.warning(f"Desconexão remota acionada ({disconnect_type}): {reason}")
        self.stop()
        if self.on_remote_disconnect:
            try:
                self.on_remote_disconnect(disconnect_type)
            except Exception as e:
                log.error(f"Erro chamando on_remote_disconnect: {e}")

    def stop(self):
        """Para a transmissão e encerra a sessão com desconexão amigável (0x0006)."""
        self.active = False
        self._running = False
        self.capturer.stop_streaming()

        if self.sock_video:
            try:
                self.sock_video.close()
            except Exception:
                pass
            self.sock_video = None

        if self.sock_audio:
            try:
                self.sock_audio.close()
            except Exception:
                pass
            self.sock_audio = None

        if self.control_sock:
            try:
                discon = b"EEMP0100" + self.local_ip + struct.pack("<II", 0x0006, 0)
                self.control_sock.sendall(discon)
                time.sleep(0.2)
                self.control_sock.close()
            except Exception:
                pass
            self.control_sock = None

        self.escvp.close()
