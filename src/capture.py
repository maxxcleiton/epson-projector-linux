"""
Módulo de Captura Nativa de Tela para Linux (Sem Wine, sem flickering).
Captura a tela em alta performance com PIL / Gdk, mantendo proporção 16:9 (Letterbox)
e particionando nos 4 quadrantes nativos que a placa Epson exige.
O quadrante (0,0) é gerado por último para servir de gatilho de renderização.
"""

import time
import io
import threading
import logging
import ctypes
from typing import Callable, Optional

# Inicializa XInitThreads para garantir segurança em background threads no X11
_libx11 = None
_xfixes = None
try:
    _libx11 = ctypes.cdll.LoadLibrary("libX11.so.6")
    _libx11.XInitThreads()
except Exception:
    pass

class XFixesCursorImage(ctypes.Structure):
    _fields_ = [
        ("x", ctypes.c_short),
        ("y", ctypes.c_short),
        ("width", ctypes.c_ushort),
        ("height", ctypes.c_ushort),
        ("xhot", ctypes.c_ushort),
        ("yhot", ctypes.c_ushort),
        ("cursor_serial", ctypes.c_ulong),
        ("pixels", ctypes.POINTER(ctypes.c_ulong)),
        ("atom", ctypes.c_ulong),
        ("name", ctypes.c_char_p),
    ]

try:
    _xfixes = ctypes.cdll.LoadLibrary("libXfixes.so.3")
    if _libx11:
        _libx11.XOpenDisplay.restype = ctypes.c_void_p
        _libx11.XCloseDisplay.argtypes = [ctypes.c_void_p]
        _libx11.XFree.argtypes = [ctypes.c_void_p]
    _xfixes.XFixesGetCursorImage.restype = ctypes.POINTER(XFixesCursorImage)
    _xfixes.XFixesGetCursorImage.argtypes = [ctypes.c_void_p]
except Exception as e:
    pass

from PIL import Image, ImageGrab, ImageDraw
import gi
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk

log = logging.getLogger(__name__)

CANVAS_W, CANVAS_H = 1024, 768
HALF_W, HALF_H = 512, 384

# Compatibilidade retroativa com Pillow antigo (< 9.1 / Ubuntu 22.04) e moderno (>= 9.1)
# Utiliza filtro BICUBIC para garantir contornos nítidos e máxima legibilidade de textos
_resample_mod = getattr(Image, "Resampling", Image)
RESAMPLE_FILTER = getattr(_resample_mod, "BICUBIC", 3)

# Ordem dos quadrantes com (0,0) POR ÚLTIMO (gatilho de renderização no hardware Epson)
QUADRANTS = [
    (HALF_W, 0,      HALF_W, HALF_H, (HALF_W, 0,      CANVAS_W, HALF_H)),  # Top-Right
    (0,      HALF_H, HALF_W, HALF_H, (0,      HALF_H, HALF_W,   CANVAS_H)),# Bot-Left
    (HALF_W, HALF_H, HALF_W, HALF_H, (HALF_W, HALF_H, CANVAS_W, CANVAS_H)),# Bot-Right
    (0,      0,      HALF_W, HALF_H, (0,      0,      HALF_W,   HALF_H)),  # Top-Left ← GATILHO
]


