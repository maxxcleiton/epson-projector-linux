"""
Ícone na Bandeja do Sistema (System Tray / AyatanaAppIndicator).
Permite controlar e monitorar a projeção mesmo com a janela fechada.
"""

import os
from pathlib import Path
import logging

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

log = logging.getLogger(__name__)

# AyatanaAppIndicator é opcional (Recommends no .deb)
try:
    gi.require_version("AyatanaAppIndicator3", "0.1")
    from gi.repository import AyatanaAppIndicator3 as AppIndicator
    HAS_INDICATOR = True
except (ValueError, ImportError):
    HAS_INDICATOR = False
    log.info("AyatanaAppIndicator3 não disponível — bandeja do sistema desativada.")

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
ICON_PATH = str(ASSETS_DIR / "icon.png")


class TrayIndicator:
    def __init__(self, main_window):
        if not HAS_INDICATOR:
            raise ImportError("AyatanaAppIndicator3 não está instalado.")

        self.main_window = main_window

        # Configura o indicador na barra de notificações
        icon_name = ICON_PATH if os.path.exists(ICON_PATH) else "video-display"
        self.indicator = AppIndicator.Indicator.new(
            "epson-projection-linux",
            icon_name,
            AppIndicator.IndicatorCategory.APPLICATION_STATUS
        )
        self.indicator.set_status(AppIndicator.IndicatorStatus.ACTIVE)

        self.menu = Gtk.Menu()
        self.build_menu()
        self.indicator.set_menu(self.menu)

    def build_menu(self):
        # Abrir Janela Principal
        item_open = Gtk.MenuItem(label="Abrir Janela Principal")
        item_open.connect("activate", self.on_open_clicked)
        self.menu.append(item_open)

        # Separador
        self.menu.append(Gtk.SeparatorMenuItem())

        # Desconectar (aparece sensível quando há sessão)
        self.item_disconnect = Gtk.MenuItem(label="⏹ Desligar Projeção")
        self.item_disconnect.connect("activate", self.on_disconnect_clicked)
        self.item_disconnect.set_sensitive(False)
        self.menu.append(self.item_disconnect)

        # Separador
        self.menu.append(Gtk.SeparatorMenuItem())

        # Sair
        item_quit = Gtk.MenuItem(label="Sair")
        item_quit.connect("activate", self.on_quit_clicked)
        self.menu.append(item_quit)

        self.menu.show_all()

    def update_session_state(self, active: bool):
        self.item_disconnect.set_sensitive(active)

    def on_open_clicked(self, widget):
        self.main_window.show_all()
        self.main_window.present()

    def on_disconnect_clicked(self, widget):
        if self.main_window.floating_toolbar:
            self.main_window.floating_toolbar.on_disconnect_clicked(None)

    def on_quit_clicked(self, widget):
        if self.main_window.session:
            self.main_window.session.stop()
        Gtk.main_quit()
