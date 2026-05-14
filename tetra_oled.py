#!/usr/bin/env python3
# ═══════════════════════════════════════════════════════════════
#  TETRA OLED Display v3.1
#  Jose Maria - EA8DLF · 2026
#  https://github.com/EA8DLF/Tetra-oled-display
#  Compatible con SSD1306 (128x64), SH1107 (128x128) y SSD1327 (128x128)
# ═══════════════════════════════════════════════════════════════

import re, json, time, requests, threading, os, csv, signal, sys, random, math, subprocess, socket
from datetime import datetime, timedelta
from PIL import Image, ImageDraw, ImageFont
import board, busio, pytz

# ─── CONFIGURACIÓN ────────────────────────────────────────────
# Nombre del servicio systemd de tu bluestation
SERVICE_NAME         = "tmo.service"

# Tipo de pantalla:
#   "SSD1306" → pantalla OLED 0.96" 128x64  (la más común)
#   "SH1107"  → pantalla OLED 1.5"  128x128 (Hailege y similares)
#   "SSD1327" → pantalla OLED 1.5"  128x128 (ZJY-M150 y similares, escala de grises)
DISPLAY_TYPE         = "SSD1306"

# Dirección I2C de la pantalla (normalmente 0x3C, algunas SH1107 usan 0x3D)
DISPLAY_ADDR         = 0x3C

# Modo de datos:
#   "monitor"    → usa TetraPack Monitor (necesita MONITOR_URL)
#   "journalctl" → lee directamente del servicio systemd (sin dashboard)
DATA_MODE            = "monitor"

# URL del TetraPack Monitor (solo si DATA_MODE = "monitor")
MONITOR_URL          = "http://localhost:5000"

# ISSI de tu terminal local (para priorizar tu TG)
LOCAL_ISSI           = "0"       # Introduce el ISSI de tu terminal TETRA local

# URL del servidor XLX/Brew (para consultar llamadas activas al arrancar)
BREW_URL             = "https://watch.tetrapack.online/api/brew/calls"

# Tiempos de visualización
DISPLAY_TIMEOUT      = 30   # segundos hasta volver a standby
CALL_MIN_DISPLAY     = 5    # segundos mínimo para llamadas cortas
SDS_DISPLAY          = 5    # segundos para mensajes SDS
SCREEN_OFF_TIMEOUT   = 300  # segundos hasta apagar pantalla (5 min)
# ──────────────────────────────────────────────────────────────

# URLs derivadas
API_URL   = f"{MONITOR_URL}/api/log-stream"
STATS_URL = f"{MONITOR_URL}/api/system/stats"

# ─── INIT PANTALLA ────────────────────────────────────────────
i2c = busio.I2C(board.SCL, board.SDA)

if DISPLAY_TYPE == "SH1107":
    import adafruit_sh1107
    oled   = adafruit_sh1107.SH1107_I2C(128, 128, i2c, addr=DISPLAY_ADDR, rotation=0)
    WIDTH  = 128
    HEIGHT = 128
elif DISPLAY_TYPE == "SSD1327":
    import adafruit_ssd1327
    oled   = adafruit_ssd1327.SSD1327_I2C(128, 128, i2c, addr=DISPLAY_ADDR)
    WIDTH  = 128
    HEIGHT = 128
else:
    import adafruit_ssd1306
    oled   = adafruit_ssd1306.SSD1306_I2C(128, 64, i2c, addr=DISPLAY_ADDR)
    WIDTH  = 128
    HEIGHT = 64

print(f"[oled] Pantalla: {DISPLAY_TYPE} {WIDTH}x{HEIGHT} en 0x{DISPLAY_ADDR:02X}")

# ─── FUENTES ──────────────────────────────────────────────────
try:
    font_big   = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf", 14)
    font_med   = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 11)
    font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 10)
    # Fuentes grandes para SH1107/SSD1327 que tienen más espacio
    if DISPLAY_TYPE in ("SH1107", "SSD1327"):
        font_xl  = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf", 20)
        font_lg  = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf", 16)
    else:
        font_xl  = font_big
        font_lg  = font_big
