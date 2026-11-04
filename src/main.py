#!/usr/bin/env python3
"""
Ponto de entrada do aplicativo Epson Projeção Linux.
"""

import sys
import os
import signal
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import ctypes

# Garante que o diretório pai de 'src/' esteja no sys.path,
# necessário quando executado via .deb (/usr/share/epson-projector/src/main.py)
_this_dir = os.path.dirname(os.path.abspath(__file__))
_parent_dir = os.path.dirname(_this_dir)
if _parent_dir not in sys.path:
    sys.path.insert(0, _parent_dir)

# Diretório de configuração e arquivo de log nativo em ~/.config/epson-projector/epson-projector.log
CONFIG_DIR = Path.home() / ".config" / "epson-projector"
try:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
except Exception:
    pass
LOG_FILE = CONFIG_DIR / "epson-projector.log"

# Configuração de logging: Console (stdout) + Arquivo rotativo (2MB max, 3 backups)
log_formatter = logging.Formatter("[%(asctime)s] %(levelname)s [%(name)s]: %(message)s")

handlers = []
stream_handler = logging.StreamHandler(sys.stdout)
stream_handler.setFormatter(log_formatter)
stream_handler.setLevel(logging.INFO)
handlers.append(stream_handler)

try:
    file_handler = RotatingFileHandler(
        str(LOG_FILE),
        maxBytes=2 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8"
    )
    file_handler.setFormatter(log_formatter)
    file_handler.setLevel(logging.INFO)
    handlers.append(file_handler)
except Exception as _e:
    sys.stderr.write(f"Aviso ao inicializar arquivo de log ({LOG_FILE}): {_e}\n")

root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
for h in handlers:
    root_logger.addHandler(h)

log = logging.getLogger("epson-projector")


def handle_uncaught_exception(exc_type, exc_value, exc_traceback):
    """Garante que qualquer exceção não tratada seja registrada no arquivo de log."""
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    log.critical("Exceção não tratada na aplicação:", exc_info=(exc_type, exc_value, exc_traceback))


sys.excepthook = handle_uncaught_exception

# OBRIGATÓRIO: Inicializa o suporte a múltiplas threads no X11/Xlib antes de qualquer inicialização de GUI.
# Sem isso, chamadas de captura de tela em background threads disparam erro fatal no XCB:
# "[xcb] Most likely this is a multi-threaded client and XInitThreads has not been called"
try:
    ctypes.cdll.LoadLibrary("libX11.so.6").XInitThreads()
except Exception as _e:
    log.warning(f"Aviso XInitThreads: {_e}")

# Garante compatibilidade total em ambientes Wayland (ex: Ubuntu 24.04 GNOME) roteando via XWayland
os.environ.setdefault("GDK_BACKEND", "x11")

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib

from src.ui import MainWindow
from src.tray import TrayIndicator
from src import __version__


def main():
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    log.info(f"=== Iniciando Epson Projeção Linux v{__version__} ===")
    log.info(f"Log de execução ativo em: {LOG_FILE}")
    app_window = MainWindow()

    # Cria o indicador na bandeja do sistema
    try:
        tray = TrayIndicator(app_window)
        app_window.on_session_start_cb = lambda s: tray.update_session_state(True)
        app_window.on_session_stop_cb = lambda: tray.update_session_state(False)
    except Exception as e:
        log.warning(f"Bandeja do sistema não pôde ser iniciada (não crítico): {e}")

    app_window.connect("destroy", Gtk.main_quit)
    app_window.show_all()

    Gtk.main()


if __name__ == "__main__":
    main()