class ScreenCapturer:
    def __init__(self, monitor_index: int = 0, fps: int = 20, quality: int = 90, canvas_w: int = 1024, canvas_h: int = 768):
        self.monitor_index = monitor_index
        self.target_fps = fps
        self.quality = quality
        self.canvas_w = canvas_w
        self.canvas_h = canvas_h
        self.half_w = canvas_w // 2
        self.half_h = canvas_h // 2

        # 4 quadrantes dinâmicos com (0,0) por último (gatilho de renderização Epson)
        self.quadrants = [
            (self.half_w, 0,           self.half_w, self.half_h, (self.half_w, 0,           self.canvas_w, self.half_h)),
            (0,           self.half_h, self.half_w, self.half_h, (0,           self.half_h, self.half_w,   self.canvas_h)),
            (self.half_w, self.half_h, self.half_w, self.half_h, (self.half_w, self.half_h, self.canvas_w, self.canvas_h)),
            (0,           0,           self.half_w, self.half_h, (0,           0,           self.half_w,   self.half_h)),
        ]

        self.running = False
        self._thread: Optional[threading.Thread] = None
        self.paused = False
        self.black_screen = False
        self._x11_display = None
        self._fallback_cursor_img: Optional[Image.Image] = None

    @staticmethod
    def get_monitors() -> list[dict]:
        """Retorna lista de monitores conectados no sistema com coordenadas e nomes."""
        display = Gdk.Display.get_default()
        if not display:
            return [{"index": 0, "name": "Tela Principal (1920x1080)", "x": 0, "y": 0, "width": 1920, "height": 1080, "is_primary": True}]

        n = display.get_n_monitors()
        monitors = []
        for i in range(n):
            mon = display.get_monitor(i)
            geom = mon.get_geometry()
            name = mon.get_model() or f"Monitor {i+1}"
            is_prim = mon.is_primary()
            suffix = " (Principal)" if is_prim else ""
            monitors.append({
                "index": i,
                "name": f"{name} ({geom.width}x{geom.height}){suffix}",
                "x": geom.x,
                "y": geom.y,
                "width": geom.width,
                "height": geom.height,
                "is_primary": is_prim,
            })
        return monitors

    def _get_capture_bbox(self) -> Optional[tuple[int, int, int, int]]:
        monitors = self.get_monitors()
        if 0 <= self.monitor_index < len(monitors):
            m = monitors[self.monitor_index]
            return (m["x"], m["y"], m["x"] + m["width"], m["y"] + m["height"])
        return None

    def fit_to_canvas(self, screen_img: Image.Image) -> tuple[Image.Image, float, int, int]:
        """Ajusta a tela ao canvas preservando a proporção original (Letterbox) e retorna métricas de escala."""
        sw, sh = screen_img.size
        scale = min(self.canvas_w / sw, self.canvas_h / sh)
        new_w = max(1, int(sw * scale))
        new_h = max(1, int(sh * scale))
        resized = screen_img.resize((new_w, new_h), RESAMPLE_FILTER)

        canvas = Image.new("RGB", (self.canvas_w, self.canvas_h), (0, 0, 0))
        paste_x = (self.canvas_w - new_w) // 2
        paste_y = (self.canvas_h - new_h) // 2
        canvas.paste(resized, (paste_x, paste_y))
        return canvas, scale, paste_x, paste_y

    def capture_screen_image(self) -> tuple[Image.Image, tuple[int, int, int, int]]:
        """
        Captura a tela do monitor selecionado de forma robusta e multiplataforma:
        Retorna: (imagem_pil, (origem_x, origem_y, largura, altura))
        """
        try:
            root = Gdk.get_default_root_window()
            if root:
                display = Gdk.Display.get_default()
                if display and display.get_n_monitors() > 0:
                    n = display.get_n_monitors()
                    idx = self.monitor_index if (0 <= self.monitor_index < n) else 0
                    mon = display.get_monitor(idx)
                    geom = mon.get_geometry()
                    x, y, w, h = geom.x, geom.y, geom.width, geom.height
                else:
                    x, y, w, h = 0, 0, root.get_width(), root.get_height()

                pixbuf = Gdk.pixbuf_get_from_window(root, x, y, w, h)
                if pixbuf:
                    pw, ph = pixbuf.get_width(), pixbuf.get_height()
                    rowstride = pixbuf.get_rowstride()
                    n_channels = pixbuf.get_n_channels()
                    mode = "RGB" if n_channels == 3 else "RGBA"
                    img = Image.frombytes(mode, (pw, ph), pixbuf.get_pixels(), "raw", mode, rowstride)
                    if mode == "RGBA":
                        img = img.convert("RGB")
                    return img, (x, y, w, h)
        except Exception as e:
            log.debug(f"Gdk capture fallback: {e}")

        # Fallback para ImageGrab
        try:
            bbox = self._get_capture_bbox()
            x1, y1 = (bbox[0], bbox[1]) if bbox else (0, 0)
            img = ImageGrab.grab(bbox=bbox)
            return img, (x1, y1, img.width, img.height)
        except Exception as e:
            log.warning(f"Erro em todos os métodos de captura de tela: {e}")

        return Image.new("RGB", (1920, 1080), (0, 0, 0)), (0, 0, 1920, 1080)

    def _get_cursor_info(self) -> Optional[tuple[Image.Image, int, int, int, int]]:
        """
        Obtém o ícone do cursor atual e suas coordenadas através da biblioteca nativa XFixes (X11).
        Fallback para Gdk se XFixes não responder.
        Retorna: (cursor_rgba_image, cursor_x, cursor_y, hotspot_x, hotspot_y)
        """
        disp = self._x11_display
        close_needed = False
        if not disp and _libx11:
            try:
                disp = _libx11.XOpenDisplay(None)
                close_needed = True
            except Exception:
                disp = None

        if disp and _xfixes and _libx11:
            try:
                cur = _xfixes.XFixesGetCursorImage(disp)
                if cur:
                    try:
                        c = cur.contents
                        w, h = c.width, c.height
                        if w > 0 and h > 0 and c.pixels:
                            arr = (ctypes.c_ulong * (w * h)).from_address(ctypes.addressof(c.pixels.contents))
                            raw = bytes(arr)
                            # No Linux 64-bit (x86_64), c_ulong possui 8 bytes mas o pixel é 32-bit (CARD32).
                            # Extrai os 32 bits inferiores de cada long (evita o efeito 'pente/serrilhado' vazado).
                            if ctypes.sizeof(ctypes.c_ulong) == 8:
                                raw_32 = bytes(memoryview(raw).cast("I")[0::2])
                            else:
                                raw_32 = raw
                            img = Image.frombytes("RGBA", (w, h), raw_32, "raw", "BGRA")
                            return img, c.x, c.y, c.xhot, c.yhot
                    finally:
                        _libx11.XFree(cur)
            except Exception as e:
                log.debug(f"XFixes get cursor error: {e}")
            finally:
                if close_needed and _libx11:
                    try:
                        _libx11.XCloseDisplay(disp)
                    except Exception:
                        pass

        # Fallback para Gdk
        try:
            display = Gdk.Display.get_default()
            if display:
                seat = display.get_default_seat()
                if seat:
                    pointer = seat.get_pointer()
                    if pointer:
                        _, px, py = pointer.get_position()
                        if not self._fallback_cursor_img:
                            self._fallback_cursor_img = self._create_fallback_cursor()
                        return self._fallback_cursor_img, px, py, 0, 0
        except Exception:
            pass

        return None

    @staticmethod
    def _create_fallback_cursor() -> Image.Image:
        """Cria um cursor padrão (seta branca com borda preta nítida)."""
        img = Image.new("RGBA", (24, 24), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        points = [(0, 0), (0, 18), (5, 14), (9, 22), (12, 21), (8, 13), (14, 13)]
        draw.polygon(points, fill=(255, 255, 255, 255), outline=(0, 0, 0, 255))
        return img

    def draw_cursor(self, canvas: Image.Image, scale: float, paste_x: int, paste_y: int, mx: int, my: int, mw: int, mh: int):
        """Desenha a seta/ícone do mouse sobre o canvas projetado mantendo alinhamento pixel-perfect."""
        cur_info = self._get_cursor_info()
        if not cur_info:
            return

        cur_img, cx, cy, xhot, yhot = cur_info
        # Apenas desenha se o cursor estiver dentro das coordenadas do monitor que está sendo transmitido
        if not (mx <= cx < mx + mw and my <= cy < my + mh):
            return

        # Posição proporcional mapeada para o canvas projetado
        target_x = paste_x + int((cx - mx) * scale) - xhot
        target_y = paste_y + int((cy - my) * scale) - yhot

        try:
            canvas.paste(cur_img, (target_x, target_y), cur_img)
        except Exception as e:
            log.debug(f"Erro ao colar cursor no canvas: {e}")

    def capture_tiles(self) -> list[tuple[int, int, int, int, bytes]]:
        """
        Captura a tela, desenha o cursor do mouse, ajusta para letterbox
        e fatia nos 4 quadrantes Epson com (0,0) por último.
        """
        if self.black_screen:
            canvas = Image.new("RGB", (self.canvas_w, self.canvas_h), (0, 0, 0))
        else:
            screen, (mx, my, mw, mh) = self.capture_screen_image()
            canvas, scale, paste_x, paste_y = self.fit_to_canvas(screen)
            self.draw_cursor(canvas, scale, paste_x, paste_y, mx, my, mw, mh)

        tiles_data = []
        for tx, ty, tw, th, crop_box in self.quadrants:
            tile_img = canvas.crop(crop_box)
            bio = io.BytesIO()
            tile_img.save(bio, format="JPEG", quality=self.quality)
            tiles_data.append((tx, ty, tw, th, bio.getvalue()))

        return tiles_data

    def start_streaming(self, on_frame: Callable[[list[tuple[int, int, int, int, bytes]]], None]):
        """Inicia o loop contínuo de captura e entrega de tiles."""
        self.running = True
        self.paused = False

        def loop():
            # Abre conexão dedicada X11 para consulta de alta velocidade do cursor nesta thread
            if _libx11:
                try:
                    self._x11_display = _libx11.XOpenDisplay(None)
                except Exception as e:
                    log.debug(f"Erro abrindo XOpenDisplay dedicado: {e}")
                    self._x11_display = None

            interval = 1.0 / max(1, self.target_fps)
            try:
                while self.running:
                    t0 = time.time()
                    if not self.paused:
                        try:
                            tiles = self.capture_tiles()
                            on_frame(tiles)
                        except Exception as e:
                            log.warning(f"Erro processando frame: {e}")
                    elapsed = time.time() - t0
                    sleep_time = interval - elapsed
                    if sleep_time > 0:
                        time.sleep(sleep_time)
            finally:
                if self._x11_display and _libx11:
                    try:
                        _libx11.XCloseDisplay(self._x11_display)
                    except Exception:
                        pass
                    self._x11_display = None

        self._thread = threading.Thread(target=loop, daemon=True)
        self._thread.start()

    def set_pause(self, paused: bool):
        self.paused = paused

    def set_black_screen(self, black: bool):
        self.black_screen = black

    def stop_streaming(self):
        self.running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._thread = None
