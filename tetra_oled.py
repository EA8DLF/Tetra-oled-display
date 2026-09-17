#!/usr/bin/env python3
# ═══════════════════════════════════════════════════════════════
#  TETRA OLED Display v3.5.0
#  Jose Maria - EA8DLF · 2026
#  https://github.com/EA8DLF/Tetra-oled-display
#  Pantallas: SSD1306/SSD1309/SSD1315, SH1106, SH1107 y SSD1327
# ═══════════════════════════════════════════════════════════════

import re, json, time, requests, threading, os, csv, signal, sys, math, subprocess, socket
import configparser
from collections import deque
from datetime import datetime, timedelta
from PIL import Image, ImageDraw, ImageFont

# ─── CONFIGURACIÓN ────────────────────────────────────────────
# Los valores de aquí son los de fábrica. La configuración real vive en
# /etc/tetra-oled.conf (la crea instalar.sh); así las actualizaciones no la
# tocan. Si ese archivo no existe se usan estos valores.
CONFIG_FILE = os.environ.get("TETRA_OLED_CONF", "/etc/tetra-oled.conf")

# Nombre del servicio systemd de tu bluestation / FlowStation
SERVICE_NAME         = "tmo.service"

# Tipo de pantalla:
#   "AUTO"    → detecta el controlador leyendo su registro de estado
#   "SSD1306" → 0.96" 128x64 / 0.91" 128x32 (también SSD1309, SSD1315)
#   "SH1106"  → 1.3" 128x64
#   "SH1107"  → 1.5" 128x128 (Hailege y similares)
#   "SSD1327" → 1.5" 128x128 escala de grises (ZJY-M150 y similares)
DISPLAY_TYPE         = "SSD1306"

# Dirección I2C (0x3C normalmente, algunas usan 0x3D). 0 = buscar sola.
DISPLAY_ADDR         = 0x3C

# Bus I2C (/dev/i2c-N). En Raspberry Pi es el 1 (pines 3 y 5)
I2C_BUS              = 1

# Resolución (0 = la habitual del modelo) y giro (0, 90, 180, 270)
DISPLAY_WIDTH        = 0
DISPLAY_HEIGHT       = 0
DISPLAY_ROTATE       = 0

# Modo de datos:
#   "monitor"    → usa TetraPack Monitor (necesita MONITOR_URL)
#   "journalctl" → lee directamente del servicio systemd (sin dashboard)
DATA_MODE            = "monitor"

# URL del TetraPack Monitor (solo si DATA_MODE = "monitor")
MONITOR_URL          = "http://localhost:5000"

# ISSI de tu terminal local (para priorizar tu TG)
LOCAL_ISSI           = "0"

# Tiempos de visualización (segundos)
DISPLAY_TIMEOUT      = 30   # sin actividad → reposo
CALL_MIN_DISPLAY     = 5    # mínimo en pantalla para llamadas cortas
SDS_DISPLAY          = 5    # SDS en pantalla
SCREEN_OFF_TIMEOUT   = 0    # reposo → apagar pantalla (0 = nunca)

# Pantalla de reposo: "scroll" (reloj + últimos oídos desplazándose) o "clock"
IDLE_MODE            = "scroll"

# Brillo 0-255 con actividad y en reposo
BRIGHTNESS           = 255
IDLE_BRIGHTNESS      = 50

# Título de la pantalla de reposo
TITLE                = "TETRA Monitor"

# Descargar la base de datos de RadioID (indicativo y nombre). "no" la desactiva.
RADIOID              = "yes"
# ──────────────────────────────────────────────────────────────


CONFIG_KEYS = ("SERVICE_NAME", "DISPLAY_TYPE", "DISPLAY_ADDR", "I2C_BUS", "DISPLAY_WIDTH",
               "DISPLAY_HEIGHT", "DISPLAY_ROTATE", "DATA_MODE", "MONITOR_URL", "LOCAL_ISSI",
               "DISPLAY_TIMEOUT", "CALL_MIN_DISPLAY", "SDS_DISPLAY", "SCREEN_OFF_TIMEOUT",
               "IDLE_MODE", "BRIGHTNESS", "IDLE_BRIGHTNESS", "TITLE", "RADIOID")


def load_config():
    """Aplica /etc/tetra-oled.conf (sección [oled]) sobre los valores de fábrica."""
    g = globals()
    cp = configparser.ConfigParser()
    try:
        if not cp.read(CONFIG_FILE, encoding="utf-8") or not cp.has_section("oled"):
            return
    except Exception as e:
        print(f"[config] No se pudo leer {CONFIG_FILE}: {e}", flush=True)
        return
    sec = cp["oled"]
    ints = ("DISPLAY_ADDR", "I2C_BUS", "DISPLAY_WIDTH", "DISPLAY_HEIGHT", "DISPLAY_ROTATE", "DISPLAY_TIMEOUT",
            "CALL_MIN_DISPLAY", "SDS_DISPLAY", "SCREEN_OFF_TIMEOUT", "BRIGHTNESS", "IDLE_BRIGHTNESS")
    for key in list(sec.keys()):
        name = key.upper()
        if name not in CONFIG_KEYS:
            print(f"[config] Clave desconocida ignorada: {key}", flush=True)
            continue
        raw = sec.get(key).strip().strip('"')
        if name in ints:
            try:
                g[name] = int(raw, 0)
            except ValueError:
                print(f"[config] Valor no válido para {key}: {raw}", flush=True)
        else:
            g[name] = raw
    print(f"[config] Leída {CONFIG_FILE}", flush=True)


