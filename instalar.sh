#!/bin/bash

# ═══════════════════════════════════════════════════════════════
#  TETRA OLED Display - Script de instalación v3.1
#  Jose Maria - EA8DLF · 2026
#  https://github.com/EA8DLF/Tetra-oled-display
# ═══════════════════════════════════════════════════════════════

set -e

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
REPO="https://raw.githubusercontent.com/EA8DLF/Tetra-oled-display/main"

ok()   { echo -e "${GREEN}[OK]${NC} $1"; }
info() { echo -e "${YELLOW}[INFO]${NC} $1"; }
err()  { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

echo "════════════════════════════════════════"
echo "  TETRA OLED Display - Instalación v3.1"
echo "  Jose Maria - EA8DLF · 2026"
echo "════════════════════════════════════════"

# ── 0. USUARIO DE LA RASPBERRY ────────────────────────────────
info "Detectando usuario..."
DEFAULT_USER=$(logname 2>/dev/null || echo "${SUDO_USER:-pi}")
read -p "Usuario de la Raspberry Pi [$DEFAULT_USER]: " RPIUSER
RPIUSER=${RPIUSER:-$DEFAULT_USER}
RPIHOME="/home/$RPIUSER"

if [ ! -d "$RPIHOME" ]; then
    err "El directorio $RPIHOME no existe. Comprueba el nombre de usuario."
fi
ok "Usuario: $RPIUSER  |  Home: $RPIHOME"

# ── 1. CONFIGURAR I2C ─────────────────────────────────────────
info "Activando I2C..."
sudo raspi-config nonint do_i2c 0
CONFIG=/boot/firmware/config.txt
if grep -q "dtparam=i2c_arm=on" $CONFIG; then
    sudo sed -i 's/dtparam=i2c_arm=on.*/dtparam=i2c_arm=on,i2c_arm_baudrate=400000/' $CONFIG
else
    echo "dtparam=i2c_arm=on,i2c_arm_baudrate=400000" | sudo tee -a $CONFIG
fi
ok "I2C configurado a 400kHz"

# ── 2. ZONA HORARIA ───────────────────────────────────────────
info "Configurando zona horaria..."
echo "¿Cuál es tu zona horaria?"
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
echo "¿Cómo se llama tu servicio systemd de bluestation?"
echo "  Ejemplos: tmo.service, bluestation.service, tetra.service"
read -p "Nombre del servicio [tmo.service]: " SERVICE_NAME
SERVICE_NAME=${SERVICE_NAME:-tmo.service}
if systemctl list-units --type=service | grep -q "${SERVICE_NAME}"; then
    ok "Servicio encontrado: $SERVICE_NAME"
else
    echo -e "${YELLOW}[AVISO]${NC} Servicio '$SERVICE_NAME' no encontrado. Continuando de todas formas."
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
        MONITOR_IP=$(echo "$MONITOR_IP" | sed 's|:5000$||')
        MONITOR_URL="http://${MONITOR_IP}:5000"
        ok "Modo: TetraPack Monitor ($MONITOR_URL)"
        ;;
    *)
        DATA_MODE="journalctl"
        MONITOR_URL="http://localhost:5000"
        ok "Modo: journalctl directo"
        ;;
esac

# ── 5. ISSI LOCAL ─────────────────────────────────────────────
info "Configurando ISSI local..."
echo "Introduce el ISSI de tu terminal TETRA local (para priorizar tu TG)"
read -p "ISSI local [0]: " LOCAL_ISSI
LOCAL_ISSI=${LOCAL_ISSI:-0}
ok "ISSI local: $LOCAL_ISSI"

# ── 6. DEPENDENCIAS DEL SISTEMA ───────────────────────────────
info "Instalando dependencias del sistema..."
sudo apt update -qq
sudo apt install -y i2c-tools swig libgpiod-dev python3-lgpio python3-full
ok "Dependencias instaladas"

# ── 7. ENTORNO VIRTUAL PYTHON ─────────────────────────────────
info "Creando entorno virtual Python en $RPIHOME/oled-env ..."
sudo -u "$RPIUSER" python3 -m venv "$RPIHOME/oled-env"
sudo -u "$RPIUSER" "$RPIHOME/oled-env/bin/pip" install --upgrade pip -q
sudo -u "$RPIUSER" "$RPIHOME/oled-env/bin/pip" install \
    adafruit-circuitpython-ssd1306 pillow requests pytz -q
ok "Paquetes Python instalados"

# ── 8. COPIAR MÓDULO lgpio ────────────────────────────────────
info "Copiando módulo lgpio al entorno virtual..."
LGPIO_SO=$(find /usr -name "_lgpio*.so" 2>/dev/null | head -1)
LGPIO_PY=$(find /usr/lib/python3 -name "lgpio.py" 2>/dev/null | head -1)
SITE=$("$RPIHOME/oled-env/bin/python3" -c "import site; print(site.getsitepackages()[0])")
[ -n "$LGPIO_SO" ] && sudo cp "$LGPIO_SO" "$SITE/" && ok "Copiado: $LGPIO_SO" || err "No se encontró _lgpio.so"
[ -n "$LGPIO_PY" ] && sudo cp "$LGPIO_PY" "$SITE/" && ok "Copiado: $LGPIO_PY"

