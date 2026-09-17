#!/bin/bash

# ═══════════════════════════════════════════════════════════════
#  TETRA OLED Display - Script de instalación v3.5.0
#  Jose Maria - EA8DLF · 2026
#  https://github.com/EA8DLF/Tetra-oled-display
# ═══════════════════════════════════════════════════════════════

set -e

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
REPO="https://raw.githubusercontent.com/EA8DLF/Tetra-oled-display/main"
CONF=/etc/tetra-oled.conf

ok()   { echo -e "${GREEN}[OK]${NC} $1"; }
info() { echo -e "${YELLOW}[INFO]${NC} $1"; }
warn() { echo -e "${YELLOW}[AVISO]${NC} $1"; }
err()  { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

echo "════════════════════════════════════════"
echo "  TETRA OLED Display - Instalación v3.5.0"
echo "  Jose Maria - EA8DLF · 2026"
echo "════════════════════════════════════════"

# ── 0. USUARIO DE LA RASPBERRY ────────────────────────────────
info "Detectando usuario..."
DEFAULT_USER=$(logname 2>/dev/null || echo "${SUDO_USER:-pi}")
read -p "Usuario de la Raspberry Pi [$DEFAULT_USER]: " RPIUSER
RPIUSER=${RPIUSER:-$DEFAULT_USER}
RPIHOME=$(getent passwd "$RPIUSER" | cut -d: -f6)

if [ -z "$RPIHOME" ] || [ ! -d "$RPIHOME" ]; then
    err "No se encuentra el usuario '$RPIUSER' o su carpeta personal."
fi
ok "Usuario: $RPIUSER  |  Home: $RPIHOME"

# ── 1. CONFIGURAR I2C ─────────────────────────────────────────
info "Activando I2C..."
sudo raspi-config nonint do_i2c 0
# La ruta de config.txt cambia según la versión de Raspberry Pi OS
BOOTCFG=/boot/firmware/config.txt
[ -f "$BOOTCFG" ] || BOOTCFG=/boot/config.txt
# Velocidad estándar (100kHz): más fiable con módulos OLED baratos y cables
# de puente largos. Los 400kHz provocaban errores de I2C ("device not found")
# en pantallas SSD1327 y similares.
if grep -q "dtparam=i2c_arm" "$BOOTCFG"; then
    sudo sed -i 's/dtparam=i2c_arm=on.*/dtparam=i2c_arm=on/' "$BOOTCFG"
else
    echo "dtparam=i2c_arm=on" | sudo tee -a "$BOOTCFG" > /dev/null
fi
ok "I2C activado a velocidad estándar (100kHz)"

# ── 2. ZONA HORARIA ───────────────────────────────────────────
info "Configurando zona horaria..."
echo "¿Cuál es tu zona horaria? (la hora de la pantalla es la del sistema)"
echo "  1) Atlantic/Canary  (Canarias)"
echo "  2) Europe/Madrid    (Península)"
echo "  3) Otra             (introducir manualmente)"
read -p "Elige [1/2/3]: " tz_opt
case $tz_opt in
    1) TZ="Atlantic/Canary" ;;
    2) TZ="Europe/Madrid" ;;
    3) read -p "Zona horaria (ej: Europe/London): " TZ ;;
    *) TZ="Atlantic/Canary" ;;
esac
sudo timedatectl set-timezone "$TZ"
ok "Zona horaria: $TZ"

# ── 3. NOMBRE DEL SERVICIO BLUESTATION ────────────────────────
info "Configurando servicio bluestation..."
echo "¿Cómo se llama tu servicio systemd de bluestation / FlowStation?"
echo "  Ejemplos: tmo.service, flowstation.service, bluestation.service, tetra.service"
read -p "Nombre del servicio [tmo.service]: " SERVICE_NAME
SERVICE_NAME=${SERVICE_NAME:-tmo.service}
SERVICE_NAME=$(echo "$SERVICE_NAME" | tr -cd 'A-Za-z0-9._@-')
if systemctl list-unit-files --type=service | grep -q "^${SERVICE_NAME}"; then
    ok "Servicio encontrado: $SERVICE_NAME"