load_config()
DISPLAY_TYPE = DISPLAY_TYPE.upper()
DATA_MODE = DATA_MODE.lower()
IDLE_MODE = IDLE_MODE.lower()
LOCAL_ISSI = str(LOCAL_ISSI).strip()
BRIGHTNESS = max(0, min(255, BRIGHTNESS))
IDLE_BRIGHTNESS = max(0, min(255, IDLE_BRIGHTNESS))
if DISPLAY_ROTATE not in (0, 90, 180, 270):
    print(f"[config] Giro {DISPLAY_ROTATE} no válido; se usa 0", flush=True)
    DISPLAY_ROTATE = 0

# URLs derivadas
API_URL   = f"{MONITOR_URL}/api/log-stream"
STATS_URL = f"{MONITOR_URL}/api/system/stats"

# ─── DETECCIÓN DEL CONTROLADOR ────────────────────────────────
# Mismo método que OneBitDisplay (bitbank2): se lee el registro de estado.
# Quitando el bit 6 (pantalla encendida): 0x03/0x06 = SSD1306, 0x08 = SH1106,
# 0x07/0x0F = SH1107. El SSD1327 no permite leer por I2C.
I2C_SLAVE = 0x0703


def i2c_probe(addr):
    """Devuelve (presente, byte_de_estado_o_None) sin inicializar nada."""
    try:
        import fcntl
    except ImportError:
        return False, None
    try:
        fd = os.open(f"/dev/i2c-{I2C_BUS}", os.O_RDWR)
    except OSError:
        return False, None
    try:
        fcntl.ioctl(fd, I2C_SLAVE, addr)
        os.write(fd, bytes([0x00, 0xE3]))  # NOP: comprueba que alguien responde
    except OSError:
        os.close(fd)
        return False, None
    try:
        status = os.read(fd, 1)[0]
    except OSError:
        status = None
    os.close(fd)
    return True, status


def identify(status):
    """(modelo, seguro) a partir del byte de estado."""
    if status is None:
        return "SSD1327", False
    s = status & 0xBF
    if s in (0x03, 0x06):
        return "SSD1306", True
    if s == 0x08:
        return "SH1106", True
    if s in (0x07, 0x0F):
        return "SH1107", True
    return "SSD1306", False


def detect_display():
    """Resuelve DISPLAY_TYPE=AUTO y DISPLAY_ADDR=0."""
    global DISPLAY_TYPE, DISPLAY_ADDR
    candidates = [DISPLAY_ADDR] if DISPLAY_ADDR else [0x3C, 0x3D]
    for addr in candidates:
        present, status = i2c_probe(addr)
        if not present:
            continue
        DISPLAY_ADDR = addr
        if DISPLAY_TYPE == "AUTO":
            model, sure = identify(status)
            txt = "no legible" if status is None else f"0x{status:02X}"
            if sure:
                print(f"[oled] Detectada {model} en 0x{addr:02X} (estado {txt})", flush=True)
            else:
                print(f"[oled] Controlador en 0x{addr:02X} sin identificar (estado {txt}); "
                      f"se usa {model}. Si no se ve bien, fija display_type en {CONFIG_FILE}", flush=True)
            DISPLAY_TYPE = model
        return True
    if not DISPLAY_ADDR:
        DISPLAY_ADDR = 0x3C
    if DISPLAY_TYPE == "AUTO":
        DISPLAY_TYPE = "SSD1306"
    return False


# ─── PANTALLA ─────────────────────────────────────────────────
SIZES = {
    "SSD1306": (128, 64),
    "SH1106":  (128, 64),
    "SH1107":  (128, 128),
    "SSD1327": (128, 128),
}


class Panel:
    """Envoltorio común para Adafruit (SSD1306) y luma.oled (resto).

    Gira la imagen si hace falta, así el resto del código dibuja siempre en el
    tamaño lógico (WIDTH x HEIGHT)."""

    def __init__(self, device, luma):
        self.device = device
        self.luma = luma
        self._buf = None

    def image(self, img):
        if DISPLAY_ROTATE:
            img = img.rotate(-DISPLAY_ROTATE, expand=True)
        self._buf = img

    def show(self):
        if self._buf is None:
            return
        img = self._buf
        if self.luma:
            if img.mode != self.device.mode:
                img = img.convert(self.device.mode)
            self.device.display(img)
        else:
            self.device.image(img.convert("1"))
            self.device.show()

    def fill(self, color):
        self._buf = Image.new("1", PANEL_SIZE, color)

    def contrast(self, value):
        self.device.contrast(max(0, min(255, int(value))))

    def poweron(self):
        (self.device.show if self.luma else self.device.poweron)()

    def poweroff(self):
        (self.device.hide if self.luma else self.device.poweroff)()


def _init_display():
    """Devuelve el panel ya inicializado. PANEL_SIZE es el tamaño físico."""
    if DISPLAY_TYPE == "SSD1306":
        import board, busio
        import adafruit_ssd1306
        i2c = busio.I2C(board.SCL, board.SDA)
        dev = adafruit_ssd1306.SSD1306_I2C(PANEL_SIZE[0], PANEL_SIZE[1], i2c, addr=DISPLAY_ADDR)
        return Panel(dev, luma=False)
    from luma.core.interface.serial import i2c as luma_i2c
    serial = luma_i2c(port=I2C_BUS, address=DISPLAY_ADDR)
    w, h = PANEL_SIZE
    if DISPLAY_TYPE == "SH1106":
        from luma.oled.device import sh1106
        return Panel(sh1106(serial, width=w, height=h), luma=True)
    if DISPLAY_TYPE == "SH1107":
        from luma.oled.device import sh1107
        return Panel(sh1107(serial, width=w, height=h, rotate=0), luma=True)
    if DISPLAY_TYPE == "SSD1327":
        from luma.oled.device import ssd1327
        return Panel(ssd1327(serial, width=w, height=h), luma=True)
    raise ValueError(f"display_type '{DISPLAY_TYPE}' no soportado")


