#!/bin/bash

# ═══════════════════════════════════════════════════════════════
#  TETRA OLED Display - Script de actualización v3.5.0
#  Jose Maria - EA8DLF · 2026
#  https://github.com/EA8DLF/Tetra-oled-display
# ═══════════════════════════════════════════════════════════════

set -e

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
REPO="https://raw.githubusercontent.com/EA8DLF/Tetra-oled-display/main"
CONF=/etc/tetra-oled.conf

ok()   { echo -e "${GREEN}[OK]${NC} $1"; }
info() { echo -e "${YELLOW}[INFO]${NC} $1"; }
err()  { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

# Valor de una clave en la configuración (vacío si no está)
conf_get() {
    sed -n "s/^[[:space:]]*$1[[:space:]]*=[[:space:]]*//p" "$CONF" 2>/dev/null | tail -1 | tr -d '"\r'
}

echo "════════════════════════════════════════"
echo "  TETRA OLED Display - Actualización v3.5.0"
echo "  Jose Maria - EA8DLF · 2026"
echo "════════════════════════════════════════"

# ── 1. DETECTAR USUARIO ───────────────────────────────────────
info "Detectando instalación existente..."
DEFAULT_USER=$(logname 2>/dev/null || echo "${SUDO_USER:-pi}")
read -p "Usuario de la Raspberry Pi [$DEFAULT_USER]: " RPIUSER
RPIUSER=${RPIUSER:-$DEFAULT_USER}
RPIHOME=$(getent passwd "$RPIUSER" | cut -d: -f6)
SCRIPT="$RPIHOME/tetra_oled.py"

if [ -z "$RPIHOME" ] || [ ! -f "$SCRIPT" ]; then
    err "No se encontró $SCRIPT. ¿Es correcto el usuario '$RPIUSER'?"
fi
ok "Instalación encontrada en $RPIHOME"

# ── 2. CONFIGURACIÓN ──────────────────────────────────────────
if [ -f "$CONF" ]; then
    ok "Configuración existente: $CONF (no se modifica)"
else
    # Versiones anteriores a la 3.5.0 guardaban la configuración dentro del
    # propio script: se pasa a $CONF para que las actualizaciones no la toquen.
    info "Migrando la configuración del script a $CONF..."
    old_str() { grep -m1 "^$1 *=" "$SCRIPT" | sed "s/^[^=]*= *\"//;s/\".*//"; }
    old_raw() { grep -m1 "^$1 *=" "$SCRIPT" | sed "s/^[^=]*= *//;s/ .*//"; }
    SERVICE_NAME=$(old_str SERVICE_NAME)
    DATA_MODE=$(old_str DATA_MODE)
    MONITOR_URL=$(old_str MONITOR_URL)
    LOCAL_ISSI=$(old_str LOCAL_ISSI)
    DISPLAY_TYPE=$(old_str DISPLAY_TYPE)
    DISPLAY_ADDR=$(old_raw DISPLAY_ADDR)
    sudo tee "$CONF" > /dev/null << CONFEOF
# TETRA OLED Display - configuración (migrada desde el script)
# Tras cambiar algo: sudo systemctl restart tetra-oled
[oled]
service_name = ${SERVICE_NAME:-tmo.service}
data_mode = ${DATA_MODE:-journalctl}
monitor_url = ${MONITOR_URL:-http://localhost:5000}
local_issi = ${LOCAL_ISSI:-0}

# AUTO, SSD1306 (también SSD1309/SSD1315), SH1106, SH1107, SSD1327
display_type = ${DISPLAY_TYPE:-SSD1306}
# 0 = buscar en 0x3C y 0x3D
display_addr = ${DISPLAY_ADDR:-0x3C}
i2c_bus = 1
# Resolución (0 = la habitual del modelo) y giro (0, 90, 180, 270)
display_width = 0
display_height = 0
display_rotate = 0

# Reposo: scroll (reloj + últimos oídos) o clock (solo reloj)
idle_mode = scroll
title = TETRA Monitor
brightness = 255
idle_brightness = 50

display_timeout = 30
call_min_display = 5
sds_display = 5
# Apagar la pantalla tras este tiempo en reposo (0 = nunca)
screen_off_timeout = 0

radioid = yes
CONFEOF
    sudo chmod 644 "$CONF"
    ok "Configuración migrada"
fi

SERVICE_NAME=$(conf_get service_name)
DATA_MODE=$(conf_get data_mode)
DISPLAY_TYPE=$(conf_get display_type | tr '[:lower:]' '[:upper:]')
echo ""
echo "  Configuración ($CONF):"
echo "  ├─ Servicio TETRA : $SERVICE_NAME"
echo "  ├─ Modo datos     : $DATA_MODE"
echo "  ├─ ISSI local     : $(conf_get local_issi)"
echo "  ├─ Pantalla       : $DISPLAY_TYPE"
echo "  └─ Reposo         : $(conf_get idle_mode)"
echo ""
read -p "¿Continuar con la actualización? [S/n]: " seguir
if [[ "$seguir" =~ ^[Nn]$ ]]; then
    err "Cancelado. Puedes editar la configuración con: sudo nano $CONF"
fi

# ── 3. DESCARGAR NUEVA VERSIÓN (antes de parar nada) ──────────
info "Descargando nueva versión desde GitHub..."
TMP=$(mktemp)
curl -fsSL "${REPO}/tetra_oled.py" -o "$TMP" || err "No se pudo descargar tetra_oled.py (no se ha cambiado nada)"
python3 -m py_compile "$TMP" || err "El archivo descargado no es válido (no se ha cambiado nada)"
ok "Descarga verificada"

# ── 4. PARAR SERVICIO Y COPIA DE SEGURIDAD ────────────────────
info "Parando servicio..."
sudo systemctl stop tetra-oled 2>/dev/null || true
BACKUP="$RPIHOME/tetra_oled.py.bak_$(date +%Y%m%d_%H%M%S)"
cp "$SCRIPT" "$BACKUP"
ok "Copia guardada en $BACKUP"

sudo install -m 644 -o "$RPIUSER" -g "$RPIUSER" "$TMP" "$SCRIPT"
rm -f "$TMP"
ok "Script actualizado"

# ── 5. DEPENDENCIAS ───────────────────────────────────────────
PIP="$RPIHOME/oled-env/bin/pip"
case $DISPLAY_TYPE in
    SH1106|SH1107|SSD1327|AUTO)
        info "Asegurando librería luma.oled..."
        sudo -u "$RPIUSER" "$PIP" install luma.oled -q
        ok "luma.oled instalada"
        ;;
esac
case $DISPLAY_TYPE in
    SSD1306|AUTO)
        sudo -u "$RPIUSER" "$PIP" install adafruit-circuitpython-ssd1306 -q
        ok "Librería Adafruit SSD1306 lista"
        ;;
