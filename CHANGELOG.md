# Changelog

## [3.3.1] - 2026-05-14

### Corregido
- Voltaje: usa `vcgencmd get_throttled` en lugar de `measure_volts` (compatible con todos los modelos)
- Pantalla muestra `5.0V OK` cuando la alimentación es correcta o `⚠ VOLT` si hay problema real
- Si `vcgencmd` no está disponible, el voltaje no se muestra (en lugar de mostrar `0V`)
- `instalar.sh`: añadida dependencia `libopenjp2-7` (requerida por Pillow)

---

## [3.3.0] - 2026-05-14

### Añadido
- Script `actualizar.sh`: actualización sin perder configuración, con copia de seguridad automática
- El instalador pregunta el usuario del sistema (no asume `pi`)
- Compatible con Raspberry Pi 2B
- Manual v3.3 con sección de actualización y nuevo paso de usuario en la instalación

### Corregido
- `instalar.sh`: servicio systemd usa el usuario real (`User=`, `Group=`, rutas) en lugar de `pi` hardcodeado
- `tetra_oled.py`: `CACHE_FILE` usa `os.path.expanduser("~")` en lugar de `/home/pi/` hardcodeado
- URL del script de instalación corregida en README e `instalar.sh` (mayúscula en `Tetra-oled-display`)

---

## [3.2.0] - 2026-05-12

### Añadido
- Soporte para pantalla SSD1327 1.5" 128×128 (ZJY-M150 y similares, escala de grises)
- Opción 3 en el script de instalación para seleccionar SSD1327
- Instalación automática de `adafruit-circuitpython-ssd1327` al elegir SSD1327
- Layout 128×128 reutilizado del SH1107 (fuentes grandes, más información visible)

---

## [3.1.0] - 2026-05-10

### Añadido
- Soporte para pantalla SH1107 1.5" 128×128 (Hailege y similares)
- Variable `DISPLAY_TYPE` para seleccionar entre SSD1306 y SH1107
- Variable `DISPLAY_ADDR` para configurar dirección I2C (0x3C o 0x3D)
- Layout rediseñado para SH1107 con fuentes más grandes y más información visible
- Script de instalación pregunta automáticamente qué pantalla tiene el usuario

---

## [3.0.0] - 2026-05-10

### Añadido
- Soporte dual: TetraPack Monitor y lectura directa via `journalctl`
- Compatible con cualquier instalación de tetra-bluestation
- Nombre del servicio systemd configurable (`SERVICE_NAME`)
- ISSI local configurable para priorizar TG seleccionado (`LOCAL_ISSI`)
- Sistema de prioridad de TG: el TG del terminal local tiene prioridad
- Detección de llamadas de red en tiempo real desde el log de bluestation
- Detección de SDS de red (`BrewWorker: SHORT_TRANSFER`)
- Prioridad inteligente: no reemplaza pantalla si hay llamada prioritaria activa
- Reloj en tiempo real durante eventos (se actualiza cada segundo)
- Pixel shift suave basado en función seno (anti-quemado)
- Apagado automático de pantalla tras 5 minutos sin actividad
- Timer cancelable para cambios de slot/speaker sin parpadeo
- `truncate()` optimizado con búsqueda binaria
- Recarga automática de radioid.net tras pérdida de red
- Señal de apagado/reinicio diferenciada (`SIGTERM`)

### Mejorado
- Tiempos de visualización configurables (llamadas: 5s, SDS: 5s)
- Reconexión del stream en 1 segundo (antes 5s)
- Brillo reducido en standby (50/255)
- Base de datos radioid.net sin race condition en carga

### Corregido
- Doble carga de radioid.net al arrancar
- Flash a standby en cambios de slot/speaker
- Texto de grados `°C` correcto
- Destino SDS sin prefijo `ISSI:` cuando no está en la BD

---

## [2.0.0] - 2026-05-10

### Añadido
- Pantalla standby con IP, temperatura, voltaje y hora
- Hora local automática según zona horaria por IP
- Protección anti-quemado con pixel shift aleatorio
- Mensajes de estado: Iniciando, Reiniciando, Apagando
- Base de datos radioid.net con actualización diaria automática
- Brillo reducido en standby, alto en eventos
- Servicio systemd con arranque automático

---

## [1.0.0] - 2026-05-09

### Inicial
- Pantalla OLED SSD1306 128×64 con I2C
- Detección de voz local (grupo y privada)
- Detección de SDS local
- Indicativo, nombre y provincia desde radioid.net