# Al arrancar el bus I2C puede tardar un momento; si tras varios intentos no
# hay pantalla (p.ej. esta unidad usa TFT/Nextion) se sale limpio (exit 0)
# para no reiniciar en bucle.
oled = None
_REQ_TYPE, _REQ_ADDR = DISPLAY_TYPE, DISPLAY_ADDR
for _intento in range(1, 6):
    DISPLAY_TYPE, DISPLAY_ADDR = _REQ_TYPE, _REQ_ADDR   # cada intento vuelve a detectar
    detect_display()
    if DISPLAY_TYPE not in SIZES:
        print(f"[oled] display_type '{DISPLAY_TYPE}' no soportado", flush=True)
        raise SystemExit(1)
    PANEL_SIZE = (DISPLAY_WIDTH, DISPLAY_HEIGHT) if DISPLAY_WIDTH and DISPLAY_HEIGHT else SIZES[DISPLAY_TYPE]
    try:
        oled = _init_display()
        break
    except Exception as e:
        print(f"[oled] Intento {_intento}/5: no se detecta {DISPLAY_TYPE} "
              f"(I2C 0x{DISPLAY_ADDR:02X}): {e}", flush=True)
        time.sleep(2)
if oled is None:
    print("[oled] Sin pantalla OLED tras 5 intentos. ¿Variante TFT/Nextion? "
          "Saliendo sin reintentar.", flush=True)
    raise SystemExit(0)

# Tamaño lógico (el que se dibuja): se intercambia con giro de 90/270
WIDTH, HEIGHT = (PANEL_SIZE[1], PANEL_SIZE[0]) if DISPLAY_ROTATE in (90, 270) else PANEL_SIZE
if WIDTH >= 120 and HEIGHT >= 120:
    LAYOUT = "large"
elif WIDTH >= 120 and HEIGHT >= 64:
    LAYOUT = "medium"
else:
    LAYOUT = "compact"
ROW = 11                                   # alto de fila del diseño compacto
ROWS = max(1, (HEIGHT + 1) // ROW)
print(f"[oled] Pantalla: {DISPLAY_TYPE} {PANEL_SIZE[0]}x{PANEL_SIZE[1]} en 0x{DISPLAY_ADDR:02X}, "
      f"giro {DISPLAY_ROTATE}, diseño {LAYOUT}", flush=True)

# ─── FUENTES ──────────────────────────────────────────────────
try:
    font_big   = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf", 14)
    font_med   = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 11)
    font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 10)
    if LAYOUT == "large":
        font_xl  = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf", 20)
        font_lg  = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf", 16)
    else:
        font_xl  = font_big
        font_lg  = font_big
except Exception:
    font_big = font_med = font_small = font_xl = font_lg = ImageFont.load_default()


def hora_local():
    # La hora sale de la zona horaria del sistema (la configura instalar.sh)
    return datetime.now().strftime("%H:%M:%S")


# ─── STATS DEL SISTEMA ────────────────────────────────────────
stats = {"cpuTemp": 0, "voltage": 0, "localIp": "---"}


def get_local_ip():
    # connect() en UDP solo consulta la tabla de rutas: no envía nada
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "---"


def get_temp():
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            return int(f.read()) / 1000.0
    except Exception:
        return 0


def voltage_from_throttled(value):
    """Bit 0 = subtensión AHORA. Los bits 16-19 son sucesos pasados y el resto
    son límites de frecuencia/temperatura: no deben encender el aviso."""
    return 4.7 if value & 0x1 else 5.0


def get_voltage():
    try:
        r = subprocess.run(["vcgencmd", "get_throttled"], capture_output=True, text=True, timeout=2)
        m = re.search(r"throttled=(0x[\da-fA-F]+)", r.stdout)
        if m:
            return voltage_from_throttled(int(m.group(1), 16))
        return 0
    except Exception:
        return 0


def fetch_stats_monitor():
    while True:
        try:
            data = requests.get(STATS_URL, timeout=5).json()
            for k in ("cpuTemp", "voltage", "localIp"):
                if k in data:
                    stats[k] = data[k]
        except Exception:
            pass
        time.sleep(10)


def fetch_stats_system():
    while True:
        stats["cpuTemp"] = get_temp()
        stats["voltage"] = get_voltage()
        stats["localIp"] = get_local_ip()
        time.sleep(30)


def fetch_stats():
    if DATA_MODE == "monitor":
        fetch_stats_monitor()
    else:
        fetch_stats_system()


# ─── RADIOID ──────────────────────────────────────────────────
RADIOID_URL   = "https://radioid.net/static/user.csv"
CACHE_FILE    = os.path.join(os.path.expanduser("~"), "radioid_cache.csv")
CACHE_MAX_AGE = timedelta(hours=24)
RETRY_AFTER   = 3600                       # tras un fallo de descarga
radioid_db    = {}                         # issi → (indicativo, nombre, provincia)
_radioid_lock = threading.Lock()


def cache_is_fresh():
    if not os.path.exists(CACHE_FILE):
        return False
    return datetime.now() - datetime.fromtimestamp(os.path.getmtime(CACHE_FILE)) < CACHE_MAX_AGE