# ── 9. VERIFICAR PANTALLA ─────────────────────────────────────
info "Verificando detección de pantalla I2C..."
I2C_OUT=$(i2cdetect -y 1 2>/dev/null)
if echo "$I2C_OUT" | grep -q "3c\|3d"; then
    ok "Pantalla detectada en bus I2C"
else
    echo "$I2C_OUT"
    echo -e "${YELLOW}[AVISO]${NC} Pantalla no detectada. Verifica el cableado:"
    echo "  VCC → Pin 1 (3.3V) | GND → Pin 9 o cualquier GND"
    echo "  SDA → Pin 3 (GPIO2) | SCL → Pin 5 (GPIO3)"
    read -p "¿Continuar de todas formas? [s/N]: " cont
    [[ "$cont" =~ ^[Ss]$ ]] || exit 1
fi

# ── 9b. TIPO DE PANTALLA ──────────────────────────────────────
info "Configurando tipo de pantalla..."
echo "¿Qué modelo de pantalla OLED tienes?"
echo "  1) SSD1306 - 0.96\" 128x64  (la más común, 4 pines)"
echo "  2) SH1107  - 1.5\"  128x128 (Hailege y similares, 4 pines)"
echo "  3) SSD1327 - 1.5\"  128x128 (ZJY-M150 y similares, escala de grises)"
read -p "Elige [1/2/3]: " display_opt
case $display_opt in
    2)
        DISPLAY_TYPE="SH1107"
        ok "Pantalla: SH1107 128x128"
        sudo -u "$RPIUSER" "$RPIHOME/oled-env/bin/pip" install adafruit-circuitpython-sh1107 -q
        ok "Librería SH1107 instalada"
        ;;
    3)
        DISPLAY_TYPE="SSD1327"
        ok "Pantalla: SSD1327 128x128 (escala de grises)"
        sudo -u "$RPIUSER" "$RPIHOME/oled-env/bin/pip" install adafruit-circuitpython-ssd1327 -q
        ok "Librería SSD1327 instalada"
        ;;
    *)
        DISPLAY_TYPE="SSD1306"
        ok "Pantalla: SSD1306 128x64"
        ;;
esac
DISPLAY_ADDR=0x3C
ok "Dirección I2C: $DISPLAY_ADDR (por defecto)"

# ── 10. DESCARGAR Y CONFIGURAR SCRIPT ─────────────────────────
info "Descargando tetra_oled.py desde GitHub..."
curl -sSL "${REPO}/tetra_oled.py" -o "$RPIHOME/tetra_oled.py"
chown "$RPIUSER:$RPIUSER" "$RPIHOME/tetra_oled.py"

# Aplicar configuración
sed -i "s|SERVICE_NAME         = \"tmo.service\"|SERVICE_NAME         = \"${SERVICE_NAME}\"|"   "$RPIHOME/tetra_oled.py"
sed -i "s|DATA_MODE            = \"monitor\"|DATA_MODE            = \"${DATA_MODE}\"|"           "$RPIHOME/tetra_oled.py"
sed -i "s|MONITOR_URL          = \"http://localhost:5000\"|MONITOR_URL          = \"${MONITOR_URL}\"|" "$RPIHOME/tetra_oled.py"
sed -i "s|LOCAL_ISSI           = \"0\"|LOCAL_ISSI           = \"${LOCAL_ISSI}\"|"               "$RPIHOME/tetra_oled.py"
sed -i "s|DISPLAY_TYPE         = \"SSD1306\"|DISPLAY_TYPE         = \"${DISPLAY_TYPE}\"|"       "$RPIHOME/tetra_oled.py"
sed -i "s|DISPLAY_ADDR         = 0x3C|DISPLAY_ADDR         = ${DISPLAY_ADDR}|"                 "$RPIHOME/tetra_oled.py"
ok "Script configurado en $RPIHOME/tetra_oled.py"

# ── 11. SERVICIO SYSTEMD ──────────────────────────────────────
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
TimeoutStopSec=5
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
SVCEOF

sudo systemctl daemon-reload
sudo systemctl enable tetra-oled.service
ok "Servicio creado y activado para usuario $RPIUSER"

# ── 12. RESUMEN ───────────────────────────────────────────────
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
echo "  Pantalla      : $DISPLAY_TYPE ($DISPLAY_ADDR)"
echo "  Script        : $RPIHOME/tetra_oled.py"
echo ""
echo "  Comandos útiles:"
echo "  sudo systemctl start tetra-oled"
echo "  sudo systemctl stop tetra-oled"
echo "  sudo systemctl status tetra-oled"
echo "  sudo journalctl -u tetra-oled -f"
echo "════════════════════════════════════════"
echo ""
read -p "¿Reiniciar ahora para aplicar cambios de I2C? [s/N]: " reinicio
[[ "$reinicio" =~ ^[Ss]$ ]] && sudo reboot
