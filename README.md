# TETRA OLED Display

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-3.2.0-green.svg)](CHANGELOG.md)
[![Platform](https://img.shields.io/badge/platform-Raspberry%20Pi-red.svg)](https://www.raspberrypi.org/)

**Autor:** Jose Maria Minguillon — EA8DLF  
**Compatible con:** [tetra-bluestation](https://github.com/MidnightBlueLabs/tetra-bluestation) · MidnightBlueLabs

Sistema de visualización en tiempo real para redes TETRA sobre Raspberry Pi con pantalla OLED. Muestra quién transmite, indicativo, nombre, provincia, tipo de llamada y mensajes SDS — tanto locales como del resto de la red. Compatible con SSD1306 (128×64), SH1107 (128×128) y SSD1327 (128×128).

---

## Instalación rápida

```bash
bash <(curl -sSL https://raw.githubusercontent.com/EA8DLF/tetra-oled-display/main/instalar.sh)
```

El script de instalación guía paso a paso y configura todo automáticamente.

---

## Requisitos

### Hardware
| Componente | Descripción |
|---|---|
| Raspberry Pi | Modelos 3, 4 o 5 con Raspberry Pi OS 64-bit |
| Pantalla OLED | SSD1306 0.96" 128×64 I2C **o** SH1107 1.5" 128×128 I2C **o** SSD1327 1.5" 128×128 I2C (4 pines) |
| Cables | 4 jumpers hembra-hembra |

### Software
| Requisito | Descripción |
|---|---|
| tetra-bluestation | Ejecutándose como servicio systemd |
| TetraPack Monitor | **Opcional** — si no lo tienes, usa modo `journalctl` |

---

## Cableado

| Pin pantalla | Pin Raspberry | Descripción |
|---|---|---|
| VCC | Pin 1 (3.3V) | Alimentación |
| GND | Pin 9 (cualquier GND) | Masa |
| SDA | Pin 3 (GPIO2) | Datos I2C — obligatorio |
| SCL | Pin 5 (GPIO3) | Reloj I2C — obligatorio |

> El cableado es idéntico en todos los modelos de Raspberry Pi con conector GPIO de 40 pines.

---

## Modos de funcionamiento

### Modo `monitor` (TetraPack Monitor)
Lee los logs a través del dashboard web de TetraPack Monitor. Requiere tenerlo instalado y corriendo en el puerto 5000.

```python
DATA_MODE   = "monitor"
MONITOR_URL = "http://localhost:5000"
```

### Modo `journalctl` (sin dashboard)
Lee los logs directamente desde el servicio systemd. **No requiere ningún dashboard adicional.** Compatible con cualquier instalación de tetra-bluestation.

```python
DATA_MODE    = "journalctl"
SERVICE_NAME = "tmo.service"   # ← cambia por el nombre de tu servicio
```

---

## Configuración

Edita `tetra_oled.py` y ajusta la sección de configuración al principio del archivo:

```python
# ─── CONFIGURACIÓN ────────────────────────────────────────────
SERVICE_NAME    = "tmo.service"   # nombre de tu servicio systemd
DATA_MODE       = "monitor"       # "monitor" o "journalctl"
MONITOR_URL     = "http://localhost:5000"  # si DATA_MODE = "monitor"
LOCAL_ISSI      = "0"       # ISSI de tu terminal local
BREW_URL        = "http://TU_SERVIDOR_XLX:PUERTO/api/brew/calls"  # servidor XLX

DISPLAY_TIMEOUT     = 30   # segundos hasta standby
CALL_MIN_DISPLAY    = 5    # segundos mínimo para llamadas
SDS_DISPLAY         = 5    # segundos para SDS
SCREEN_OFF_TIMEOUT  = 300  # segundos hasta apagar pantalla
```

> Tras cualquier cambio: `sudo systemctl restart tetra-oled`

### Adaptar al nombre de tu servicio

Cada instalación de tetra-bluestation puede tener un nombre de servicio diferente. Comprueba el tuyo con:

```bash
systemctl list-units --type=service | grep -iE "tetra|bluestation|tmo"
```

Y cambia `SERVICE_NAME` en `tetra_oled.py` o responde a la pregunta durante la instalación.

---

## Pantallas

### Standby
```
┌─────────────────────┐
│   TETRA Monitor     │  ← título centrado (fondo amarillo)
│      01:30:00       │  ← hora local automática
│ 33.1°C     5.0V OK  │  ← temperatura y voltaje
│ IP 192.168.1.193    │  ← IP local
└─────────────────────┘
```

### Llamada de voz — Grupo
```
┌─────────────────────┐
│ EA8DLF 2150212      │  ← indicativo + ID DMR
│ Jose Maria          │  ← nombre completo
│ Las Palmas          │  ← provincia / población
│ [VOZ]               │  ← tipo de llamada
│ TG:9990             │  ← TalkGroup
└─────────────────────┘
```

### Llamada de voz — Privada
```
┌─────────────────────┐
│ EA8DLF 2150212      │
│ Jose Maria          │
│ Las Palmas          │
│ EA8DLF -> EA5YY     │  ← origen y destino
│ [VOZ PRIV]          │
└─────────────────────┘
```

### Llamada de red (otro usuario)
```
┌─────────────────────┐
│ EA7KEN 2145007      │
│ Pedro Martinez      │
│ Sevilla             │
│ [NET VOZ]           │
│ TG:214              │
└─────────────────────┘
```

### Mensaje SDS
```
┌─────────────────────┐
│ EA8DLF 2150212      │
│ Jose Maria          │
│ Las Palmas          │
│ EA8DLF -> 9999      │
│ [SDS T3]            │
└─────────────────────┘
```

### Estados especiales
| Pantalla | Cuándo aparece |
|---|---|
| `Iniciando...` | Al arrancar o reiniciar el servicio |
| `Reiniciando...` | Al ejecutar `sudo reboot` |
| `Apagando...` | Al ejecutar `sudo shutdown` |

---

## Características

- ✅ Llamadas de voz locales (grupo y privada)
- ✅ Llamadas de red en tiempo real (otros usuarios en la red)
- ✅ Mensajes SDS locales y de red
- ✅ Prioridad inteligente de TG (no reemplaza el TG seleccionado)
- ✅ Indicativos y nombres desde [radioid.net](https://radioid.net) (actualización automática diaria)
- ✅ Hora local automática según ubicación geográfica
- ✅ Temperatura, voltaje e IP en standby
- ✅ Anti-quemado: pixel shift suave + apagado tras 5 minutos
- ✅ Brillo reducido en standby, máximo en eventos
- ✅ Sin parpadeo en cambios de slot/speaker (timer cancelable)
- ✅ Arranque automático con systemd
- ✅ Reconexión automática al stream
- ✅ Compatible con y sin TetraPack Monitor

---

## Gestión del servicio

```bash
sudo systemctl start tetra-oled      # iniciar
sudo systemctl stop tetra-oled       # parar
sudo systemctl restart tetra-oled    # reiniciar tras cambios
sudo systemctl status tetra-oled     # estado
sudo journalctl -u tetra-oled -f     # logs en tiempo real
```

---

## Solución de problemas

**La pantalla no enciende**
- Comprueba el cableado: VCC→Pin1, GND→cualquier GND, SDA→Pin3, SCL→Pin5
- Ejecuta `i2cdetect -y 1` → debe aparecer `3c`
- Si no aparece, prueba con Pin 2 (5V) en lugar de Pin 1 (3.3V)

**El servicio no arranca**
- `sudo systemctl status tetra-oled` → ver el error
- Comprueba que el entorno virtual existe: `ls ~/oled-env/bin/python3`
- Activa el inicio automático: `sudo systemctl enable tetra-oled`

**No aparecen indicativos**
- La BD de radioid.net se descarga al arrancar (puede tardar 1-2 min)
- Comprueba acceso a Internet desde la Raspberry
- El indicativo debe estar registrado en [radioid.net](https://radioid.net)

**La hora es incorrecta**
- `timedatectl` → comprueba la zona horaria
- `sudo timedatectl set-timezone Atlantic/Canary` → corregir

**La pantalla está apagada**
- Normal: se apaga tras 5 min sin actividad
- Se enciende sola al detectar tráfico
- Para encenderla: `sudo systemctl restart tetra-oled`

---

## Licencia

Este proyecto está bajo la licencia [MIT](LICENSE).  
Puedes usarlo, modificarlo y distribuirlo libremente citando al autor.

---

*Compatible con tetra-bluestation · MidnightBlueLabs*

---

## English Summary

**TETRA OLED Display** is a real-time monitoring system for TETRA radio networks, designed to run on a Raspberry Pi with an SSD1306, SH1107 or SSD1327 OLED display. It shows who is transmitting, their callsign, name, province, call type, TalkGroup, and SDS messages — both local and network-wide.

### Quick Install

```bash
bash <(curl -sSL https://raw.githubusercontent.com/EA8DLF/Tetra-oled-display/main/instalar.sh)
```

### Compatible Displays

| Model | Size | Resolution |
|---|---|---|
| SSD1306 | 0.96" | 128×64 |
| SH1107 | 1.5" | 128×128 |
| SSD1327 | 1.5" | 128×128 (grayscale) |

### Wiring (all Raspberry Pi models with 40-pin GPIO)

| Display pin | Raspberry Pi pin | Description |
|---|---|---|
| VCC | Pin 1 (3.3V) | Power |
| GND | Pin 9 (any GND) | Ground |
| SDA | Pin 3 (GPIO2) | I2C Data — required |
| SCL | Pin 5 (GPIO3) | I2C Clock — required |

### Operating Modes

- **`monitor`** — reads logs from TetraPack Monitor dashboard (port 5000)
- **`journalctl`** — reads logs directly from the systemd service, no dashboard required

### Key Configuration (`tetra_oled.py`)

```python
SERVICE_NAME  = "tmo.service"   # your bluestation systemd service name
DATA_MODE     = "monitor"       # "monitor" or "journalctl"
MONITOR_URL   = "http://localhost:5000"
DISPLAY_TYPE  = "SSD1306"       # "SSD1306", "SH1107" o "SSD1327"
LOCAL_ISSI    = "0"             # your local terminal ISSI (for TG priority)
```

### Features

- ✅ Local voice calls (group and private)
- ✅ Network voice calls in real time (other users)
- ✅ Local and network SDS messages
- ✅ Smart TG priority (selected TG is not replaced by lower priority calls)
- ✅ Callsigns and names from [radioid.net](https://radioid.net) (auto-updated daily)
- ✅ Automatic local time based on geolocation
- ✅ Temperature, voltage and IP on standby screen
- ✅ Anti-burn protection: smooth pixel shift + auto power-off after 5 min
- ✅ systemd service with auto-start on boot
- ✅ Works with or without TetraPack Monitor

### Troubleshooting

**Screen not detected** — run `i2cdetect -y 1`. Should show `3c`. If not, try powering from Pin 2 (5V).

**SH1107 not responding** — some units use address `0x3D`. Check with `i2cdetect -y 1` and set `DISPLAY_ADDR = 0x3D` in `tetra_oled.py`.

**No callsigns shown** — radioid.net database downloads on first start (may take 1-2 min). Requires internet access.

### License

MIT License — free to use, modify and distribute with attribution.