esac
if ! fc-list 2>/dev/null | grep -q DejaVuSansMono; then
    sudo apt install -y fonts-dejavu-core > /dev/null && ok "Fuentes DejaVu instaladas"
fi
if [ "$DATA_MODE" = "journalctl" ] && ! id -nG "$RPIUSER" | grep -qwE "systemd-journal|adm"; then
    sudo usermod -aG systemd-journal "$RPIUSER"
    ok "Usuario $RPIUSER añadido al grupo systemd-journal"
fi

# ── 6. VELOCIDAD I2C SEGURA ───────────────────────────────────
# Versiones antiguas forzaban el bus a 400kHz, lo que rompe algunos SSD1327
# (error "I2C device not found"). Lo bajamos a la velocidad estándar (100kHz).
NEEDS_REBOOT=0
BOOTCFG=/boot/firmware/config.txt
[ -f "$BOOTCFG" ] || BOOTCFG=/boot/config.txt
if grep -q "i2c_arm_baudrate=400000" "$BOOTCFG" 2>/dev/null; then
    info "Bajando el bus I2C de 400kHz a 100kHz (más fiable)..."
    sudo sed -i 's/dtparam=i2c_arm=on.*/dtparam=i2c_arm=on/' "$BOOTCFG"
    NEEDS_REBOOT=1
    ok "I2C a 100kHz (requiere reinicio para aplicarse)"
fi

# ── 7. ACTUALIZAR SERVICIO SYSTEMD ────────────────────────────
info "Actualizando servicio systemd..."
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
ok "Servicio systemd actualizado"

# ── 8. REINICIAR ──────────────────────────────────────────────
if [ "$NEEDS_REBOOT" = "1" ]; then
    echo -e "${YELLOW}[IMPORTANTE]${NC} Se cambió la velocidad del bus I2C."
    echo "  REINICIA la Raspberry Pi para que la pantalla funcione:  sudo reboot"
else
    info "Reiniciando servicio..."
    sudo systemctl start tetra-oled
    sleep 3
    if sudo systemctl is-active --quiet tetra-oled; then
        ok "Servicio activo y corriendo"
    else
        echo -e "${RED}[ERROR]${NC} El servicio no arrancó. Revisa los logs:"
        echo "  sudo journalctl -u tetra-oled -n 30"
        echo "  Para volver a la versión anterior: cp $BACKUP $SCRIPT"
        exit 1
    fi
fi

# ── 9. RESUMEN ────────────────────────────────────────────────
echo ""
echo "════════════════════════════════════════"
echo -e "${GREEN}  Actualización completada${NC}"
echo "  Jose Maria - EA8DLF · 2026"
echo "════════════════════════════════════════"
echo "  Usuario       : $RPIUSER"
echo "  Script        : $SCRIPT"
echo "  Configuración : $CONF"
echo "  Copia previa  : $BACKUP"
echo ""
echo "  sudo journalctl -u tetra-oled -f"
echo "════════════════════════════════════════"
