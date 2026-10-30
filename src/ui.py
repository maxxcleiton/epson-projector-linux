"""
Interface Gráfica Nativa em GTK3:
- Janela Principal (Interface Geral de Seleção e Configuração)
- Mini Janela Flutuante (Floating Toolbar no canto com botão 'Desligar Projeção')
"""

import time
import threading
import logging
from typing import Optional

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GLib", "2.0")
from gi.repository import Gtk, Gdk, GLib, Pango

from .config import (
    get_projectors,
    add_or_update_projector,
    update_projector_details,
    remove_projector,
    load_config,
    save_config,
)
from .discovery import update_all_projector_statuses, scan_network_for_projectors
from .capture import ScreenCapturer
from .streamer import ProjectorSession
from . import __version__

log = logging.getLogger(__name__)


class FloatingToolbar(Gtk.Window):
    """
    Mini Janela Flutuante que aparece no canto da tela quando a projeção está ativa.
    Contém status da transmissão, tempo, controles rápidos e o botão de desligar a projeção.
    """
    def __init__(self, session: ProjectorSession, on_disconnect_callback, on_remote_takeover_callback=None):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.session = session
        self.on_disconnect_callback = on_disconnect_callback
        self.on_remote_takeover_callback = on_remote_takeover_callback

        # Conecta escuta de desconexão remota (quando outro usuário assume o projetor)
        self.session.on_remote_disconnect = self._on_remote_disconnect_signal

        self.set_title("Projeção Ativa")
        self.set_default_size(320, 60)
        self.set_resizable(False)
        self.set_keep_above(True)  # Sempre visível no topo
        self.set_skip_taskbar_hint(False)  # Mantém visível na barra de tarefas

        # Posiciona no canto superior direito do monitor que está sendo transmitido
        monitors = ScreenCapturer.get_monitors()
        mon_idx = getattr(self.session, "monitor_index", 0)
        m = monitors[mon_idx] if (0 <= mon_idx < len(monitors)) else monitors[0]
        target_x = m["x"] + m["width"] - 340
        target_y = m["y"] + 40
        self.move(target_x, target_y)

        # Layout visual
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        vbox.set_margin_top(8)
        vbox.set_margin_bottom(8)
        vbox.set_margin_start(10)
        vbox.set_margin_end(10)
        self.add(vbox)

        # Linha superior: Indicador e Nome do Projetor
        hbox_top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        vbox.pack_start(hbox_top, False, False, 0)

        self.lbl_status = Gtk.Label()
        mon_label = f" [Mon {getattr(self.session, 'monitor_index', 0) + 1}]" if len(monitors) > 1 else ""
        self.lbl_status.set_markup(f"<span foreground='#e74c3c' font_desc='15'>●</span> <b>PROJETANDO:</b> {self.session.name}{mon_label}")
        hbox_top.pack_start(self.lbl_status, True, True, 0)

        self.lbl_timer = Gtk.Label(label="00:00")
        hbox_top.pack_end(self.lbl_timer, False, False, 0)

        # Linha de botões de ação
        hbox_btns = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        vbox.pack_start(hbox_btns, True, True, 0)

        # Botão Pausar / Congelar Tela
        self.btn_pause = Gtk.Button(label="⏸ Pausar")
        self.btn_pause.connect("clicked", self.on_pause_clicked)
        hbox_btns.pack_start(self.btn_pause, True, True, 0)

        # Botão Tela Preta (A/V Mute)
        self.btn_mute = Gtk.Button(label="⚫ Tela Preta")
        self.btn_mute.connect("clicked", self.on_mute_clicked)
        hbox_btns.pack_start(self.btn_mute, True, True, 0)

        # Botão principal: Desligar Projeção
        self.btn_disconnect = Gtk.Button(label="⏹ Desligar Projeção")
        self.btn_disconnect.get_style_context().add_class("destructive-action")
        self.btn_disconnect.connect("clicked", self.on_disconnect_clicked)
        hbox_btns.pack_start(self.btn_disconnect, True, True, 0)

        # Cronômetro
        self.start_time = time.time()
        self._timer_id = GLib.timeout_add_seconds(1, self.update_timer)

        self.show_all()

    def update_timer(self) -> bool:
        elapsed = int(time.time() - self.start_time)
        m, s = divmod(elapsed, 60)
        self.lbl_timer.set_text(f"{m:02d}:{s:02d}")
        return True

    def on_pause_clicked(self, widget):
        paused = self.session.toggle_pause()
        mon_idx = getattr(self.session, "monitor_index", 0)
        mon_label = f" [Mon {mon_idx + 1}]"
        if paused:
            self.btn_pause.set_label("▶ Retomar")
            self.lbl_status.set_markup(f"<span foreground='#f39c12' font_desc='15'>●</span> <b>PAUSADO:</b> {self.session.name}")
        else:
            self.btn_pause.set_label("⏸ Pausar")
            self.lbl_status.set_markup(f"<span foreground='#e74c3c' font_desc='15'>●</span> <b>PROJETANDO:</b> {self.session.name}{mon_label}")

    def on_mute_clicked(self, widget):
        is_black = self.session.toggle_black_screen()
        mon_idx = getattr(self.session, "monitor_index", 0)
        mon_label = f" [Mon {mon_idx + 1}]"
        if is_black:
            self.btn_mute.set_label("⚪ Restaurar Tela")
            self.lbl_status.set_markup(f"<span foreground='#7f8c8d' font_desc='15'>●</span> <b>TELA PRETA:</b> {self.session.name}")
        else:
            self.btn_mute.set_label("⚫ Tela Preta")
            self.lbl_status.set_markup(f"<span foreground='#e74c3c' font_desc='15'>●</span> <b>PROJETANDO:</b> {self.session.name}{mon_label}")

    def _on_remote_disconnect_signal(self, reason: str):
        GLib.idle_add(self._handle_remote_takeover_gui, reason)

    def _handle_remote_takeover_gui(self, reason: str):
        if self._timer_id:
            GLib.source_remove(self._timer_id)
            self._timer_id = 0
        self.destroy()
        if self.on_remote_takeover_callback:
            self.on_remote_takeover_callback(reason)

    def on_disconnect_clicked(self, widget):
        if self._timer_id:
            GLib.source_remove(self._timer_id)
            self._timer_id = 0
        self.session.stop()
        self.destroy()
        if self.on_disconnect_callback:
            self.on_disconnect_callback()


