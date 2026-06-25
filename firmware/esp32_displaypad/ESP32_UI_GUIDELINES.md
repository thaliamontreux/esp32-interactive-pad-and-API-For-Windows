# ESP32 DisplayPad UI Design Guidelines

These guidelines define how to design and implement screens for the ESP32 DisplayPad so that the UI is clean, consistent, and touch-friendly.

## General Layout

- **Safe area and margins**  
  - Keep a top header bar of **30 px** height reserved for the title and BACK button.  
  - Main content should start at **y ≈ 40** (e.g., `contentTop = 40`).  
  - Reserve at least **10 px bottom margin** (`SCREEN_HEIGHT - 10`) so nothing is drawn fully at the extreme bottom edge.

- **Text alignment and fonts**  
  - Use `setTextDatum(TC_DATUM)` for centered titles at the top of a screen.  
  - Use `setTextDatum(MC_DATUM)` for centered button labels.  
  - Use `setTextDatum(ML_DATUM)` or `TL_DATUM` for left-aligned labels.  
  - Use **text size 2** for screen titles and major headings.  
  - Use **text size 1** for body text, status lines, and list entries.

- **Colors**  
  - Backgrounds: dark (e.g., `COLOR_BG_DARK`, `COLOR_BG_MID`, or `COLOR_BLACK`).  
  - Primary text: `COLOR_WHITE` on dark backgrounds.  
  - Accents: use neon colors (e.g., `COLOR_NEON_CYAN`, `COLOR_NEON_PURPLE`, `COLOR_YELLOW`, `COLOR_GREEN`, `COLOR_RED`) to highlight important elements (buttons, selection, status).

## Header Bar and BACK Button

- **Header bar**  
  - Always draw a header bar using `drawSubscreenHeader(title)` for subscreens.  
  - Header height: **30 px** (fills `y = 0` to `y = 30`).  
  - Title: centered horizontally with `TC_DATUM` or `MC_DATUM` and text size 2.

- **BACK button**  
  - Place the BACK button in the top-right corner inside the header bar.  
  - Typical dimensions: width ≈ **50 px**, height ≈ **18 px**, with a small margin from edges.  
  - Hit area: treat any touch where `y < 30` and `x > SCREEN_WIDTH - 60` as a BACK press (see `handleBackButtonTouch`).  
  - Ensure no other interactive elements overlap this hit area.

## Main Control Panel Menu

- **Grid layout**  
  - Use a **2-column** grid for the main control panel menu.  
  - Content area: from `contentTop = 40` to `contentBottom = SCREEN_HEIGHT - 10`.  
  - Show **3 rows** of items at a time (`rowsVisible = 3`), for **6 items visible** total.  
  - Use a small horizontal gap between columns (e.g., `colGap = 6`).

- **Menu items**  
  - Use rounded rectangles for each menu item.  
  - Highlight the selected item with an accent background color and contrasting text.  
  - Keep text inside the button bounds; center labels horizontally and vertically.

- **Wide scrollbar (required)**  
  - Use a **finger-friendly wide scrollbar** on the right side of the menu.  
  - Standard width: `scrollBarWidth = 24`. Use this width consistently anywhere a vertical scrollbar is drawn.  
  - Track X position: `trackX = SCREEN_WIDTH - scrollBarWidth - 2`.  
  - Track height: spans from `contentTop` to `contentBottom`.  
  - Thumb height: proportional to visible rows, minimum ≈ 10 px.  
  - Thumb Y position: proportional to `menuScrollRow` relative to max offset.  
  - The scrollbar strip is also the drag area: touch and drag within `x >= trackX` and `x < SCREEN_WIDTH` while `y` within `contentTop..contentBottom` should update `menuScrollRow` and redraw.

- **Tap hit-testing for items**  
  - Only treat taps as menu item selections if they are inside the left content area (exclude scrollbar width).  
  - X range for content: from **5 px** left margin to `scrollRegionStartX = SCREEN_WIDTH - scrollBarWidth - 2`.

