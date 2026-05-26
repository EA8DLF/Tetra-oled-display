#!/usr/bin/env python3
# ═══════════════════════════════════════════════════════════════
#  TETRA OLED Display — generador de vistas previas (emulador)
#  Jose Maria - EA8DLF
# ═══════════════════════════════════════════════════════════════
# Ejecuta el codigo REAL de tetra_oled.py contra dispositivos OLED falsos
# que graban lo que se mostraria en pantalla, y genera un montaje PNG con
# todas las pantallas (arranque, standby, voz, SDS...) para cada modelo.
#
#   python Docs/preview/preview.py
#
# No toca hardware ni necesita luma/adafruit instalados: solo Pillow.
#   pip install pillow
import sys, os, types
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", "..", "tetra_oled.py"))
OUT  = HERE

# ── Fuentes monoespaciadas: DejaVu en Linux/Pi, Consolas en Windows ──
def find_mono(bold):
    for c in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono%s.ttf" % ("-Bold" if bold else ""),
        os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts",
                     "consolab.ttf" if bold else "consola.ttf"),
    ):
        if os.path.exists(c):
            return c
    return None

import PIL.ImageFont as IF
_orig_tt = IF.truetype
def _patched_tt(font=None, size=10, *a, **k):
    # Si el codigo pide DejaVu y no esta (p.ej. en Windows), usa otra mono
    if isinstance(font, str) and "DejaVuSansMono" in font and not os.path.exists(font):
        alt = find_mono("Bold" in font)
        if alt:
            font = alt
    return _orig_tt(font, size, *a, **k)
IF.truetype = _patched_tt

def label_font(size, bold=False):
    p = find_mono(bold)
    return ImageFont.truetype(p, size) if p else ImageFont.load_default()

# ── Dispositivos falsos que graban la ultima imagen mostrada ──
class RecLuma:          # emula un device de luma.oled (SH1107 / SSD1327)
    def __init__(self, mode, size): self.mode, self.size, self.last = mode, size, None
    def display(self, img): self.last = img.copy()
    def contrast(self, v): pass
    def show(self): pass
    def hide(self): pass

class RecAdafruit:      # emula adafruit_ssd1306.SSD1306_I2C (framebuf)
    def __init__(self, w, h): self.size = (w, h); self._buf = None; self.last = None
    def image(self, img): self._buf = img
    def show(self):
        if self._buf is not None: self.last = self._buf.copy()
    def fill(self, c): self._buf = Image.new("1", self.size, c)
    def contrast(self, v): pass
    def poweron(self): pass
    def poweroff(self): pass

def install_fakes():
    def mod(name):
        m = types.ModuleType(name); m.__path__ = []; sys.modules[name] = m; return m
    mod("luma"); mod("luma.core"); mod("luma.core.interface")
    ser = mod("luma.core.interface.serial"); ser.i2c = lambda *a, **k: object()
    mod("luma.oled")
    dev = mod("luma.oled.device")
    dev.ssd1327 = lambda serial=None, width=128, height=128, **k: RecLuma("RGB", (width, height))
    dev.sh1107  = lambda serial=None, width=128, height=128, **k: RecLuma("1",   (width, height))
    b = mod("board"); b.SCL = 0; b.SDA = 1
    bu = mod("busio"); bu.I2C = lambda *a, **k: object()
    ada = mod("adafruit_ssd1306"); ada.SSD1306_I2C = lambda w, h, i2c, **k: RecAdafruit(w, h)

def load_module(display_type):
    src = open(REPO, "r", encoding="utf-8").read()
    src = src.replace('DISPLAY_TYPE         = "SSD1306"',
                      'DISPLAY_TYPE         = "%s"' % display_type, 1)
    g = {"__name__": "tetra_preview"}
    exec(compile(src, "tetra_oled_preview", "exec"), g)
    return g

SAMPLE_DB = {
    "2150212": {"callsign": "EA8DLF", "name": "Jose Maria",     "city": "Las Palmas", "state": "Las Palmas"},
    "2145007": {"callsign": "EA7KEN", "name": "Pedro Martinez", "city": "Sevilla",    "state": "Sevilla"},
}
SAMPLE_STATS = {"cpuTemp": 33.1, "voltage": 5.0, "localIp": "192.168.1.193", "publicIp": ""}

def render_screens(display_type):
    g = load_module(display_type)
    g["radioid_db"] = dict(SAMPLE_DB)
    g["stats"].clear(); g["stats"].update(SAMPLE_STATS)
    oled = g["oled"]
    dev = oled.device if hasattr(oled, "device") else oled  # adaptador luma vs adafruit
    def grab():
        return dev.last if dev.last is not None else Image.new("RGB", (g["WIDTH"], g["HEIGHT"]), "black")
    shots = []
    g["show_splash"]("Iniciando...");                                shots.append(("Arranque", grab()))
    g["show_standby"]();                                             shots.append(("Standby", grab()))
    g["show_event"]("2150212", "VOZ", sds_text="TG:9990");           shots.append(("Voz - Grupo", grab()))
    g["show_event"]("2150212", "VOZ PRIV", issi_dst="2145007");      shots.append(("Voz - Privada", grab()))
    g["show_event"]("2145007", "NET VOZ", sds_text="TG:214");        shots.append(("Voz de red", grab()))
    g["show_event"]("2150212", "SDS T3", sds_text="Hola QSO 73!", issi_dst="9999"); shots.append(("Mensaje SDS", grab()))
    return shots

def montage(shots, scale, cols, title, path):
    cell_w = shots[0][1].width  * scale
    cell_h = shots[0][1].height * scale
    label_h, pad, title_h = 22, 12, 34
    rows = (len(shots) + cols - 1) // cols
    W = cols * cell_w + (cols + 1) * pad
    H = title_h + rows * (cell_h + label_h + pad) + pad
    canvas = Image.new("RGB", (W, H), (30, 30, 30))
    d = ImageDraw.Draw(canvas)
    tfont, lfont = label_font(20, True), label_font(14)
    d.text((pad, 7), title, font=tfont, fill=(255, 220, 0))
    for i, (lab, img) in enumerate(shots):
        r, c = divmod(i, cols)
        x = pad + c * (cell_w + pad)
        y = title_h + r * (cell_h + label_h + pad)
        canvas.paste(img.convert("RGB").resize((cell_w, cell_h), Image.NEAREST), (x, y))
        d.rectangle((x, y, x + cell_w - 1, y + cell_h - 1), outline=(90, 90, 90))
        d.text((x, y + cell_h + 4), lab, font=lfont, fill=(200, 200, 200))
    canvas.save(path)
    print("guardado:", os.path.basename(path), canvas.size)

if __name__ == "__main__":
    install_fakes()
    montage(render_screens("SSD1327"), 3, 3, "SSD1327  -  128x128 (escala de grises)", os.path.join(OUT, "preview_ssd1327.png"))
    montage(render_screens("SH1107"),  3, 3, "SH1107  -  128x128 (monocromo)",         os.path.join(OUT, "preview_sh1107.png"))
    montage(render_screens("SSD1306"), 4, 3, "SSD1306  -  128x64 (monocromo)",          os.path.join(OUT, "preview_ssd1306.png"))
    print("OK")