else
    warn "Servicio '$SERVICE_NAME' no encontrado. Continuando de todas formas."
fi

# ── 4. MODO DE DATOS ──────────────────────────────────────────
info "Configurando modo de datos..."
echo "¿Tienes TetraPack Monitor instalado? (dashboard web en puerto 5000)"
echo "  1) Sí, tengo TetraPack Monitor"
echo "  2) No, leer directamente del servicio systemd"
read -p "Elige [1/2]: " data_opt
case $data_opt in
    1)
        DATA_MODE="monitor"
        read -p "IP del monitor, sin puerto (ej: 192.168.1.193) [localhost]: " MONITOR_IP
        MONITOR_IP=${MONITOR_IP:-localhost}
        MONITOR_IP=$(echo "$MONITOR_IP" | sed 's|:5000$||' | tr -cd 'A-Za-z0-9.:-')
        MONITOR_URL="http://${MONITOR_IP}:5000"
        ok "Modo: TetraPack Monitor ($MONITOR_URL)"
        ;;
    *)
        DATA_MODE="journalctl"
        MONITOR_URL="http://localhost:5000"
        ok "Modo: journalctl directo"
        # El usuario necesita leer el journal del servicio
        if ! id -nG "$RPIUSER" | grep -qwE "systemd-journal|adm"; then
            sudo usermod -aG systemd-journal "$RPIUSER"
            ok "Usuario $RPIUSER añadido al grupo systemd-journal"
        fi
        ;;
esac

# ── 5. ISSI LOCAL ─────────────────────────────────────────────
info "Configurando ISSI local..."
echo "Introduce el ISSI de tu terminal TETRA local (para priorizar tu TG)"
read -p "ISSI local [0]: " LOCAL_ISSI
LOCAL_ISSI=$(echo "${LOCAL_ISSI:-0}" | tr -cd '0-9')
LOCAL_ISSI=${LOCAL_ISSI:-0}
ok "ISSI local: $LOCAL_ISSI"

# ── 6. TIPO DE PANTALLA ───────────────────────────────────────
info "Configurando tipo de pantalla..."
echo "¿Qué pantalla OLED tienes?"
echo "  0) Automático - la detecta sola (recomendado)"
echo "  1) SSD1306 - 0.96\" 128x64  (la más común; también SSD1309 / SSD1315)"
echo "  2) SSD1306 - 0.91\" 128x32"
echo "  3) SH1106  - 1.3\"  128x64"
echo "  4) SH1107  - 1.5\"  128x128 (Hailege y similares)"
echo "  5) SSD1327 - 1.5\"  128x128 (ZJY-M150 y similares, escala de grises)"
read -p "Elige [0-5]: " display_opt
WIDTH=0; HEIGHT=0
case $display_opt in
    1) DISPLAY_TYPE="SSD1306" ;;
    2) DISPLAY_TYPE="SSD1306"; WIDTH=128; HEIGHT=32 ;;
    3) DISPLAY_TYPE="SH1106" ;;
    4) DISPLAY_TYPE="SH1107" ;;
    5) DISPLAY_TYPE="SSD1327" ;;
    *) DISPLAY_TYPE="AUTO" ;;
esac
ok "Pantalla: $DISPLAY_TYPE"

echo "¿La pantalla está montada girada?"
echo "  0) No   1) 90°   2) 180°   3) 270°"
read -p "Elige [0-3]: " rot_opt
case $rot_opt in
    1) ROTATE=90 ;;
    2) ROTATE=180 ;;
    3) ROTATE=270 ;;
    *) ROTATE=0 ;;
esac

# ── 7. DEPENDENCIAS DEL SISTEMA ───────────────────────────────
info "Instalando dependencias del sistema..."
sudo apt update -qq
sudo apt install -y i2c-tools swig libgpiod-dev python3-lgpio python3-full fonts-dejavu-core
ok "Dependencias instaladas"

