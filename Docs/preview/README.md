# Vistas previas de pantalla

Renderizado de las pantallas de TETRA OLED Display **sin necesidad de hardware**.

`preview.py` ejecuta el código real de `tetra_oled.py` contra dispositivos OLED
simulados que graban lo que se mostraría, y genera un montaje PNG con todas las
pantallas (arranque, standby, voz de grupo, privada, red y SDS) para cada modelo.

## Uso

```bash
pip install pillow
python Docs/preview/preview.py
```

Genera tres archivos en esta carpeta:

| Archivo | Pantalla |
| --- | --- |
| `preview_ssd1306.png` | SSD1306 128×64 (monocromo) |
| `preview_sh1107.png`  | SH1107 128×128 (monocromo) |
| `preview_ssd1327.png` | SSD1327 128×128 (escala de grises) |

> SH1107 y SSD1327 comparten el mismo diseño de 128×128, por eso se ven igual.
> Las fuentes usan DejaVu Mono en Linux/Raspberry Pi y Consolas en Windows.