def download_radioid():
    """Descarga a un temporal y lo renombra: nunca deja un CSV a medias."""
    print("[radioid] Descargando...", flush=True)
    tmp = CACHE_FILE + ".part"
    try:
        with requests.get(RADIOID_URL, timeout=120, stream=True) as r:
            r.raise_for_status()
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(chunk_size=65536):
                    f.write(chunk)
        os.replace(tmp, CACHE_FILE)
        print("[radioid] Descarga completada.", flush=True)
        return True
    except Exception as e:
        print(f"[radioid] Error: {e}", flush=True)
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False


def load_radioid():
    global radioid_db
    if not os.path.exists(CACHE_FILE):
        return False
    print("[radioid] Cargando...", flush=True)
    tmp = {}
    try:
        with open(CACHE_FILE, "r", encoding="utf-8", errors="replace") as f:
            for row in csv.DictReader(f):
                rid = str(row.get("RADIO_ID", "")).strip()
                if not rid:
                    continue
                nombre = f"{row.get('FIRST_NAME', '').strip()} {row.get('LAST_NAME', '').strip()}".strip()
                prov = row.get("STATE", "").strip() or row.get("CITY", "").strip()
                # Tupla en vez de diccionario: mucha menos RAM con ~250.000 entradas
                tmp[rid] = (row.get("CALLSIGN", "").strip(), nombre, prov)
    except Exception as e:
        print(f"[radioid] Error: {e}", flush=True)
        return False
    radioid_db = tmp
    print(f"[radioid] {len(radioid_db)} entradas.", flush=True)
    return True


def radioid_updater():
    """Un único hilo: carga al arrancar y refresca cada 24 h, con reintento
    espaciado si la descarga falla (antes se lanzaban descargas en paralelo)."""
    if RADIOID.lower() in ("no", "false", "0", "off"):
        print("[radioid] Desactivado en la configuración.", flush=True)
        return
    while True:
        with _radioid_lock:
            if not cache_is_fresh():
                download_radioid()
            if not radioid_db or cache_is_fresh():
                load_radioid()
        time.sleep(RETRY_AFTER)


def lookup(issi):
    """(indicativo o None, nombre, provincia)."""
    e = radioid_db.get(str(issi))
    if e and e[0]:
        return e
    return None, "", ""


def header_for(issi):
    cs, _, _ = lookup(issi)
    return f"{cs} {issi}" if cs else f"ISSI {issi}"


def short_for(issi):
    cs, _, _ = lookup(issi)
    return cs or str(issi)


# ─── DIBUJO ───────────────────────────────────────────────────
lock          = threading.RLock()     # reentrante: el manejador de señales dibuja también
current_event = {"active": False, "issi": None, "tipo": None, "sds_text": None, "issi_dst": None}
_scroll       = [0]


def get_shift():
    # Basado en el reloj: el mismo ritmo aunque la pantalla se refresque más rápido
    t = int(time.time()) % 628
    sx = int(1.5 + 1.5 * math.sin(t / 50))
    sy = int(1.0 + 1.0 * math.sin(t / 37))
    return sx, sy


def text_width(text, font):
    if not text:
        return 0
    b = font.getbbox(text)
    return b[2] - b[0]


def truncate(text, font, max_width):
    if not text:
        return ""
    if text_width(text, font) <= max_width:
        return text
    lo, hi = 0, len(text)
    while lo < hi - 1:
        mid = (lo + hi) // 2
        if text_width(text[:mid], font) <= max_width:
            lo = mid
        else:
            hi = mid
    return text[:lo]


def fit(text, max_width, fonts):
    for f in fonts:
        if text_width(text, f) <= max_width:
            return f
    return fonts[-1]


def wrap(text, font, max_width):
    lines, line = [], ""
    for word in (text or "").split():
        cand = f"{line} {word}" if line else word
        if text_width(cand, font) <= max_width:
            line = cand
            continue
        if line:
            lines.append(line)
        while text_width(word, font) > max_width:
            head = truncate(word, font, max_width)
            if not head:
                break
            lines.append(head)
            word = word[len(head):]
        line = word
    if line:
        lines.append(line)
    return lines


