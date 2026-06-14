from PIL import Image
from pathlib import Path
from collections import Counter, defaultdict
import shutil
import csv

SOURCE_DIR = Path.cwd()
OUTPUT_DIR = SOURCE_DIR / "_png_categories"
REPORT_FILE = OUTPUT_DIR / "png_analysis_report.csv"

ALLOWED_RGB = {
    (0, 0, 0),
    (254, 254, 254),
    (255, 255, 255),
}

CATEGORY_TARGET_FORMAT = "01_target_format"
CATEGORY_WHITE_BACKGROUND = "02_white_background_icon"
CATEGORY_ALPHA_MASK_BLACK = "03_alpha_mask_black_icon"
CATEGORY_COLORED_OR_MIXED = "04_colored_or_mixed"
CATEGORY_NO_ALPHA = "05_no_alpha"
CATEGORY_ERRORS = "99_errors"

def safe_copy(src: Path, category: str):
    relative = src.relative_to(SOURCE_DIR)
    dest = OUTPUT_DIR / category / relative
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)

def analyze_image(path: Path):
    img = Image.open(path)
    rgba = img.convert("RGBA")

    rgba_counts = Counter(rgba.getdata())

    total_pixels = rgba.width * rgba.height
    unique_rgba = len(rgba_counts)
    unique_rgb = len(set((r, g, b) for r, g, b, a in rgba_counts.keys()))
    unique_alpha = len(set(a for r, g, b, a in rgba_counts.keys()))

    transparent = sum(c for (r, g, b, a), c in rgba_counts.items() if a == 0)
    semi_transparent = sum(c for (r, g, b, a), c in rgba_counts.items() if 0 < a < 255)
    opaque = sum(c for (r, g, b, a), c in rgba_counts.items() if a == 255)

    white = sum(c for (r, g, b, a), c in rgba_counts.items() if a > 0 and r >= 240 and g >= 240 and b >= 240)
    black = sum(c for (r, g, b, a), c in rgba_counts.items() if a > 0 and r <= 32 and g <= 32 and b <= 32)

    colored = sum(
        c for (r, g, b, a), c in rgba_counts.items()
        if a > 0
        and not (r >= 240 and g >= 240 and b >= 240)
        and not (r <= 32 and g <= 32 and b <= 32)
    )

    rgb_only_allowed = all(
        (r, g, b) in ALLOWED_RGB
        for r, g, b, a in rgba_counts.keys()
    )

    transparent_black_only = all(
        (a != 0) or ((r, g, b) == (0, 0, 0))
        for r, g, b, a in rgba_counts.keys()
    )

    has_alpha = transparent > 0 or semi_transparent > 0

    if rgb_only_allowed and transparent_black_only:
        category = CATEGORY_TARGET_FORMAT

    elif white > 0 and black > 0:
        category = CATEGORY_WHITE_BACKGROUND

    elif black > 0 and transparent > 0 and colored == 0:
        category = CATEGORY_ALPHA_MASK_BLACK

    elif not has_alpha:
        category = CATEGORY_NO_ALPHA

    else:
        category = CATEGORY_COLORED_OR_MIXED

    return {
        "file": str(path.relative_to(SOURCE_DIR)),
        "category": category,
        "format": img.format,
        "mode": img.mode,
        "width": rgba.width,
        "height": rgba.height,
        "total_pixels": total_pixels,
        "unique_rgba": unique_rgba,
        "unique_rgb": unique_rgb,
        "unique_alpha": unique_alpha,
        "transparent": transparent,
        "semi_transparent": semi_transparent,
        "opaque": opaque,
        "white_near_white": white,
        "black_near_black": black,
        "other_colored": colored,
        "has_alpha": has_alpha,
    }

def main():
    png_files = [
        p for p in SOURCE_DIR.rglob("*.png")
        if OUTPUT_DIR not in p.parents
    ]

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 70)
    print("PNG Directory Analyzer and Sorter")
    print("=" * 70)
    print(f"Scanning: {SOURCE_DIR}")
    print(f"Found PNG files: {len(png_files)}")
    print()

    rows = []
    counts = defaultdict(int)

    for index, file in enumerate(png_files, start=1):
        try:
            info = analyze_image(file)
            rows.append(info)
            counts[info["category"]] += 1
            safe_copy(file, info["category"])

            print(f"[{index}/{len(png_files)}] {info['category']}  ->  {info['file']}")

        except Exception as e:
            counts[CATEGORY_ERRORS] += 1
            safe_copy(file, CATEGORY_ERRORS)

            rows.append({
                "file": str(file.relative_to(SOURCE_DIR)),
                "category": CATEGORY_ERRORS,
                "error": str(e),
            })

            print(f"[{index}/{len(png_files)}] ERROR -> {file}: {e}")

    if rows:
        fieldnames = sorted(set().union(*(row.keys() for row in rows)))

        with open(REPORT_FILE, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    print()
    print("=" * 70)
    print("Summary")
    print("=" * 70)

    for category, count in sorted(counts.items()):
        print(f"{category}: {count}")

    print()
    print(f"Sorted output: {OUTPUT_DIR}")
    print(f"CSV report: {REPORT_FILE}")
    print("Done.")

if __name__ == "__main__":
    main()