except:
    font_big = font_med = font_small = font_xl = font_lg = ImageFont.load_default()

# ─── ZONA HORARIA ─────────────────────────────────────────────
timezone_actual = [pytz.utc]

def fetch_timezone(public_ip):
    try:
        r = requests.get(f"http://ip-api.com/json/{public_ip}?fields=timezone", timeout=5)
        tz_name = r.json().get("timezone", "UTC")
        timezone_actual[0] = pytz.timezone(tz_name)
        print(f"[tz] Zona horaria: {tz_name}")
    except Exception as e:
        print(f"[tz] Error: {e}")

def hora_local():
    return datetime.now().astimezone().strftime("%H:%M:%S")

# ─── STATS DEL SISTEMA ────────────────────────────────────────
stats = {"cpuTemp": 0, "voltage": 0, "localIp": "---", "publicIp": ""}

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "---"

def get_temp():
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            return int(f.read()) / 1000.0
    except:
        return 0

def get_voltage():
    try:
        r = subprocess.run(["vcgencmd", "measure_volts"], capture_output=True, text=True, timeout=2)
        v = re.search(r"volt=([\d.]+)", r.stdout)
        return float(v.group(1)) if v else 0
    except:
        return 0

def get_public_ip():
    try:
        r = requests.get("https://api.ipify.org?format=json", timeout=5)
        return r.json().get("ip", "")
    except:
        return ""

def fetch_stats_monitor():
    last_ip = None
    while True:
        try:
            r = requests.get(STATS_URL, timeout=5)
            data = r.json()
            stats.update(data)
            pub = data.get("publicIp", "")
            if pub and pub != last_ip:
                last_ip = pub
                threading.Thread(target=fetch_timezone, args=(pub,), daemon=True).start()
            if not radioid_db and os.path.exists(CACHE_FILE):
                threading.Thread(target=load_radioid, daemon=True).start()
        except:
            pass
        time.sleep(10)

def fetch_stats_system():
    last_ip = None
    while True:
        try:
            stats["cpuTemp"] = get_temp()
            stats["voltage"]  = get_voltage()
            stats["localIp"]  = get_local_ip()
            pub = get_public_ip()
            if pub:
                stats["publicIp"] = pub
                if pub != last_ip:
                    last_ip = pub
                    threading.Thread(target=fetch_timezone, args=(pub,), daemon=True).start()
            if not radioid_db and os.path.exists(CACHE_FILE):
                threading.Thread(target=load_radioid, daemon=True).start()
        except:
            pass
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
radioid_db    = {}

def cache_is_fresh():
    if not os.path.exists(CACHE_FILE):
        return False
    return datetime.now() - datetime.fromtimestamp(os.path.getmtime(CACHE_FILE)) < CACHE_MAX_AGE

