from PIL import Image
from pathlib import Path

SOURCE_DIR = Path.cwd()
OUTPUT_DIR = SOURCE_DIR / "_icons_standardized"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_COLORS = {
    (0, 0, 0),
    (254, 254, 254),
    (255, 255, 255),
}

def is_standardized(img):
    img = img.convert("RGBA")

    for r, g, b, a in img.getdata():
        if (r, g, b) not in ALLOWED_COLORS:
            return False

        if a == 0 and (r, g, b) != (0, 0, 0):
            return False

    return True

def standardize_image(img):
    img = img.convert("RGBA")
    out = Image.new("RGBA", img.size)

    for y in range(img.height):
        for x in range(img.width):
            r, g, b, a = img.getpixel((x, y))

            if a == 0:
                out.putpixel((x, y), (0, 0, 0, 0))
            elif r >= 240 and g >= 240 and b >= 240:
                out.putpixel((x, y), (255, 255, 255, 255))
            elif r <= 128 and g <= 128 and b <= 128:
                out.putpixel((x, y), (0, 0, 0, a))
            else:
                brightness = (r + g + b) // 3
                new_alpha = max(0, min(255, 255 - brightness))
                out.putpixel((x, y), (0, 0, 0, new_alpha))

    return out

png_files = [
    p for p in SOURCE_DIR.rglob("*.png")
    if OUTPUT_DIR not in p.parents
]

print(f"Scanning: {SOURCE_DIR}")
print(f"Found {len(png_files)} PNG files")

converted_count = 0
already_ok_count = 0

for file in png_files:
    try:
        relative = file.relative_to(SOURCE_DIR)
        output_file = OUTPUT_DIR / relative
        output_file.parent.mkdir(parents=True, exist_ok=True)

        img = Image.open(file)

        if is_standardized(img):
            img.save(output_file)
            already_ok_count += 1
            print(f"OK: {relative}")
        else:
            converted = standardize_image(img)
            converted.save(output_file)
            converted_count += 1
            print(f"CONVERTED: {relative}")

    except Exception as e:
        print(f"ERROR: {file} -> {e}")

print()
print("Done")
print(f"Already OK: {already_ok_count}")
print(f"Converted: {converted_count}")
print(f"Output folder: {OUTPUT_DIR}")