# ── 8. ENTORNO VIRTUAL PYTHON ─────────────────────────────────
info "Creando entorno virtual Python en $RPIHOME/oled-env ..."
sudo -u "$RPIUSER" python3 -m venv "$RPIHOME/oled-env"
PIP="$RPIHOME/oled-env/bin/pip"
sudo -u "$RPIUSER" "$PIP" install --upgrade pip -q
sudo -u "$RPIUSER" "$PIP" install pillow requests -q
NEED_ADAFRUIT=0; NEED_LUMA=0
case $DISPLAY_TYPE in
    SSD1306) NEED_ADAFRUIT=1 ;;
    AUTO)    NEED_ADAFRUIT=1; NEED_LUMA=1 ;;
    *)       NEED_LUMA=1 ;;
esac
if [ "$NEED_ADAFRUIT" = 1 ]; then
    sudo -u "$RPIUSER" "$PIP" install adafruit-circuitpython-ssd1306 -q
    ok "Librería Adafruit SSD1306 instalada"
fi
if [ "$NEED_LUMA" = 1 ]; then
    sudo -u "$RPIUSER" "$PIP" install luma.oled -q
    ok "Librería luma.oled instalada"
fi

# ── 9. COPIAR MÓDULO lgpio (lo necesita la librería Adafruit) ─
if [ "$NEED_ADAFRUIT" = 1 ]; then
    info "Copiando módulo lgpio al entorno virtual..."
    LGPIO_SO=$(find /usr -name "_lgpio*.so" 2>/dev/null | head -1)
    LGPIO_PY=$(find /usr/lib/python3 -name "lgpio.py" 2>/dev/null | head -1)
    SITE=$("$RPIHOME/oled-env/bin/python3" -c "import site; print(site.getsitepackages()[0])")
    [ -n "$LGPIO_SO" ] || err "No se encontró _lgpio.so"
    sudo cp "$LGPIO_SO" "$SITE/" && ok "Copiado: $LGPIO_SO"
    if [ -n "$LGPIO_PY" ]; then
        sudo cp "$LGPIO_PY" "$SITE/" && ok "Copiado: $LGPIO_PY"
    fi
fi

# ── 10. VERIFICAR PANTALLA ────────────────────────────────────
info "Verificando detección de pantalla I2C..."
I2C_OUT=$(i2cdetect -y 1 2>/dev/null || true)
if echo "$I2C_OUT" | grep -qE " 3c| 3d"; then
    ok "Pantalla detectada en bus I2C"
else
    echo "$I2C_OUT"
    warn "Pantalla no detectada. Verifica el cableado:"
    echo "  VCC → Pin 1 (3.3V) | GND → Pin 9 o cualquier GND"
    echo "  SDA → Pin 3 (GPIO2) | SCL → Pin 5 (GPIO3)"
    read -p "¿Continuar de todas formas? [s/N]: " cont
    [[ "$cont" =~ ^[Ss]$ ]] || exit 1
fi

# ── 11. DESCARGAR SCRIPT ──────────────────────────────────────
info "Descargando tetra_oled.py desde GitHub..."
TMP=$(mktemp)
# -f: si GitHub devuelve un error no se guarda la página de error como script
curl -fsSL "${REPO}/tetra_oled.py" -o "$TMP" || err "No se pudo descargar tetra_oled.py"
python3 -m py_compile "$TMP" || err "El archivo descargado no es válido"
sudo install -m 644 -o "$RPIUSER" -g "$RPIUSER" "$TMP" "$RPIHOME/tetra_oled.py"
rm -f "$TMP"
ok "Script instalado en $RPIHOME/tetra_oled.py"

