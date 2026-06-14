from dataclasses import dataclass


@dataclass(frozen=True)
class ButtonRect:
    slot: int
    x: int
    y: int
    w: int
    h: int


def choose_grid(button_count: int, width: int, height: int) -> tuple[int, int, int]:
    """Choose grid (cols, rows) and gap for a given button count.

    This follows the explicit mapping provided for 1-32 buttons.
    Width/height are currently informational; the mapping assumes a
    320x240 landscape screen with a 36px title bar.
    """

    if button_count < 1 or button_count > 32:
        raise ValueError("button_count must be between 1 and 32")

    # Default gap is 8px for small layouts, 6px for denser layouts.
    gap = 8

    if button_count == 1:
        cols, rows = 1, 1
    elif button_count == 2:
        cols, rows = 2, 1
    elif button_count == 3:
        cols, rows = 3, 1
    elif button_count == 4:
        cols, rows = 2, 2
    elif button_count <= 6:
        cols, rows = 3, 2
    elif button_count <= 8:
        cols, rows = 4, 2
    elif button_count <= 9:
        cols, rows = 3, 3
    elif button_count <= 12:
        cols, rows = 4, 3
    elif button_count <= 16:
        cols, rows = 4, 4
        gap = 6
    elif button_count <= 20:
        cols, rows = 5, 4
        gap = 6
    elif button_count <= 24:
        cols, rows = 6, 4
        gap = 6
    elif button_count <= 25:
        cols, rows = 5, 5
        gap = 6
    elif button_count <= 30:
        cols, rows = 6, 5
        gap = 6
    else:  # 31-32
        cols, rows = 8, 4
        gap = 6

    return cols, rows, gap


def generate_layout(button_count: int, width: int, height: int) -> list[ButtonRect]:
    """Generate button rectangles for a 320x240 screen.

    Obeys these rules:
    - Title bar occupies Y=0..35; buttons start at Y>=36.
    - Button area is 320x204 starting at Y=36.
    - Padding is 8px; gap is 8px for smaller layouts and 6px for dense layouts.
    - Buttons never overlap each other or the title bar.
    - Slots are 1-based and filled row-major.
    """

    cols, rows, gap = choose_grid(button_count, width, height)

    # Clamp to the device's logical resolution; width/height are kept for
    # potential future multi-resolution support but we currently assume
    # 320x240 landscape.
    screen_width = width
    screen_height = height

    title_bar_height = 36
    button_area_y = title_bar_height
    button_area_h = screen_height - title_bar_height  # e.g., 204 for 240px tall

    padding = 8

    # Integer button sizes that fit entirely within the button area.
    button_w = (screen_width - padding * 2 - gap * (cols - 1)) // cols
    button_h = (button_area_h - padding * 2 - gap * (rows - 1)) // rows

    rects: list[ButtonRect] = []
    for index in range(button_count):
        row = index // cols
        col = index % cols

        x = padding + col * (button_w + gap)
        y = button_area_y + padding + row * (button_h + gap)

        # Ensure we never draw above the title bar.
        if y < title_bar_height:
            y = title_bar_height

        rects.append(ButtonRect(slot=index + 1, x=x, y=y, w=button_w, h=button_h))

    return rects
