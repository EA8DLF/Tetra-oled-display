#!/bin/bash

# ═══════════════════════════════════════════════════════════════
#  TETRA OLED Display - Script de actualización v3.1
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
echo "  TETRA OLED Display - Actualización"
echo "  Jose Maria - EA8DLF · 2026"
echo "════════════════════════════════════════"

# ── 1. DETECTAR USUARIO ───────────────────────────────────────
info "Detectando instalación existente..."
DEFAULT_USER=$(logname 2>/dev/null || echo "${SUDO_USER:-pi}")
read -p "Usuario de la Raspberry Pi [$DEFAULT_USER]: " RPIUSER
RPIUSER=${RPIUSER:-$DEFAULT_USER}
RPIHOME="/home/$RPIUSER"

SCRIPT="$RPIHOME/tetra_oled.py"

if [ ! -f "$SCRIPT" ]; then
    err "No se encontró $SCRIPT. ¿Es correcto el usuario '$RPIUSER'?"
fi
ok "Instalación encontrada en $RPIHOME"

# ── 2. LEER CONFIGURACIÓN ACTUAL ──────────────────────────────
info "Leyendo configuración actual..."
SERVICE_NAME=$(grep 'SERVICE_NAME' "$SCRIPT" | head -1 | sed "s/.*= *\"//;s/\".*//")
DATA_MODE=$(grep 'DATA_MODE' "$SCRIPT" | head -1 | sed "s/.*= *\"//;s/\".*//")
MONITOR_URL=$(grep 'MONITOR_URL' "$SCRIPT" | head -1 | sed "s/.*= *\"//;s/\".*//")
LOCAL_ISSI=$(grep 'LOCAL_ISSI' "$SCRIPT" | head -1 | sed "s/.*= *\"//;s/\".*//")
DISPLAY_TYPE=$(grep 'DISPLAY_TYPE' "$SCRIPT" | head -1 | sed "s/.*= *\"//;s/\".*//")
DISPLAY_ADDR=$(grep 'DISPLAY_ADDR' "$SCRIPT" | head -1 | sed "s/.*= *//;s/ .*//" )

echo ""
echo "  Configuración detectada:"
echo "  ├─ Servicio TETRA : $SERVICE_NAME"
echo "  ├─ Modo datos     : $DATA_MODE"
echo "  ├─ Monitor URL    : $MONITOR_URL"
echo "  ├─ ISSI local     : $LOCAL_ISSI"
echo "  ├─ Pantalla       : $DISPLAY_TYPE"
echo "  └─ Dirección I2C  : $DISPLAY_ADDR"
echo ""
read -p "¿Mantener esta configuración? [S/n]: " mantener
if [[ "$mantener" =~ ^[Nn]$ ]]; then
    err "Edita manualmente $SCRIPT o ejecuta instalar.sh para reinstalar."
fi

# ── 3. PARAR SERVICIO ─────────────────────────────────────────
info "Parando servicio..."
sudo systemctl stop tetra-oled 2>/dev/null || true
ok "Servicio parado"

# ── 4. HACER COPIA DE SEGURIDAD ───────────────────────────────
info "Haciendo copia de seguridad..."
BACKUP="$RPIHOME/tetra_oled.py.bak_$(date +%Y%m%d_%H%M%S)"
cp "$SCRIPT" "$BACKUP"
ok "Copia guardada en $BACKUP"

# ── 5. DESCARGAR NUEVA VERSIÓN ────────────────────────────────
info "Descargando nueva versión desde GitHub..."
curl -sSL "${REPO}/tetra_oled.py" -o "$SCRIPT"
chown "$RPIUSER:$RPIUSER" "$SCRIPT"
ok "Script actualizado"

# ── 6. RESTAURAR CONFIGURACIÓN ────────────────────────────────
info "Restaurando tu configuración..."
sed -i "s|SERVICE_NAME         = \"tmo.service\"|SERVICE_NAME         = \"${SERVICE_NAME}\"|"   "$SCRIPT"
sed -i "s|DATA_MODE            = \"monitor\"|DATA_MODE            = \"${DATA_MODE}\"|"           "$SCRIPT"
sed -i "s|MONITOR_URL          = \"http://localhost:5000\"|MONITOR_URL          = \"${MONITOR_URL}\"|" "$SCRIPT"
sed -i "s|LOCAL_ISSI           = \"0\"|LOCAL_ISSI           = \"${LOCAL_ISSI}\"|"               "$SCRIPT"
sed -i "s|DISPLAY_TYPE         = \"SSD1306\"|DISPLAY_TYPE         = \"${DISPLAY_TYPE}\"|"       "$SCRIPT"
sed -i "s|DISPLAY_ADDR         = 0x3C|DISPLAY_ADDR         = ${DISPLAY_ADDR}|"                 "$SCRIPT"
ok "Configuración restaurada"

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
ExecStop=-/bin/kill -SIGTERM \$MAINPID
TimeoutStopSec=5
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
SVCEOF

sudo systemctl daemon-reload
ok "Servicio systemd actualizado"

# ── 8. REINICIAR ──────────────────────────────────────────────
info "Reiniciando servicio..."
sudo systemctl start tetra-oled
sleep 2
if sudo systemctl is-active --quiet tetra-oled; then
    ok "Servicio activo y corriendo"
else
    echo -e "${RED}[ERROR]${NC} El servicio no arrancó. Revisa los logs:"
    echo "  sudo journalctl -u tetra-oled -f"
    exit 1
fi

# ── 9. RESUMEN ────────────────────────────────────────────────
echo ""
echo "════════════════════════════════════════"
echo -e "${GREEN}  Actualización completada${NC}"
echo "  Jose Maria - EA8DLF · 2026"
echo "════════════════════════════════════════"
echo "  Usuario    : $RPIUSER"
echo "  Script     : $SCRIPT"
echo "  Copia prev.: $BACKUP"
echo ""
echo "  sudo journalctl -u tetra-oled -f"
echo "════════════════════════════════════════"