## Lists Without Visual Scrollbars

Some screens use scrolling lists without drawing a visual scrollbar (e.g., Wi‑Fi networks list, US timezone list). For these:

- **Row layout**  
  - Use consistent row height (e.g., 28–30 px).  
  - Start list rows below the header (e.g., `y ≈ 45–55`).  
  - Leave enough space below the last row for hints or instructions.

- **Scrolling interaction**  
  - Use **tap top area to scroll up** and **tap bottom area to scroll down**, or  
  - Use **tap above the list** to scroll up and **tap below the list** to scroll down.  
  - Always show a short hint such as `"Tap top/bottom to scroll"` in a stable location below the list.

- **Selection**  
  - Highlight the currently selected row with an accent background color and a border.  
  - Use left-aligned labels inside each row and keep text within the row rectangle.

## Buttons

- **General rules**  
  - Minimum height: **26–30 px** for easy touch.  
  - Use `fillRoundRect` + `drawRoundRect` for buttons, with a consistent corner radius (≈ 5–8).  
  - Center label text with `MC_DATUM` and ensure high contrast with the button background.

- **Bottom buttons**  
  - For primary actions at the bottom (e.g., CONNECT / EDIT):  
    - Place them at `y ≈ SCREEN_HEIGHT - 40` with height ≈ 26 px.  
    - Use symmetric horizontal margins and consistent gaps between buttons.

## Text and Truncation

- **Long values**  
  - Truncate long strings (SSID, UUID, etc.) to avoid overlapping other elements or running off-screen.  
  - Example: if SSID length is too long, keep the first N characters and append `...`.

- **Multi-line messages**  
  - For centered informational messages (e.g., "Connected!", error messages):  
    - Use text size 2 for the main message around `y ≈ 70–80`.  
    - Use text size 1 for secondary lines around `y ≈ 110–130`.  
    - Reserve space at `y ≈ 150–170` for a small instruction such as `"Touch to go back"`.

## Dialogs and Modals

- **Centered confirmation dialogs**  
  - Clear the screen and draw a prominent centered box.  
  - Use rounded rectangle background and border with accent colors.  
  - Title at top in larger font (size 2) and in an attention color (e.g., red for destructive actions).  
  - Message text in smaller font (size 1) below the title.  
  - YES/NO buttons inside the box at the bottom, large enough to hit easily.  
  - Tapping outside the box should cancel or be treated as NO if appropriate.

## Overlap and Clarity

- **No overlapping interactive elements**  
  - Ensure buttons and text do not occupy overlapping rectangles.  
  - Keep enough vertical spacing between lines (at least 12–16 px for text size 1).  
  - When adding new elements, verify their coordinates (x, y, width, height) do not conflict with:  
    - Header/back button region (top 30 px).  
    - Bottom buttons.  
    - Scrollbar strip on the right, if present.

- **Consistent patterns**  
  - Reuse existing layout patterns (header + body + bottom buttons, 2-column menus, lists with row highlights) instead of inventing new arrangements per screen.  
  - Prefer centered, concise messages with clear next steps (e.g., `"Touch to go back"`).

## Scrollbar Consistency Checklist

Whenever you add a new visual vertical scrollbar on any screen:

1. **Width**: set `scrollBarWidth = 24` (or equivalent constant).  
2. **Location**: place the scrollbar on the right edge with a 2 px gap from the edge.  
3. **Hit area**: ensure the scrollbar strip is thick enough and used for drag gestures.  
4. **Content exclusion**: reduce content width so no buttons or text are drawn under the scrollbar strip.  
5. **Visual style**: track in a mid-tone background, thumb in a bright accent color.

---

**Usage**: When designing any new ESP32 DisplayPad screen, follow these rules for:

- Margins, header, and BACK button behavior.  
- Scrollbar width and interaction.  
- Button sizes, positions, and visual style.  
- Text placement, truncation, and alignment.

Refer to this file before implementing a new layout to keep the UI consistent and avoid overlap or thin scrollbars.
