from PIL import Image
from pathlib import Path
import re

SOURCE_DIR = Path.cwd()
OUTPUT_DIR = SOURCE_DIR / "_esp32_icon_masks"
HEADER_FILE = OUTPUT_DIR / "esp32_icons.h"

ALPHA_THRESHOLD = 1
WHITE_THRESHOLD = 240

def make_c_name(path: Path):
    name = path.stem.lower()
    name = re.sub(r"[^a-z0-9_]", "_", name)
    if name[0].isdigit():
        name = "_" + name
    return name

def is_visible_icon_pixel(r, g, b, a):
    if a == 0:
        return False

    if r >= WHITE_THRESHOLD and g >= WHITE_THRESHOLD and b >= WHITE_THRESHOLD:
        return False

    return True

def convert_to_1bit_mask(img):
    img = img.convert("RGBA")
    width, height = img.size

    bytes_per_row = (width + 7) // 8
    data = []

    for y in range(height):
        for byte_x in range(bytes_per_row):
            value = 0

            for bit in range(8):
                x = byte_x * 8 + bit

                if x < width:
                    r, g, b, a = img.getpixel((x, y))

                    if is_visible_icon_pixel(r, g, b, a):
                        value |= 1 << (7 - bit)

            data.append(value)

    return width, height, data

def main():
    png_files = [
        p for p in SOURCE_DIR.rglob("*.png")
        if "_esp32_icon_masks" not in p.parts
        and "_png_categories" not in p.parts
        and "_icons_standardized" not in p.parts
    ]

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    lines = []
    lines.append("#pragma once")
    lines.append("#include <stdint.h>")
    lines.append("")
    lines.append("typedef struct {")
    lines.append("  const char* name;")
    lines.append("  uint16_t width;")
    lines.append("  uint16_t height;")
    lines.append("  const uint8_t* data;")
    lines.append("} Esp32Icon;")
    lines.append("")

    icon_entries = []

    print(f"Scanning: {SOURCE_DIR}")
    print(f"Found PNG files: {len(png_files)}")
    print()

    for index, file in enumerate(png_files, start=1):
        img = Image.open(file)
        width, height, data = convert_to_1bit_mask(img)

        c_name = make_c_name(file.relative_to(SOURCE_DIR))
        array_name = f"icon_{c_name}_bits"

        lines.append(f"// {file.relative_to(SOURCE_DIR)}")
        lines.append(f"static const uint8_t {array_name}[] PROGMEM = {{")

        row = []
        for i, byte in enumerate(data):
            row.append(f"0x{byte:02X}")
            if len(row) == 16:
                lines.append("  " + ", ".join(row) + ",")
                row = []

        if row:
            lines.append("  " + ", ".join(row) + ",")

        lines.append("};")
        lines.append("")

        icon_entries.append((file.stem, width, height, array_name))

        print(f"[{index}/{len(png_files)}] Converted: {file.relative_to(SOURCE_DIR)}  {width}x{height}")

    lines.append("static const Esp32Icon ESP32_ICONS[] = {")
    for name, width, height, array_name in icon_entries:
        lines.append(f'  {{"{name}", {width}, {height}, {array_name}}},')
    lines.append("};")
    lines.append("")
    lines.append(f"static const uint16_t ESP32_ICON_COUNT = {len(icon_entries)};")
    lines.append("")

    with open(HEADER_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print()
    print("Done.")
    print(f"Output: {HEADER_FILE}")

if __name__ == "__main__":
    main()