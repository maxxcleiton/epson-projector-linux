#!/usr/bin/env python3
"""
Ponto de entrada do aplicativo Epson Projeção Linux.
"""

import sys
import os
import signal
import logging
import ctypes

# OBRIGATÓRIO: Inicializa o suporte a múltiplas threads no X11/Xlib antes de qualquer inicialização de GUI.
# Sem isso, chamadas de captura de tela em background threads disparam erro fatal no XCB:
# "[xcb] Most likely this is a multi-threaded client and XInitThreads has not been called"
try:
    ctypes.cdll.LoadLibrary("libX11.so.6").XInitThreads()
except Exception as _e:
    logging.warning(f"Aviso XInitThreads: {_e}")

# Garante compatibilidade total em ambientes Wayland (ex: Ubuntu 24.04 GNOME) roteando via XWayland
os.environ.setdefault("GDK_BACKEND", "x11")

# Garante que o diretório pai de 'src/' esteja no sys.path,
# necessário quando executado via .deb (/usr/share/epson-projector/src/main.py)
_this_dir = os.path.dirname(os.path.abspath(__file__))
_parent_dir = os.path.dirname(_this_dir)
if _parent_dir not in sys.path:
    sys.path.insert(0, _parent_dir)

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib

from src.ui import MainWindow
from src.tray import TrayIndicator

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s [%(name)s]: %(message)s"
)
log = logging.getLogger("epson-projector")


def main():
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    log.info("Iniciando Epson Projeção Linux...")
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