# ── 12. CONFIGURACIÓN ─────────────────────────────────────────
info "Escribiendo configuración en $CONF..."
sudo tee "$CONF" > /dev/null << CONFEOF
# TETRA OLED Display - configuración
# Tras cambiar algo: sudo systemctl restart tetra-oled
[oled]
# Servicio systemd de la estación (bluestation / FlowStation)
service_name = ${SERVICE_NAME}
# journalctl (leer el servicio) o monitor (TetraPack Monitor)
data_mode = ${DATA_MODE}
monitor_url = ${MONITOR_URL}
# ISSI de tu radio: su TG tiene prioridad en pantalla (0 = ninguno)
local_issi = ${LOCAL_ISSI}

# AUTO, SSD1306 (también SSD1309/SSD1315), SH1106, SH1107, SSD1327
display_type = ${DISPLAY_TYPE}
# 0 = buscar en 0x3C y 0x3D
display_addr = 0
i2c_bus = 1
# Resolución (0 = la habitual del modelo). SSD1306: 128x64 o 128x32; SH1106: 128x64
display_width = ${WIDTH}
display_height = ${HEIGHT}
# Giro: 0, 90, 180 o 270
display_rotate = ${ROTATE}

# Reposo: scroll (reloj + últimos oídos) o clock (solo reloj)
idle_mode = scroll
title = TETRA Monitor
# Brillo 0-255
brightness = 255
idle_brightness = 50

# Tiempos en segundos
display_timeout = 30
call_min_display = 5
sds_display = 5
# Apagar la pantalla tras este tiempo en reposo (0 = nunca)
screen_off_timeout = 0

# Base de datos de RadioID (indicativo y nombre): yes / no
radioid = yes
CONFEOF
sudo chmod 644 "$CONF"
ok "Configuración guardada"

# ── 13. SERVICIO SYSTEMD ──────────────────────────────────────
info "Creando servicio systemd..."
sudo tee /etc/systemd/system/tetra-oled.service > /dev/null << SVCEOF
[Unit]
Description=TETRA OLED Display
After=network.target ${SERVICE_NAME}

[Service]
Type=simple
User=${RPIUSER}
Group=${RPIUSER}
WorkingDirectory=${RPIHOME}
ExecStart=${RPIHOME}/oled-env/bin/python3 ${RPIHOME}/tetra_oled.py
KillSignal=SIGTERM
TimeoutStopSec=8
Restart=on-failure
RestartSec=3
# Prioridad baja: la pantalla nunca debe quitar CPU a la estación
Nice=10

[Install]
WantedBy=multi-user.target
SVCEOF

sudo systemctl daemon-reload
sudo systemctl enable tetra-oled.service
ok "Servicio creado y activado para usuario $RPIUSER"

# ── 14. RESUMEN ───────────────────────────────────────────────
echo ""
echo "════════════════════════════════════════"
echo -e "${GREEN}  Instalación completada${NC}"
echo "  Jose Maria - EA8DLF · 2026"
echo "════════════════════════════════════════"
echo "  Usuario       : $RPIUSER  ($RPIHOME)"
echo "  Zona horaria  : $TZ"
echo "  Servicio TETRA: $SERVICE_NAME"
echo "  Modo datos    : $DATA_MODE"
[ "$DATA_MODE" = "monitor" ] && echo "  Monitor URL   : $MONITOR_URL"
echo "  ISSI local    : $LOCAL_ISSI"
echo "  Pantalla      : $DISPLAY_TYPE (giro $ROTATE)"
echo "  Configuración : $CONF"
echo "  Script        : $RPIHOME/tetra_oled.py"
echo ""
echo "  Comandos útiles:"
echo "  sudo systemctl start tetra-oled"
echo "  sudo systemctl status tetra-oled"
echo "  sudo journalctl -u tetra-oled -f"
echo "  sudo nano $CONF"
echo "════════════════════════════════════════"
echo ""
read -p "¿Reiniciar ahora para aplicar cambios de I2C? [s/N]: " reinicio
[[ "$reinicio" =~ ^[Ss]$ ]] && sudo reboot
exit 0