class MainWindow(Gtk.Window):
    """
    Janela Principal do Aplicativo.
    Exibe os projetores da empresa, status de rede/lâmpada, seletor de tela e botão de conexão.
    """
    def __init__(self, on_session_start_cb=None, on_session_stop_cb=None):
        super().__init__(title=f"Epson Projeção Linux v{__version__}")
        self.set_default_size(520, 500)
        self.set_position(Gtk.WindowPosition.CENTER)

        self.on_session_start_cb = on_session_start_cb
        self.on_session_stop_cb = on_session_stop_cb

        self.session: Optional[ProjectorSession] = None
        self.floating_toolbar: Optional[FloatingToolbar] = None

        self.projectors_data = []
        self.selected_proj_index = -1
        self._refreshing = False
        self._transient_power_states = {}  # Guarda estados temporários para transição suave (STARTING / COOLDOWN)

        # Aplica estilo CSS para garantir contraste perfeito e seleção elegante em tom grafite
        css_provider = Gtk.CssProvider()
        css_provider.load_from_data(b"""
            listbox row {
                border-radius: 6px;
                margin: 2px 2px;
                padding: 2px 4px;
                border: 1px solid transparent;
            }
            listbox row:selected, listbox row:selected:focus {
                background-color: #3e4451;
                border-color: #5c6370;
            }
            listbox row:selected label, listbox row:selected:focus label {
                color: #ffffff;
            }
        """)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(),
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        # HeaderBar moderna
        header = Gtk.HeaderBar()
        header.set_show_close_button(True)
        header.set_title(f"Epson Projeção Linux v{__version__}")
        header.set_subtitle("Conexão e Espelhamento Direto")
        self.set_titlebar(header)

        # Botão atualizar status
        btn_refresh = Gtk.Button.new_from_icon_name("view-refresh-symbolic", Gtk.IconSize.BUTTON)
        btn_refresh.set_tooltip_text("Atualizar status dos projetores")
        btn_refresh.connect("clicked", lambda w: self.refresh_projectors_async())
        header.pack_start(btn_refresh)

        # Botão adicionar projetor
        btn_add = Gtk.Button.new_from_icon_name("list-add-symbolic", Gtk.IconSize.BUTTON)
        btn_add.set_tooltip_text("Adicionar projetor manualmente por IP")
        btn_add.connect("clicked", self.on_add_projector_dialog)
        header.pack_start(btn_add)

        # Botão editar projetor (Nome / IP)
        self.btn_edit = Gtk.Button.new_from_icon_name("document-edit-symbolic", Gtk.IconSize.BUTTON)
        self.btn_edit.set_tooltip_text("Editar nome e IP do projetor selecionado")
        self.btn_edit.set_sensitive(False)
        self.btn_edit.connect("clicked", self.on_edit_projector_dialog)
        header.pack_start(self.btn_edit)

        # Botão remover projetor
        self.btn_remove = Gtk.Button.new_from_icon_name("list-remove-symbolic", Gtk.IconSize.BUTTON)
        self.btn_remove.set_tooltip_text("Remover projetor selecionado da lista")
        self.btn_remove.set_sensitive(False)
        self.btn_remove.connect("clicked", self.on_remove_projector_dialog)
        header.pack_start(self.btn_remove)

        # Botão de informações importantes (Standby / Dicas)
        btn_info = Gtk.Button.new_from_icon_name("dialog-information-symbolic", Gtk.IconSize.BUTTON)
        btn_info.set_tooltip_text("Dicas importantes sobre Standby e Modo de Comunicação")
        btn_info.connect("clicked", self.on_info_dialog)
        header.pack_end(btn_info)

        # Conteúdo principal
        main_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        main_vbox.set_margin_start(14)
        main_vbox.set_margin_end(14)
        main_vbox.set_margin_top(12)
        main_vbox.set_margin_bottom(14)
        self.add(main_vbox)

        # Título da lista
        lbl_list_title = Gtk.Label()
        lbl_list_title.set_markup("<b>Projetores Cadastrados na Rede:</b>")
        lbl_list_title.set_halign(Gtk.Align.START)
        main_vbox.pack_start(lbl_list_title, False, False, 0)

        # ScrolledWindow com ListBox para projetores
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_min_content_height(200)
        main_vbox.pack_start(scroll, True, True, 0)

        self.listbox = Gtk.ListBox()
        self.listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.listbox.connect("row-selected", self.on_row_selected)
        self.listbox.connect("row-activated", lambda lb, row: self.on_edit_projector_dialog(None))
        scroll.add(self.listbox)

        # Seletor de Monitor
        hbox_monitor = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        main_vbox.pack_start(hbox_monitor, False, False, 0)

        lbl_mon = Gtk.Label(label="Monitor a Projetar:")
        hbox_monitor.pack_start(lbl_mon, False, False, 0)

        self.combo_monitors = Gtk.ComboBoxText()
        monitors = ScreenCapturer.get_monitors()
        active_idx = 0
        for i, m in enumerate(monitors):
            self.combo_monitors.append_text(m["name"])
            if m.get("is_primary"):
                active_idx = i
        if monitors:
            self.combo_monitors.set_active(active_idx)
        hbox_monitor.pack_start(self.combo_monitors, True, True, 0)

        # Seletor de Qualidade de Imagem
        hbox_res = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        main_vbox.pack_start(hbox_res, False, False, 0)

        lbl_res = Gtk.Label(label="Qualidade de Imagem:")
        hbox_res.pack_start(lbl_res, False, False, 0)

        self.combo_resolutions = Gtk.ComboBoxText()
        self.res_options = [
            ("high", "Alta Nitidez (Texto & Planilhas — Recomendado)"),
            ("balanced", "Equilibrado (Padrão — JPEG 80)"),
            ("low", "Modo Leve (Rede Wi-Fi Lenta — Fluidez Máxima)"),
        ]
        for key, label in self.res_options:
            self.combo_resolutions.append_text(label)
        self.combo_resolutions.set_active(0)  # Padrão: Alta Nitidez
        hbox_res.pack_start(self.combo_resolutions, True, True, 0)

        # Barra de status informativa
        self.lbl_info = Gtk.Label(label="Selecione um projetor para conectar.")
        self.lbl_info.set_halign(Gtk.Align.START)
        main_vbox.pack_start(self.lbl_info, False, False, 0)

        # Linha inferior de botões principais
        hbox_bottom = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        main_vbox.pack_start(hbox_bottom, False, False, 0)

        # Botão Ligar/Standby
        self.btn_pwr = Gtk.Button(label="⚡ Ligar / Desligar")
        self.btn_pwr.set_sensitive(False)
        self.btn_pwr.connect("clicked", self.on_toggle_power)
        hbox_bottom.pack_start(self.btn_pwr, False, False, 0)

        # Botão Conectar e Projetar
        self.btn_connect = Gtk.Button(label="▶ Conectar e Projetar")
        self.btn_connect.get_style_context().add_class("suggested-action")
        self.btn_connect.set_sensitive(False)
        self.btn_connect.connect("clicked", self.on_connect_clicked)
        hbox_bottom.pack_end(self.btn_connect, True, True, 0)

        self.refresh_projectors_async()

        # Atualização automática contínua em segundo plano a cada 1 segundo
        GLib.timeout_add_seconds(1, self.auto_refresh_tick)

    def auto_refresh_tick(self) -> bool:
        """Chamado a cada 1s para atualizar o status dos projetores em tempo real."""
        if self.is_visible() and not self.session and not self._refreshing:
            self.refresh_projectors_async(silent=True)
        return True

    def refresh_projectors_async(self, silent: bool = False):
        """Atualiza a lista de projetores e status em segundo plano."""
        if self._refreshing:
            return
        self._refreshing = True
        if not silent:
            self.lbl_info.set_text("Verificando status dos projetores na rede...")
        
        def run_thread():
            try:
                raw_projs = get_projectors()
                updated = update_all_projector_statuses(raw_projs)
                now = time.time()
                for item in updated:
                    ip = item.get("ip")
                    trans = self._transient_power_states.get(ip)
                    if trans:
                        if now < trans["expires"]:
                            current_probed_pwr = item.get("power")
                            if trans["state"] == "STARTING":
                                if current_probed_pwr in ("WARMUP", "ON", "BUSY"):
                                    self._transient_power_states.pop(ip, None)
                                else:
                                    item["power"] = "STARTING"
                            elif trans["state"] == "COOLDOWN":
                                if current_probed_pwr in ("STANDBY", "OFFLINE"):
                                    self._transient_power_states.pop(ip, None)
                                else:
                                    item["power"] = "COOLDOWN"
                        else:
                            self._transient_power_states.pop(ip, None)
                GLib.idle_add(self.populate_projector_list, updated, silent)
            finally:
                self._refreshing = False

        threading.Thread(target=run_thread, daemon=True).start()

    @staticmethod
    def _get_status_visuals(p: dict) -> tuple[str, str]:
        """Retorna a cor (hex) e a descrição textual do status do projetor."""
        pwr = p.get("power", "OFFLINE")
        if pwr in ("BUSY", "ACTIVE_EASYMP") or p.get("is_busy"):
            return "#9b59b6", "Em Uso (Ocupado)"  # Roxo / Púrpura vibrante (alto contraste, não confunde com azul nem cinza)
        elif pwr == "ON":
            return "#27ae60", "Ligado (Livre)"    # Verde esmeralda vibrante
        elif pwr == "STANDBY":
            return "#f39c12", "Em Espera (Standby)"  # Âmbar / Laranja
        elif pwr == "STARTING":
            return "#3498db", "Iniciando... (Aguarde)"  # Azul vibrante (transição suave para WARMUP/ON)
        elif pwr == "WARMUP":
            return "#e67e22", "Aquecendo... (Aguarde)"  # Laranja escuro
        elif pwr == "COOLDOWN":
            return "#95a5a6", "Esfriando... (Aguarde)"  # Cinza claro
        else:
            return "#e74c3c", "Desconectado"       # Vermelho

    def populate_projector_list(self, projectors: list, silent: bool = False):
        existing_rows = self.listbox.get_children()
        existing_ips = [getattr(r, "proj_ip", None) for r in existing_rows]
        new_ips = [p.get("ip") for p in projectors]

        # 1. ATUALIZAÇÃO EM-LUGAR: Se os projetores forem os mesmos, atualiza apenas os textos e cores.
        # Evita recriar widgets e evita desmarcar/remarcar a seleção, eliminando 100% do piscar (flicker)!
        if len(existing_rows) == len(projectors) and existing_ips == new_ips:
            for row, p in zip(existing_rows, projectors):
                dot_color, status_txt = self._get_status_visuals(p)
                icon_markup = f"<span foreground='{dot_color}' font_desc='20'>●</span>"
                name_markup = f"<b>{p['name']}</b> ({p['ip']})"
                sub_markup = f"Status: <span foreground='{dot_color}'><b>{status_txt}</b></span>"

                if getattr(row, "_last_icon", None) != icon_markup:
                    row.lbl_icon.set_markup(icon_markup)
                    row._last_icon = icon_markup
                if getattr(row, "_last_name", None) != name_markup:
                    row.lbl_name.set_markup(name_markup)
                    row._last_name = name_markup
                if getattr(row, "_last_sub", None) != sub_markup:
                    row.lbl_sub.set_markup(sub_markup)
                    row._last_sub = sub_markup

            self.projectors_data = projectors
            if not silent:
                self.lbl_info.set_text("Pronto. Selecione o projetor e clique em Conectar.")
            return

        # 2. RECONSTRUÇÃO: Quando projetores são adicionados ou removidos da lista
        prev_ip = None
        if 0 <= self.selected_proj_index < len(self.projectors_data):
            prev_ip = self.projectors_data[self.selected_proj_index].get("ip")

        self.projectors_data = projectors
        for child in existing_rows:
            self.listbox.remove(child)

        target_row_idx = 0
        for i, p in enumerate(projectors):
            if prev_ip and p.get("ip") == prev_ip:
                target_row_idx = i

            row = Gtk.ListBoxRow()
            row.proj_ip = p.get("ip")
            hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            hbox.set_margin_start(10)
            hbox.set_margin_end(10)
            hbox.set_margin_top(8)
            hbox.set_margin_bottom(8)
            row.add(hbox)

            dot_color, status_txt = self._get_status_visuals(p)
            icon_markup = f"<span foreground='{dot_color}' font_desc='20'>●</span>"
            name_markup = f"<b>{p['name']}</b> ({p['ip']})"
            sub_markup = f"Status: <span foreground='{dot_color}'><b>{status_txt}</b></span>"

            lbl_icon = Gtk.Label()
            lbl_icon.set_markup(icon_markup)
            lbl_icon.set_margin_start(4)
            lbl_icon.set_margin_end(6)
            lbl_icon.set_valign(Gtk.Align.CENTER)
            hbox.pack_start(lbl_icon, False, False, 0)

            vbox_text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            lbl_name = Gtk.Label()
            lbl_name.set_markup(name_markup)
            lbl_name.set_halign(Gtk.Align.START)
            vbox_text.pack_start(lbl_name, False, False, 0)

            lbl_sub = Gtk.Label()
            lbl_sub.set_markup(sub_markup)
            lbl_sub.set_halign(Gtk.Align.START)
            vbox_text.pack_start(lbl_sub, False, False, 0)

            hbox.pack_start(vbox_text, True, True, 0)

            row.lbl_icon = lbl_icon
            row.lbl_name = lbl_name
            row.lbl_sub = lbl_sub
            row._last_icon = icon_markup
            row._last_name = name_markup
            row._last_sub = sub_markup

            self.listbox.add(row)

        self.listbox.show_all()
        if projectors:
            self.listbox.select_row(self.listbox.get_row_at_index(target_row_idx))
        if not silent:
            self.lbl_info.set_text("Pronto. Selecione o projetor e clique em Conectar.")

    def on_row_selected(self, listbox, row):
        if row is None:
            self.btn_connect.set_sensitive(False)
            self.btn_pwr.set_sensitive(False)
            self.btn_edit.set_sensitive(False)
            self.btn_remove.set_sensitive(False)
            self.selected_proj_index = -1
            return
        self.selected_proj_index = row.get_index()
        self.btn_connect.set_sensitive(True)
        self.btn_pwr.set_sensitive(True)
        self.btn_edit.set_sensitive(True)
        self.btn_remove.set_sensitive(True)

    def on_toggle_power(self, widget):
        if self.selected_proj_index < 0 or self.selected_proj_index >= len(self.projectors_data):
            return
        p = self.projectors_data[self.selected_proj_index]
        client = ProjectorSession(p["ip"], p["name"]).escvp
        curr_pwr = p.get("power")
        new_state = (curr_pwr != "ON")
        action_name = "ligar" if new_state else "desligar"
        self.btn_pwr.set_sensitive(False)

        if new_state:
            self._transient_power_states[p["ip"]] = {
                "state": "STARTING",
                "expires": time.time() + 12.0
            }
            p["power"] = "STARTING"
            self.lbl_info.set_text(f"Iniciando {p['name']}... Aguarde o aquecimento da lâmpada.")
        else:
            self._transient_power_states[p["ip"]] = {
                "state": "COOLDOWN",
                "expires": time.time() + 10.0
            }
            p["power"] = "COOLDOWN"
            self.lbl_info.set_text(f"Desligando {p['name']}... Aguarde o resfriamento.")

        # Atualiza a lista visual imediatamente
        self.populate_projector_list(self.projectors_data, silent=True)

        def run_pwr():
            try:
                if client.connect():
                    client.set_power(new_state)
                    client.close()
                    # Aguarda 2s para o projetor registrar o novo estado
                    time.sleep(2.0)
            except Exception as e:
                log.warning(f"Erro ao alterar energia: {e}")
            finally:
                GLib.idle_add(self.refresh_projectors_async, True)
                GLib.idle_add(lambda: self.btn_pwr.set_sensitive(True))

        threading.Thread(target=run_pwr, daemon=True).start()

    def on_connect_clicked(self, widget):
        """
        Ao clicar em Conectar:
        1. Oculta a janela principal.
        2. Inicia o streaming para o projetor selecionado.
        3. Abre a mini barra flutuante no canto da tela.
        """
        if self.selected_proj_index < 0 or self.selected_proj_index >= len(self.projectors_data):
            return
        p = self.projectors_data[self.selected_proj_index]

        # Se o projetor já estiver em uso por outro usuário, avisa e pede confirmação antes de assumir
        if p.get("power") in ("BUSY", "ACTIVE_EASYMP") or p.get("is_busy"):
            dialog = Gtk.MessageDialog(
                transient_for=self,
                flags=0,
                message_type=Gtk.MessageType.QUESTION,
                buttons=Gtk.ButtonsType.OK_CANCEL,
                text="Projetor já está em uso!"
            )
            dialog.format_secondary_text(
                f"O projetor '{p['name']}' já está sendo utilizado por outro computador na rede.\n\n"
                "Se você conectar agora, a transmissão do outro usuário será interrompida e você assumirá a projeção.\n\n"
                "Deseja assumir o controle do projetor agora?"
            )
            dialog.set_title("Confirmar Assumir Projeção")
            response = dialog.run()
            dialog.destroy()
            if response != Gtk.ResponseType.OK:
                return  # Usuário desistiu de assumir

        mon_idx = self.combo_monitors.get_active()
        if mon_idx < 0:
            mon_idx = 0

        res_idx = self.combo_resolutions.get_active()
        if res_idx < 0:
            res_idx = 0
        profile_key = self.res_options[res_idx][0]

        if profile_key == "high":
            quality_val = 90
            fps_val = 20
        elif profile_key == "low":
            quality_val = 70
            fps_val = 15
        else:
            quality_val = 80
            fps_val = 20

        self.btn_connect.set_sensitive(False)
        self.lbl_info.set_text(f"Iniciando projeção para {p['name']} ({p['ip']})...")

        self.session = ProjectorSession(
            p["ip"],
            p["name"],
            mac=p.get("mac", ""),
            monitor_index=mon_idx,
            fps=fps_val,
            quality=quality_val,
            width=1024,
            height=768
        )

        def connect_thread():
            try:
                ok, msg = self.session.start(on_status_change=lambda s: GLib.idle_add(self.lbl_info.set_text, s))
                if ok:
                    GLib.idle_add(self.enter_projection_mode)
                else:
                    GLib.idle_add(self.handle_connection_failed, msg)
            except Exception as e:
                log.exception(f"Erro inesperado durante a conexão: {e}")
                GLib.idle_add(self.handle_connection_failed, str(e))

        threading.Thread(target=connect_thread, daemon=True).start()

    def enter_projection_mode(self):
        """Oculta a janela principal e exibe a mini barra flutuante."""
        try:
            self.hide()
            self.floating_toolbar = FloatingToolbar(
                session=self.session,
                on_disconnect_callback=self.exit_projection_mode,
                on_remote_takeover_callback=self.handle_remote_takeover
            )
            if self.on_session_start_cb:
                self.on_session_start_cb(self.session)
        except Exception as e:
            log.exception(f"Erro ao exibir barra de projeção: {e}")
            self.show_all()
            self.handle_connection_failed(f"Falha ao exibir barra de projeção: {e}")

    def handle_remote_takeover(self, reason: str):
        """Chamado quando a sessão é encerrada remotamente (projetor desligado ou outro usuário assumiu)."""
        proj_name = self.session.name if self.session else "Projetor"
        self.floating_toolbar = None
        self.session = None
        self.btn_connect.set_sensitive(True)
        self.show_all()
        self.present()
        self.refresh_projectors_async()
        if self.on_session_stop_cb:
            self.on_session_stop_cb()

        if reason == "POWER_OFF":
            self.lbl_info.set_text(f"O projetor '{proj_name}' foi desligado.")
            dialog = Gtk.MessageDialog(
                transient_for=self,
                flags=0,
                message_type=Gtk.MessageType.INFO,
                buttons=Gtk.ButtonsType.OK,
                text="Projetor Desligado"
            )
            dialog.format_secondary_text(
                f"O projetor '{proj_name}' foi desligado ou colocado em modo de espera (Standby).\n\n"
                "A transmissão de tela foi encerrada com sucesso."
            )
            dialog.set_title("Projetor Desligado")
            dialog.run()
            dialog.destroy()
        else:
            self.lbl_info.set_text("Projeção assumida por outro usuário.")
            dialog = Gtk.MessageDialog(
                transient_for=self,
                flags=0,
                message_type=Gtk.MessageType.WARNING,
                buttons=Gtk.ButtonsType.OK,
                text="Projeção Desconectada"
            )
            dialog.format_secondary_text(
                f"Alguém na rede conectou e assumiu a sessão do projetor '{proj_name}'!\n\n"
                "A sua transmissão de tela foi interrompida para dar lugar ao novo usuário."
            )
            dialog.set_title("Sessão Assumida por Outro Usuário")
            dialog.run()
            dialog.destroy()

    def exit_projection_mode(self):
        """Ao desconectar da mini barra: fecha a mini barra e restaura a janela principal."""
        self.floating_toolbar = None
        self.session = None
        self.btn_connect.set_sensitive(True)
        self.lbl_info.set_text("Projeção encerrada.")
        self.show_all()
        self.present()
        self.refresh_projectors_async()
        if self.on_session_stop_cb:
            self.on_session_stop_cb()

    def handle_connection_failed(self, error_msg: str):
        self.btn_connect.set_sensitive(True)
        self.lbl_info.set_text(f"Erro: {error_msg}")
        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=0,
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.OK,
            text="Falha na Conexão com o Projetor"
        )
        dialog.format_secondary_text(error_msg)
        dialog.run()
        dialog.destroy()

    def on_add_projector_dialog(self, widget):
        dialog = Gtk.Dialog(
            title="Adicionar Novo Projetor",
            transient_for=self,
            flags=0,
            buttons=(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OK, Gtk.ResponseType.OK)
        )
        box = dialog.get_content_area()
        box.set_spacing(8)
        box.set_margin_start(12)
        box.set_margin_end(12)
        box.set_margin_top(12)
        box.set_margin_bottom(12)

        lbl1 = Gtk.Label(label="Nome do Projetor (ex: Sala de Reunião):")
        lbl1.set_halign(Gtk.Align.START)
        box.add(lbl1)
        entry_name = Gtk.Entry()
        box.add(entry_name)

        lbl2 = Gtk.Label(label="Endereço IP (ex: 192.168.1.101):")
        lbl2.set_halign(Gtk.Align.START)
        box.add(lbl2)
        entry_ip = Gtk.Entry()
        box.add(entry_ip)

        dialog.show_all()
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            name = entry_name.get_text().strip()
            ip = entry_ip.get_text().strip()
            if name and ip:
                add_or_update_projector(name, ip)
                self.refresh_projectors_async()
        dialog.destroy()

    def on_edit_projector_dialog(self, widget):
        """Abre caixa de diálogo para editar o nome ou IP do projetor selecionado."""
        if self.selected_proj_index < 0 or self.selected_proj_index >= len(self.projectors_data):
            return
        p = self.projectors_data[self.selected_proj_index]
        orig_ip = p.get("ip", "")
        orig_name = p.get("name", "")

        dialog = Gtk.Dialog(
            title="Editar Projetor",
            transient_for=self,
            flags=0,
            buttons=(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OK, Gtk.ResponseType.OK)
        )
        box = dialog.get_content_area()
        box.set_spacing(8)
        box.set_margin_start(16)
        box.set_margin_end(16)
        box.set_margin_top(14)
        box.set_margin_bottom(14)

        lbl1 = Gtk.Label(label="Nome do Projetor:")
        lbl1.set_halign(Gtk.Align.START)
        box.add(lbl1)
        entry_name = Gtk.Entry()
        entry_name.set_text(orig_name)
        box.add(entry_name)

        lbl2 = Gtk.Label(label="Endereço IP:")
        lbl2.set_halign(Gtk.Align.START)
        box.add(lbl2)
        entry_ip = Gtk.Entry()
        entry_ip.set_text(orig_ip)
        box.add(entry_ip)

        dialog.show_all()
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            new_name = entry_name.get_text().strip()
            new_ip = entry_ip.get_text().strip()
            if new_name and new_ip:
                update_projector_details(orig_ip, new_name, new_ip)
                self.lbl_info.set_text(f"Projetor atualizado: {new_name}")
                self.refresh_projectors_async()
        dialog.destroy()

    def on_remove_projector_dialog(self, widget):
        """Solicita confirmação e remove o projetor selecionado da lista."""
        if self.selected_proj_index < 0 or self.selected_proj_index >= len(self.projectors_data):
            return
        p = self.projectors_data[self.selected_proj_index]
        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=0,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.OK_CANCEL,
            text="Remover Projetor"
        )
        dialog.format_secondary_text(
            f"Deseja realmente remover '{p['name']}' ({p['ip']}) da lista de projetores?"
        )
        dialog.set_title("Confirmar Remoção")
        response = dialog.run()
        dialog.destroy()
        if response == Gtk.ResponseType.OK:
            remove_projector(p.get("ip", ""))
            self.lbl_info.set_text(f"Projetor '{p['name']}' removido.")
            self.refresh_projectors_async()

    def on_info_dialog(self, widget):
        """Exibe pop-up explicativo sobre a configuração fundamental de Comunicação no Standby."""
        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=Gtk.DialogFlags.MODAL,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text="Instrução Importante: Modo de Espera (Standby)"
        )
        dialog.set_title("Configuração do Projetor")
        dialog.format_secondary_markup(
            "<b>Para ligar o projetor pela rede enquanto estiver em Standby:</b>\n\n"
            "É obrigatório que o projetor mantenha sua placa de rede energizada quando desligado.\n\n"
            "📌 <b>No controle remoto ou painel físico do projetor:</b>\n"
            "  1. Pressione a tecla <b>Menu</b>\n"
            "  2. Acesse <b>Modo de Espera</b> (ou <i>Operação > Modo de Espera</i>)\n"
            "  3. Ative a opção: <b>Comunic. Activada</b> (ou <i>Communication On</i>)\n\n"
            "⚠️ <i>Se estiver desativada (Modo Eco), o projetor desliga a placa de rede ao apagar a lâmpada, "
            "ficando invisível e impossibilitando o computador de ligá-lo remotamente.</i>"
        )
        dialog.run()
        dialog.destroy()