def download_radioid():
    print("[radioid] Descargando...")
    try:
        r = requests.get(RADIOID_URL, timeout=120, stream=True)
        r.raise_for_status()
        with open(CACHE_FILE, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
        print("[radioid] Descarga completada.")
    except Exception as e:
        print(f"[radioid] Error: {e}")

def load_radioid():
    global radioid_db
    if not cache_is_fresh():
        download_radioid()
    if not os.path.exists(CACHE_FILE):
        return
    print("[radioid] Cargando...")
    tmp = {}
    try:
        with open(CACHE_FILE, "r", encoding="utf-8", errors="replace") as f:
            for row in csv.DictReader(f):
                rid = str(row.get("RADIO_ID", "")).strip()
                if rid:
                    nombre = f"{row.get('FIRST_NAME','').strip()} {row.get('LAST_NAME','').strip()}".strip()
                    tmp[rid] = {
                        "callsign": row.get("CALLSIGN", "???").strip(),
                        "name":     nombre or "Desconocido",
                        "city":     row.get("CITY", "").strip(),
                        "state":    row.get("STATE", "").strip(),
                    }
        radioid_db = tmp
    except Exception as e:
        print(f"[radioid] Error: {e}")
    print(f"[radioid] {len(radioid_db)} entradas.")

def lookup(issi):
    e = radioid_db.get(str(issi))
    if e:
        prov = e.get("state", "") or e.get("city", "") or ""
        return e["callsign"], e["name"], prov
    return f"ISSI:{issi}", "Desconocido", ""

def daily_updater():
    while True:
        time.sleep(3600)
        if not cache_is_fresh():
            load_radioid()

# ─── PANTALLA ─────────────────────────────────────────────────
lock          = threading.Lock()
current_event = {"active": False, "issi": None, "tipo": None, "sds_text": None, "issi_dst": None}
_shift_tick   = [0]

def get_shift():
    t = _shift_tick[0]
    _shift_tick[0] = (t + 1) % 628
    sx = int(1.5 + 1.5 * math.sin(t / 50))
    sy = int(1.0 + 1.0 * math.sin(t / 37))
    return sx, sy

def truncate(text, font, max_width):
    if not text:
        return ""
    if (font.getbbox(text)[2] - font.getbbox(text)[0]) <= max_width:
        return text
    lo, hi = 0, len(text)
    while lo < hi - 1:
        mid = (lo + hi) // 2
        if (font.getbbox(text[:mid])[2] - font.getbbox(text[:mid])[0]) <= max_width:
            lo = mid
        else:
            hi = mid
    return text[:lo]

def oled_display(img):
    """Muestra imagen en pantalla compatible con SSD1306 y SH1107."""
    with lock:
        oled.image(img)
        oled.show()

def show_splash(mensaje, subtitulo=""):
    oled.poweron()
    oled.contrast(255)
    current_event["active"] = False
    img  = Image.new("1", (WIDTH, HEIGHT))
    draw = ImageDraw.Draw(img)
    # Barra superior
    bar_h = 20 if DISPLAY_TYPE in ("SH1107", "SSD1327") else 15
    draw.rectangle((0, 0, WIDTH-1, bar_h), fill=1)
    titulo = "TETRA Monitor"
    tw = font_big.getbbox(titulo)[2] - font_big.getbbox(titulo)[0]
    draw.text(((WIDTH - tw) // 2, 3), titulo, font=font_big, fill=0)
    # Mensaje centrado
    f = font_xl if DISPLAY_TYPE in ("SH1107", "SSD1327") else font_big
    w = f.getbbox(mensaje)[2] - f.getbbox(mensaje)[0]
    y = HEIGHT // 2 - 10
    draw.text(((WIDTH - w) // 2, y), mensaje, font=f, fill=1)
    if subtitulo:
        w2 = font_med.getbbox(subtitulo)[2] - font_med.getbbox(subtitulo)[0]
        draw.text(((WIDTH - w2) // 2, y + 25), subtitulo, font=font_med, fill=1)
    oled_display(img)

def show_standby():
    oled.contrast(50)
    current_event["active"] = False
    if standby_since[0] > 0 and time.time() - standby_since[0] > SCREEN_OFF_TIMEOUT:
        oled.poweroff()
        return
    oled.poweron()
    img  = Image.new("1", (WIDTH, HEIGHT))
    draw = ImageDraw.Draw(img)
    ip   = stats.get("localIp", "---")
    temp = stats.get("cpuTemp", 0)
    volt = stats.get("voltage", 0)
    sx, sy = get_shift()

    if DISPLAY_TYPE in ("SH1107", "SSD1327"):
        # Layout 128x128 — más espacio, fuentes más grandes
        draw.rectangle((sx, sy, WIDTH-1-sx, 20+sy), fill=1)
        titulo = "TETRA Monitor"
        tw = font_lg.getbbox(titulo)[2] - font_lg.getbbox(titulo)[0]
        draw.text(((WIDTH - tw) // 2 + sx, 2 + sy), titulo, font=font_lg, fill=0)
        # Hora grande centrada
        hora = hora_local()
        hw = font_xl.getbbox(hora)[2] - font_xl.getbbox(hora)[0]
        draw.text(((WIDTH - hw) // 2 + sx, 28 + sy), hora, font=font_xl, fill=1)
        # Temperatura
        draw.text((4 + sx, 58 + sy), f"Temp:", font=font_med, fill=1)
        draw.text((4 + sx, 73 + sy), f"{temp:.1f}\u00b0C", font=font_lg, fill=1)
        # Voltaje
        volt_ok  = "OK" if float(volt) >= 4.8 else "!"
        volt_txt = f"{volt}V {volt_ok}"
        vw = font_lg.getbbox(volt_txt)[2] - font_lg.getbbox(volt_txt)[0]
        draw.text((WIDTH - vw - 4 - sx, 73 + sy), volt_txt, font=font_lg, fill=1)
        # IP
        draw.text((4 + sx, 100 + sy), f"IP {ip}", font=font_med, fill=1)
        # Línea separadora
        draw.line((0, 95+sy, WIDTH, 95+sy), fill=1, width=1)
    else:
        # Layout 128x64 — original
        draw.rectangle((sx, sy, WIDTH-1-sx, 15+sy), fill=1)
        titulo = "TETRA Monitor"
        tw = font_big.getbbox(titulo)[2] - font_big.getbbox(titulo)[0]
        draw.text(((WIDTH - tw) // 2 + sx, 1 + sy), titulo, font=font_big, fill=0)
        hora = hora_local()
        hw = font_big.getbbox(hora)[2] - font_big.getbbox(hora)[0]
        draw.text(((WIDTH - hw) // 2 + sx, 18 + sy), hora, font=font_big, fill=1)
        temp_txt = f"{temp:.1f}\u00b0C"
        volt_ok  = "OK" if float(volt) >= 4.8 else "!"
        volt_txt = f"{volt}V {volt_ok}"
        vw = font_med.getbbox(volt_txt)[2] - font_med.getbbox(volt_txt)[0]
        draw.text((2 + sx, 36 + sy), temp_txt, font=font_med, fill=1)
        draw.text((WIDTH - vw - 2 - sx, 36 + sy), volt_txt, font=font_med, fill=1)
        draw.text((2 + sx, 52 + sy), f"IP {ip}", font=font_small, fill=1)

    oled_display(img)

def _render_event(issi, tipo, sds_text, issi_dst):
    callsign, name, provincia = lookup(issi)
    dst_cs, _, _ = lookup(issi_dst) if issi_dst else ("", "", "")
    img  = Image.new("1", (WIDTH, HEIGHT))
    draw = ImageDraw.Draw(img)

    if DISPLAY_TYPE in ("SH1107", "SSD1327"):
        # Layout 128x128 — más espacioso y legible
        draw.rectangle((0, 0, WIDTH-1, 20), fill=1)
        draw.text((2, 2), truncate(f"{callsign} {issi}", font_lg, WIDTH-4), font=font_lg, fill=0)
        draw.text((2, 24), truncate(name, font_med, WIDTH-4), font=font_med, fill=1)
        draw.text((2, 42), truncate(provincia, font_small, WIDTH-4), font=font_small, fill=1)
        draw.line((0, 58, WIDTH, 58), fill=1, width=1)
        if dst_cs:
            dst_display = dst_cs.replace("ISSI:", "") if dst_cs.startswith("ISSI:") else dst_cs
            draw.text((2, 63), truncate(f"{callsign} -> {dst_display}", font_med, WIDTH-4), font=font_med, fill=1)
            draw.text((2, 83), f"[{tipo}]", font=font_lg, fill=1)
            draw.text((2, 108), hora_local(), font=font_small, fill=1)
        else:
            draw.text((2, 63), f"[{tipo}]", font=font_lg, fill=1)
            if sds_text:
                draw.text((2, 90), truncate(sds_text, font_med, WIDTH-4), font=font_med, fill=1)
            else:
                draw.text((2, 108), hora_local(), font=font_small, fill=1)
    else:
        # Layout 128x64 — original
        draw.rectangle((0, 0, WIDTH-1, 15), fill=1)
        draw.text((2, 1), truncate(f"{callsign} {issi}", font_big, WIDTH-4), font=font_big, fill=0)
        draw.text((2, 17), truncate(name, font_med, WIDTH-4), font=font_med, fill=1)
        draw.text((2, 29), truncate(provincia, font_small, WIDTH-4), font=font_small, fill=1)
        if dst_cs:
            dst_display = dst_cs.replace("ISSI:", "") if dst_cs.startswith("ISSI:") else dst_cs
            draw.text((2, 40), truncate(f"{callsign} -> {dst_display}", font_med, WIDTH-4), font=font_med, fill=1)
            draw.text((2, 52), f"[{tipo}]", font=font_small, fill=1)
        else:
            draw.text((2, 40), f"[{tipo}]", font=font_med, fill=1)
            if sds_text:
                draw.text((2, 52), truncate(sds_text, font_small, WIDTH-4), font=font_small, fill=1)
            else:
                draw.text((2, 52), hora_local(), font=font_small, fill=1)
    return img

def show_event(issi, tipo, sds_text=None, issi_dst=None):
    oled.poweron()
    standby_since[0] = 0
    oled.contrast(255)
    current_event.update({"active": True, "issi": issi, "tipo": tipo,
                          "sds_text": sds_text, "issi_dst": issi_dst})
    oled_display(_render_event(issi, tipo, sds_text, issi_dst))

def clock_updater():
    last_hora = ""
    while True:
        time.sleep(1)
        if current_event["active"] and not current_event["sds_text"]:
            hora = hora_local()
            if hora != last_hora:
                last_hora = hora
                try:
                    oled_display(_render_event(
                        current_event["issi"], current_event["tipo"],
                        current_event["sds_text"], current_event["issi_dst"]
                    ))
                except:
                    pass

# ─── CONTROL DE LLAMADAS ──────────────────────────────────────
last_event_time = [0]
standby_since   = [0]
call_start_time = [0]
active_calls    = {}
priority_tg     = [None]
_end_timer      = [None]

def schedule_standby(delay=3):
    if _end_timer[0]:
        _end_timer[0].cancel()
    def do_reset():
        if active_calls:
            best_issi, best_gssi = None, None
            for uuid, (issi, gssi) in active_calls.items():
                if gssi == priority_tg[0]:
                    best_issi, best_gssi = issi, gssi
                    break
            if not best_issi:
                _, (best_issi, best_gssi) = next(reversed(active_calls.items()))
            print(f"[sched] Llamada activa (prio TG:{priority_tg[0]}): {best_issi} -> TG:{best_gssi}")
            show_event(best_issi, "NET VOZ", sds_text=f"TG:{best_gssi}")
            last_event_time[0] = time.time()
            return
        elapsed = time.time() - call_start_time[0]
        if elapsed < CALL_MIN_DISPLAY:
            last_event_time[0] = time.time() - (DISPLAY_TIMEOUT - (CALL_MIN_DISPLAY - elapsed))
        else:
            last_event_time[0] = 1
    _end_timer[0] = threading.Timer(delay, do_reset)
    _end_timer[0].start()

def cancel_standby():
    if _end_timer[0]:
        _end_timer[0].cancel()
        _end_timer[0] = None

def debe_mostrar(new_issi, new_gssi):
    if not current_event["active"]:
        return True
    if priority_tg[0] and str(new_gssi) == str(priority_tg[0]):
        return True
    curr_sds = current_event.get("sds_text", "") or ""
    curr_tg = curr_sds.replace("TG:", "") if curr_sds.startswith("TG:") else None
    if priority_tg[0] and str(curr_tg) == str(priority_tg[0]):
        return False
    if str(new_issi) == str(LOCAL_ISSI):
        return True
    return False

# ─── PATRONES ─────────────────────────────────────────────────
RE_SDS        = re.compile(r"SDS: U-SDS-DATA from ISSI (\d+) to ISSI (\d+), type=(\d+)")
RE_SDS_TEXT   = re.compile(r'text[=:\s]+"([^"]+)"', re.IGNORECASE)
RE_VOICE      = re.compile(r"rx_u_setup: call from ISSI (\d+) to (GSSI|ISSI) (\d+)")
RE_VOICE_P2P  = re.compile(r"rx_u_setup_p2p: call from ISSI (\d+) to ISSI (\d+)")
RE_NET_VOICE  = re.compile(r"BrewWorker: GROUP_TX uuid=(\S+) src=(\d+) dst=(\d+)")
RE_NET_SDS    = re.compile(r"BrewWorker: SHORT_TRANSFER uuid=\S+ src=(\d+) dst=(\d+)")
RE_NET_STALE  = re.compile(r"expiring stale pending SDS")
RE_NET_END    = re.compile(r"BrewWorker: GROUP_IDLE uuid=(\S+)|BrewEntity: group call ended uuid=(\S+)")
RE_LOCAL_END  = re.compile(r"DTxCeased|U-TX CEASED|release_group_call")
RE_REBOOT     = re.compile(r"systemd.*reboot|reboot.*systemd|Rebooting", re.IGNORECASE)
RE_SHUTDOWN   = re.compile(r"systemd.*halt|systemd.*poweroff|shutdown|Halting", re.IGNORECASE)
RE_UNDERVOLT  = re.compile(r"Undervoltage detected")
RE_VOLT_OK    = re.compile(r"Voltage normalised")

def process_line(line):
    if RE_SHUTDOWN.search(line):
        show_splash("Apagando...")
        return
    if RE_REBOOT.search(line):
        show_splash("Reiniciando...")
        return
    if RE_UNDERVOLT.search(line):
        stats["voltage"] = 4.7
        return
    if RE_VOLT_OK.search(line):
        stats["voltage"] = 5.0
        return
    if RE_NET_STALE.search(line):
        return
    m = RE_NET_END.search(line)
    if m:
        uuid = m.group(1) or m.group(2) or ""
        active_calls.pop(uuid, None)
        schedule_standby(3)
        return
    if RE_LOCAL_END.search(line):
        schedule_standby(3)
        return
    m = RE_NET_VOICE.search(line)
    if m:
        uuid, issi_src, gssi_dst = m.group(1), m.group(2), m.group(3)
        active_calls[uuid] = (issi_src, gssi_dst)
        print(f"[brew] VOZ RED {issi_src} -> TG:{gssi_dst}")
        if debe_mostrar(issi_src, gssi_dst):
            cancel_standby()
            show_event(issi_src, "NET VOZ", sds_text=f"TG:{gssi_dst}")
            last_event_time[0] = time.time()
            call_start_time[0] = time.time()
        return
    m = RE_NET_SDS.search(line)
    if m:
        print(f"[brew] SDS RED {m.group(1)} -> {m.group(2)}")
        show_event(m.group(1), "NET SDS", issi_dst=m.group(2))
        last_event_time[0] = time.time() - (DISPLAY_TIMEOUT - SDS_DISPLAY)
        return
    m = RE_VOICE_P2P.search(line)
    if m:
        cancel_standby()
        issi_src, issi_dst = m.group(1), m.group(2)
        print(f"[evento] VOZ PRIV {issi_src} -> {issi_dst}")
        show_event(issi_src, "VOZ PRIV", issi_dst=issi_dst)
        last_event_time[0] = time.time()
        call_start_time[0] = time.time()
        return
    m = RE_VOICE.search(line)
    if m:
        cancel_standby()
        issi_src, dst_type, dst_id = m.group(1), m.group(2), m.group(3)
        if issi_src == LOCAL_ISSI and dst_type == "GSSI":
            priority_tg[0] = dst_id
            print(f"[prio] TG prioritario: {dst_id}")
        if dst_type == "GSSI":
            show_event(issi_src, "VOZ", sds_text=f"TG:{dst_id}")
        else:
            show_event(issi_src, "VOZ PRIV", issi_dst=dst_id)
        last_event_time[0] = time.time()
        call_start_time[0] = time.time()
        return
    m = RE_SDS.search(line)
    if m:
        issi_src, issi_dst = m.group(1), m.group(2)
        mt = RE_SDS_TEXT.search(line)
        print(f"[evento] SDS {issi_src} -> {issi_dst}")
        show_event(issi_src, f"SDS T{m.group(3)}", sds_text=mt.group(1) if mt else None, issi_dst=issi_dst)
        last_event_time[0] = time.time() - (DISPLAY_TIMEOUT - SDS_DISPLAY)

# ─── STREAM DE LOGS ───────────────────────────────────────────
def stream_monitor():
    while True:
        try:
            print("[stream] Conectando a TetraPack Monitor...")
            with requests.get(API_URL, stream=True, timeout=(10, None)) as r:
                r.raise_for_status()
                print("[stream] Conectado.")
                for raw in r.iter_lines():
                    if raw:
                        line = raw.decode("utf-8", errors="replace")
                        if line.startswith("data:"):
                            try:
                                process_line(json.loads(line[5:].strip()).get("line", ""))
                            except json.JSONDecodeError:
                                pass
        except Exception as e:
            print(f"[stream] Error: {e}. Reconectando en 1s...")
            time.sleep(1)

def stream_journalctl():
    while True:
        try:
            print(f"[stream] Leyendo journalctl de {SERVICE_NAME}...")
            proc = subprocess.Popen(
                ["journalctl", "-u", SERVICE_NAME, "-f", "--no-pager", "-o", "cat"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True
            )
            print("[stream] Conectado.")
            for line in proc.stdout:
                process_line(line.strip())
        except Exception as e:
            print(f"[stream] Error: {e}. Reconectando en 1s...")
            time.sleep(1)

def stream_logs():
    if DATA_MODE == "monitor":
        stream_monitor()
    else:
        stream_journalctl()

# ─── SEÑALES ──────────────────────────────────────────────────
def handle_signal(signum, frame):
    try:
        r = os.popen("systemctl list-jobs 2>/dev/null").read()
        if "reboot.target" in r:
            show_splash("Reiniciando...")
        elif "poweroff.target" in r or "halt.target" in r or "shutdown.target" in r:
            show_splash("Apagando...")
        else:
            show_splash("Reiniciando...")
    except:
        show_splash("Reiniciando...")
    time.sleep(2)
    oled.fill(0)
    oled.show()
    sys.exit(0)

signal.signal(signal.SIGTERM, handle_signal)
signal.signal(signal.SIGINT, handle_signal)

# ─── MAIN ─────────────────────────────────────────────────────
def main():
    print(f"[oled] Modo: {DATA_MODE} | Servicio: {SERVICE_NAME} | Pantalla: {DISPLAY_TYPE}")
    show_splash("Iniciando...")
    time.sleep(3)
    threading.Thread(target=load_radioid,  daemon=True).start()
    threading.Thread(target=daily_updater, daemon=True).start()
    threading.Thread(target=fetch_stats,   daemon=True).start()
    threading.Thread(target=stream_logs,   daemon=True).start()
    threading.Thread(target=clock_updater, daemon=True).start()
    print("[oled] En marcha. Ctrl+C para salir.")
    while True:
        elapsed = time.time() - last_event_time[0]
        if last_event_time[0] == 0 or elapsed > DISPLAY_TIMEOUT:
            if standby_since[0] == 0:
                standby_since[0] = time.time()
            show_standby()
            if last_event_time[0] != 0 and elapsed > DISPLAY_TIMEOUT:
                last_event_time[0] = 0
        time.sleep(1)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        oled.fill(0)
        oled.show()
        print("\n[oled] Saliendo.")