def centered(draw, y, text, font, fill=1, shift=0):
    draw.text(((WIDTH - text_width(text, font)) // 2 + shift, y), text, font=font, fill=fill)


def marquee(draw, y, text, font):
    """Texto que se desplaza si no cabe. Devuelve True si se mueve."""
    tw = text_width(text, font)
    if tw <= WIDTH - 4:
        centered(draw, y, text, font)
        return False
    period = tw + 32
    x = -(_scroll[0] % period)
    draw.text((x, y), text, font=font, fill=1)
    draw.text((x + period, y), text, font=font, fill=1)
    return True


def oled_display(img):
    """Muestra la imagen en cualquier pantalla soportada."""
    with lock:
        oled.image(img)
        oled.show()


def show_splash(mensaje, subtitulo=""):
    with lock:
        oled.poweron()
        oled.contrast(BRIGHTNESS)
        current_event["active"] = False
        img = Image.new("1", (WIDTH, HEIGHT))
        draw = ImageDraw.Draw(img)
        if LAYOUT == "compact":
            draw.rectangle((0, 0, WIDTH - 1, ROW - 1), fill=1)
            centered(draw, 0, truncate(TITLE, font_small, WIDTH - 2), font_small, fill=0)
            centered(draw, (HEIGHT - 10) // 2 + ROW // 2, truncate(mensaje, font_small, WIDTH - 2), font_small)
        else:
            bar_h = 20 if LAYOUT == "large" else 15
            draw.rectangle((0, 0, WIDTH - 1, bar_h), fill=1)
            f = fit(TITLE, WIDTH - 4, [font_big, font_med])
            centered(draw, 3, truncate(TITLE, f, WIDTH - 4), f, fill=0)
            f = font_xl if LAYOUT == "large" else font_big
            f = fit(mensaje, WIDTH - 4, [f, font_med])
            y = HEIGHT // 2 - 10
            centered(draw, y, mensaje, f)
            if subtitulo:
                centered(draw, y + 25, subtitulo, font_med)
        oled_display(img)


# ─── ÚLTIMOS OÍDOS ────────────────────────────────────────────
heard = deque(maxlen=10)                   # (issi, texto_destino, hora)


def add_heard(issi, what):
    issi = str(issi)
    with lock:
        for h in list(heard):
            if h[0] == issi:
                heard.remove(h)
        heard.appendleft((issi, what, datetime.now().strftime("%H:%M")))


def marquee_text():
    with lock:
        items = list(heard)
    if not items:
        return "Sin actividad"
    partes = []
    for issi, what, hhmm in items:
        cs, nombre, _ = lookup(issi)
        nombre = nombre.split(" ")[0] if nombre else ""
        quien = " ".join(p for p in (cs or f"ISSI", nombre, issi) if p)
        partes.append(f"{quien} {what} {hhmm}")
    return "Últimos: " + "   ·   ".join(partes)


def volt_label(volt):
    if volt == 5.0:
        return "5.0V OK"
    if volt == 4.7:
        return "! VOLT"
    return ""


def show_standby():
    """Pantalla de reposo. Devuelve True si hay texto moviéndose."""
    with lock:
        oled.contrast(IDLE_BRIGHTNESS)
        current_event["active"] = False
        if SCREEN_OFF_TIMEOUT > 0 and standby_since[0] > 0 and time.time() - standby_since[0] > SCREEN_OFF_TIMEOUT:
            oled.poweroff()
            return False
        oled.poweron()
        img = Image.new("1", (WIDTH, HEIGHT))
        draw = ImageDraw.Draw(img)
        ip = stats.get("localIp", "---")
        temp = stats.get("cpuTemp", 0) or 0
        temp_txt = f"{temp:.1f}°C"
        volt_txt = volt_label(stats.get("voltage", 0))
        hora = hora_local()
        sx, sy = get_shift()
        scroll = IDLE_MODE == "scroll"
        texto = marquee_text() if scroll else ""
        info = [f"{temp_txt}  {volt_txt}".strip(), f"IP {ip}"]
        info_now = info[int(time.time() // 5) % len(info)]
        moving = False

        if LAYOUT == "large":
            draw.rectangle((sx, sy, WIDTH - 1 - sx, 20 + sy), fill=1)
            f = fit(TITLE, WIDTH - 4, [font_lg, font_big, font_med])
            centered(draw, 2 + sy, truncate(TITLE, f, WIDTH - 4), f, fill=0, shift=sx)
            if scroll:
                centered(draw, 24 + sy, hora, font_xl, shift=sx)
                moving = marquee(draw, 50, texto, font_lg)
                draw.text((4 + sx, 72 + sy), truncate(info[0], font_med, WIDTH - 8), font=font_med, fill=1)
            else:
                centered(draw, 28 + sy, hora, font_xl, shift=sx)
                draw.text((4 + sx, 55 + sy), temp_txt, font=font_lg, fill=1)
                if volt_txt:
                    draw.text((4 + sx, 74 + sy), volt_txt, font=font_lg, fill=1)
            draw.line((0, 95 + sy, WIDTH, 95 + sy), fill=1, width=1)
            draw.text((4 + sx, 100 + sy), truncate(f"IP {ip}", font_med, WIDTH - 8), font=font_med, fill=1)
        elif LAYOUT == "medium":
            draw.rectangle((sx, sy, WIDTH - 1 - sx, 15 + sy), fill=1)
            centered(draw, 1 + sy, truncate(TITLE, font_big, WIDTH - 4), font_big, fill=0, shift=sx)
            if scroll:
                centered(draw, 17 + sy, hora, font_big, shift=sx)
                moving = marquee(draw, 35, texto, font_med)
                centered(draw, 52 + min(sy, 1), truncate(info_now, font_small, WIDTH - 4), font_small, shift=sx)
            else:
                centered(draw, 18 + sy, hora, font_big, shift=sx)
                draw.text((2 + sx, 36 + sy), temp_txt, font=font_med, fill=1)
                if volt_txt:
                    vw = text_width(volt_txt, font_med)
                    draw.text((WIDTH - vw - 2 - sx, 36 + sy), volt_txt, font=font_med, fill=1)
                draw.text((2 + sx, 52 + sy), f"IP {ip}", font=font_small, fill=1)
        else:
            lines = []
            if ROWS == 1:
                if scroll:
                    moving = marquee(draw, 0, f"{hora[:5]}  {texto}", font_small)
                else:
                    centered(draw, 0, f"{hora} {info_now}", font_small)
            else:
                if ROWS >= 4:
                    lines.append(("title", TITLE))
                lines.append(("text", hora))
                if scroll:
                    lines.append(("marquee", texto))
                for extra in [info_now] + info:
                    if extra and all(extra != l[1] for l in lines):
                        lines.append(("text", extra))
                for i, (kind, txt) in enumerate(lines[:ROWS]):
                    y = i * ROW
                    if kind == "marquee":
                        moving = marquee(draw, y, txt, font_small) or moving
                    elif kind == "title":
                        draw.rectangle((0, 0, WIDTH - 1, ROW - 1), fill=1)
                        centered(draw, y, truncate(txt, font_small, WIDTH - 2), font_small, fill=0)
                    else:
                        centered(draw, y, truncate(txt, font_small, WIDTH - 2), font_small, shift=min(sx, 1))
        oled_display(img)
        return moving


def _render_event(issi, tipo, sds_text, issi_dst):
    callsign, name, provincia = lookup(issi)
    header = header_for(issi)
    dst = f"{short_for(issi)} -> {short_for(issi_dst)}" if issi_dst else ""
    kind = f"[{tipo}]"
    hora = hora_local()
    img = Image.new("1", (WIDTH, HEIGHT))
    draw = ImageDraw.Draw(img)

    if LAYOUT == "large":
        draw.rectangle((0, 0, WIDTH - 1, 20), fill=1)
        f = fit(header, WIDTH - 4, [font_big, font_med])
        draw.text((2, 3), truncate(header, f, WIDTH - 4), font=f, fill=0)
        draw.text((2, 24), truncate(name, font_med, WIDTH - 4), font=font_med, fill=1)
        draw.text((2, 42), truncate(provincia, font_small, WIDTH - 4), font=font_small, fill=1)
        draw.line((0, 58, WIDTH, 58), fill=1, width=1)
        y = 63
        if dst:
            draw.text((2, y), truncate(dst, font_med, WIDTH - 4), font=font_med, fill=1)
            y += 16
        f = fit(kind, WIDTH - 4, [font_lg, font_big, font_med])
        draw.text((2, y), truncate(kind, f, WIDTH - 4), font=f, fill=1)
        y += 20
        if sds_text:
            for line in wrap(sds_text, font_med, WIDTH - 4)[: max(1, (116 - y) // 13)]:
                draw.text((2, y), line, font=font_med, fill=1)
                y += 13
        else:
            draw.text((2, 108), hora, font=font_small, fill=1)
    elif LAYOUT == "medium":
        draw.rectangle((0, 0, WIDTH - 1, 15), fill=1)
        draw.text((2, 1), truncate(header, font_big, WIDTH - 4), font=font_big, fill=0)
        draw.text((2, 17), truncate(name, font_med, WIDTH - 4), font=font_med, fill=1)
        if dst:
            # Con destino, la provincia deja sitio a "origen -> destino" y el tipo
            draw.text((2, 29), truncate(dst, font_small, WIDTH - 4), font=font_small, fill=1)
            draw.text((2, 40), truncate(kind, font_med, WIDTH - 4), font=font_med, fill=1)
        else:
            draw.text((2, 29), truncate(provincia, font_small, WIDTH - 4), font=font_small, fill=1)
            draw.text((2, 40), truncate(kind, font_med, WIDTH - 4), font=font_med, fill=1)
        bottom = sds_text if sds_text else hora
        draw.text((2, 52), truncate(bottom, font_small, WIDTH - 4), font=font_small, fill=1)
    else:
        # Diseño compacto: el origen ya va en la cabecera, así que el destino se abrevia
        dst_c = f"-> {short_for(issi_dst)}" if issi_dst else ""
        is_text = bool(sds_text) and bool(issi_dst)          # SDS con texto
        second = f"{kind} {dst_c or sds_text or ''}".strip()
        if ROWS == 1:
            full = [header, name, second, sds_text if is_text else "", hora]
            marquee(draw, 0, "  ".join(t for t in full if t), font_small)
        else:
            rows = [header]
            if ROWS >= 4 and name:
                rows.append(name)
            rows.append(second)
            if is_text:
                rows.append(sds_text)
            # Con texto de SDS se prioriza el texto; si sobra sitio, la hora al final
            rows = rows[:ROWS] if is_text and len(rows) >= ROWS else rows[: ROWS - 1] + [hora]
            for i, txt in enumerate(rows[:ROWS]):
                if i == 0:
                    draw.rectangle((0, 0, WIDTH - 1, ROW - 1), fill=1)
                    draw.text((1, 0), truncate(txt, font_small, WIDTH - 2), font=font_small, fill=0)
                else:
                    draw.text((1, i * ROW), truncate(txt, font_small, WIDTH - 2), font=font_small, fill=1)
    return img


def show_event(issi, tipo, sds_text=None, issi_dst=None):
    with lock:
        oled.poweron()
        standby_since[0] = 0
        oled.contrast(BRIGHTNESS)
        current_event.update({"active": True, "issi": issi, "tipo": tipo,
                              "sds_text": sds_text, "issi_dst": issi_dst})
        oled_display(_render_event(issi, tipo, sds_text, issi_dst))


def refresh_event():
    """Redibuja el evento actual (reloj y desplazamiento)."""
    with lock:
        if not current_event["active"]:
            return
        ev = dict(current_event)
    try:
        oled_display(_render_event(ev["issi"], ev["tipo"], ev["sds_text"], ev["issi_dst"]))
    except Exception as e:
        print(f"[oled] Error al redibujar: {e}", flush=True)


# ─── CONTROL DE LLAMADAS ──────────────────────────────────────
# Todo el estado se toca con `lock` (lo usan el hilo de logs y el temporizador)
last_event_time = [0]
standby_since   = [0]
call_start_time = [0]
active_calls    = {}                   # uuid → (issi, gssi) de llamadas de red
local_call      = [False]              # hay una llamada local en curso
priority_tg     = [None]
_end_timer      = [None]
CALL_MAX_DISPLAY = 300                 # tope de seguridad si nunca llega el fin de llamada


def schedule_standby(delay=3):
    with lock:
        if _end_timer[0]:
            _end_timer[0].cancel()

        def do_reset():
            with lock:
                _end_timer[0] = None
                if active_calls:
                    best = None
                    for issi, gssi in active_calls.values():
                        if gssi == priority_tg[0]:
                            best = (issi, gssi)
                            break
                    if best is None:
                        best = list(active_calls.values())[-1]
                    print(f"[sched] Llamada activa (prio TG:{priority_tg[0]}): {best[0]} -> TG:{best[1]}", flush=True)
                    show_event(best[0], "NET VOZ", sds_text=f"TG:{best[1]}")
                    last_event_time[0] = time.time()
                    return
                elapsed = time.time() - call_start_time[0]
                if elapsed < CALL_MIN_DISPLAY:
                    last_event_time[0] = time.time() - (DISPLAY_TIMEOUT - (CALL_MIN_DISPLAY - elapsed))
                else:
                    last_event_time[0] = 1

        _end_timer[0] = threading.Timer(delay, do_reset)
        _end_timer[0].daemon = True
        _end_timer[0].start()


def cancel_standby():
    with lock:
        if _end_timer[0]:
            _end_timer[0].cancel()
            _end_timer[0] = None


def showing_call():
    """El evento en pantalla es una llamada que sigue activa."""
    tipo = current_event.get("tipo") or ""
    if not current_event["active"] or "VOZ" not in tipo:
        return False
    return bool(active_calls) or local_call[0]


def debe_mostrar(new_issi, new_gssi):
    if not current_event["active"]:
        return True
    if priority_tg[0] and str(new_gssi) == str(priority_tg[0]):
        return True
    curr_sds = current_event.get("sds_text", "") or ""
    curr_tg = curr_sds.replace("TG:", "") if curr_sds.startswith("TG:") else None
    if priority_tg[0] and str(curr_tg) == str(priority_tg[0]):
        return False
    return str(new_issi) == LOCAL_ISSI and LOCAL_ISSI != "0"


# ─── PATRONES ─────────────────────────────────────────────────
RE_SDS        = re.compile(r"SDS: U-SDS-DATA from ISSI (\d+) to ISSI (\d+), type=(\d+)")
RE_SDS_TEXT   = re.compile(r'text[=:\s]+"([^"]+)"', re.IGNORECASE)
RE_VOICE      = re.compile(r"rx_u_setup: call from ISSI (\d+) to (GSSI|ISSI) (\d+)")
RE_VOICE_P2P  = re.compile(r"rx_u_setup_p2p: call from ISSI (\d+) to ISSI (\d+)")
RE_NET_VOICE  = re.compile(r"BrewWorker: GROUP_TX uuid=(\S+) src=(\d+) dst=(\d+)")
RE_NET_SDS    = re.compile(r"BrewWorker: SHORT_TRANSFER uuid=\S+ src=(\d+) dst=(\d+)")
RE_NET_STALE  = re.compile(r"expiring stale pending SDS")
RE_NET_END    = re.compile(r"BrewWorker: GROUP_IDLE uuid=(\S+)|BrewEntity: group call ended uuid=(\S+)")
RE_LOCAL_END  = re.compile(r"DTxCeased|U-TX CEASED|release_group_call|Hangtime expired for call_id"
                           r"|Call timeout expired for (?:group|individual) call_id")


def process_line(line):
    if RE_NET_STALE.search(line):
        return
    m = RE_NET_END.search(line)
    if m:
        uuid = m.group(1) or m.group(2) or ""
        with lock:
            active_calls.pop(uuid, None)
        schedule_standby(3)
        return
    if RE_LOCAL_END.search(line):
        with lock:
            local_call[0] = False
        schedule_standby(3)
        return
    m = RE_NET_VOICE.search(line)
    if m:
        uuid, issi_src, gssi_dst = m.group(1), m.group(2), m.group(3)
        with lock:
            active_calls[uuid] = (issi_src, gssi_dst)
            add_heard(issi_src, f"TG {gssi_dst}")
            print(f"[brew] VOZ RED {issi_src} -> TG:{gssi_dst}", flush=True)
            if debe_mostrar(issi_src, gssi_dst):
                cancel_standby()
                show_event(issi_src, "NET VOZ", sds_text=f"TG:{gssi_dst}")
                last_event_time[0] = time.time()
                call_start_time[0] = time.time()
        return
    m = RE_NET_SDS.search(line)
    if m:
        print(f"[brew] SDS RED {m.group(1)} -> {m.group(2)}", flush=True)
        with lock:
            add_heard(m.group(1), "SDS")
            show_event(m.group(1), "NET SDS", issi_dst=m.group(2))
            last_event_time[0] = time.time() - (DISPLAY_TIMEOUT - SDS_DISPLAY)
        return
    m = RE_VOICE_P2P.search(line)
    if m:
        issi_src, issi_dst = m.group(1), m.group(2)
        print(f"[evento] VOZ PRIV {issi_src} -> {issi_dst}", flush=True)
        with lock:
            cancel_standby()
            local_call[0] = True
            add_heard(issi_src, f"-> {issi_dst}")
            show_event(issi_src, "VOZ PRIV", issi_dst=issi_dst)
            last_event_time[0] = time.time()
            call_start_time[0] = time.time()
        return
    m = RE_VOICE.search(line)
    if m:
        issi_src, dst_type, dst_id = m.group(1), m.group(2), m.group(3)
        with lock:
            cancel_standby()
            local_call[0] = True
            if issi_src == LOCAL_ISSI and dst_type == "GSSI":
                priority_tg[0] = dst_id
                print(f"[prio] TG prioritario: {dst_id}", flush=True)
            if dst_type == "GSSI":
                add_heard(issi_src, f"TG {dst_id}")
                show_event(issi_src, "VOZ", sds_text=f"TG:{dst_id}")
            else:
                add_heard(issi_src, f"-> {dst_id}")
                show_event(issi_src, "VOZ PRIV", issi_dst=dst_id)
            last_event_time[0] = time.time()
            call_start_time[0] = time.time()
        return
    m = RE_SDS.search(line)
    if m:
        issi_src, issi_dst = m.group(1), m.group(2)
        mt = RE_SDS_TEXT.search(line)
        print(f"[evento] SDS {issi_src} -> {issi_dst}", flush=True)
        with lock:
            add_heard(issi_src, "SDS")
            show_event(issi_src, f"SDS T{m.group(3)}", sds_text=mt.group(1) if mt else None, issi_dst=issi_dst)
            last_event_time[0] = time.time() - (DISPLAY_TIMEOUT - SDS_DISPLAY)


# ─── STREAM DE LOGS ───────────────────────────────────────────
def stream_monitor():
    while True:
        try:
            print("[stream] Conectando a TetraPack Monitor...", flush=True)
            with requests.get(API_URL, stream=True, timeout=(10, None)) as r:
                r.raise_for_status()
                print("[stream] Conectado.", flush=True)
                for raw in r.iter_lines():
                    if raw:
                        line = raw.decode("utf-8", errors="replace")
                        if line.startswith("data:"):
                            try:
                                process_line(json.loads(line[5:].strip()).get("line", ""))
                            except json.JSONDecodeError:
                                pass
        except Exception as e:
            print(f"[stream] Error: {e}. Reconectando en 2s...", flush=True)
        time.sleep(2)


def stream_journalctl():
    while True:
        proc = None
        try:
            print(f"[stream] Leyendo journalctl de {SERVICE_NAME}...", flush=True)
            # -n 0: solo lo nuevo (sin -n se repetían las 10 últimas líneas al arrancar)
            proc = subprocess.Popen(
                ["journalctl", "-u", SERVICE_NAME, "-f", "-n", "0", "--no-pager", "-o", "cat"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
            )
            print("[stream] Conectado.", flush=True)
            first = []
            for line in proc.stdout:
                line = line.strip()
                if len(first) < 3:
                    first.append(line)      # si journalctl falla, su error sale aquí
                process_line(line)
            code = proc.wait(timeout=5)
            detalle = f": {' | '.join(first)}" if code and first else ""
            print(f"[stream] journalctl terminó (código {code}){detalle}", flush=True)
        except Exception as e:
            print(f"[stream] Error: {e}", flush=True)
        finally:
            if proc:
                try:
                    proc.kill()
                    proc.wait(timeout=5)
                except Exception:
                    pass
        # Evita un bucle a tope de CPU si journalctl sale al momento (p.ej. sin permisos)
        time.sleep(5)


def stream_logs():
    if DATA_MODE == "monitor":
        stream_monitor()
    else:
        stream_journalctl()


# ─── SEÑALES ──────────────────────────────────────────────────
_stop = [None]


def handle_signal(signum, frame):
    # Solo se marca la parada: dibujar aquí podía colgar el proceso si la señal
    # llegaba a mitad de una escritura I2C (la librería no es reentrante).
    _stop[0] = signum


def shutdown_display():
    """Rótulo según lo que esté haciendo systemd y pantalla en negro."""
    try:
        r = subprocess.run(["systemctl", "list-jobs", "--no-legend"],
                           capture_output=True, text=True, timeout=2).stdout
    except Exception:
        r = ""
    if "reboot.target" in r:
        label = "Reiniciando..."
    elif "poweroff.target" in r or "halt.target" in r or "shutdown.target" in r:
        label = "Apagando..."
    else:
        label = "Detenido"
    try:
        show_splash(label)
        time.sleep(2)
        with lock:
            oled.fill(0)
            oled.show()
    except Exception as e:
        print(f"[oled] Error al apagar la pantalla: {e}", flush=True)
    print(f"[oled] {label}", flush=True)


# ─── MAIN ─────────────────────────────────────────────────────
def main():
    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)
    print(f"[oled] Modo: {DATA_MODE} | Servicio: {SERVICE_NAME} | Pantalla: {DISPLAY_TYPE} | "
          f"Reposo: {IDLE_MODE}", flush=True)
    show_splash("Iniciando...")
    time.sleep(3)
    if _stop[0] is not None:
        shutdown_display()
        return
    for target in (radioid_updater, fetch_stats, stream_logs):
        threading.Thread(target=target, daemon=True).start()
    print("[oled] En marcha. Ctrl+C para salir.", flush=True)
    # Paso de desplazamiento según lo que cuesta refrescar cada pantalla
    step, fast = (4, 0.2) if LAYOUT != "large" else (8, 0.4)
    last_clock = 0.0
    while _stop[0] is None:
        now = time.time()
        with lock:
            elapsed = now - last_event_time[0]
            if showing_call() and elapsed < CALL_MAX_DISPLAY:
                # La llamada sigue: no volver a reposo aunque pase DISPLAY_TIMEOUT
                last_event_time[0] = max(last_event_time[0], now - DISPLAY_TIMEOUT + 1)
                elapsed = now - last_event_time[0]
            idle = last_event_time[0] == 0 or elapsed > DISPLAY_TIMEOUT
            if idle:
                if standby_since[0] == 0:
                    standby_since[0] = now
                if last_event_time[0] != 0:
                    last_event_time[0] = 0
        moving = False
        if idle:
            moving = show_standby()
        elif now - last_clock >= 1 or (LAYOUT == "compact" and ROWS == 1):
            refresh_event()
            last_clock = now
            moving = LAYOUT == "compact" and ROWS == 1
        if moving:
            _scroll[0] += step
            time.sleep(fast)
        else:
            time.sleep(1 if idle else 0.25)
    shutdown_display()


if __name__ == "__main__":
    main()
