#include "button_renderer.h"
#include "api_client.h"
#include "icon_cache.h"
#include "../../../esp32_icons.h"

#include <LittleFS.h>
#include <PNGdec.h>

#define FileSys LittleFS

// PNG decoder instance and file handle for icon rendering
static PNG png;
static fs::File pngfile;

// Icon placement, scaling, and background state for the current decode
static int16_t iconX = 0;
static int16_t iconY = 0;
static int16_t iconSrcW = 0;   // original PNG width
static int16_t iconSrcH = 0;   // original PNG height
static int16_t iconDrawW = 0;  // scaled width actually drawn
static int16_t iconDrawH = 0;  // scaled height actually drawn
// Background color for compositing PNG transparency; set per-button before decode
static uint16_t iconBgColor = COLOR_BG_MID;

// Icon analysis and rendering mode for PNG icons
enum IconRenderType {
    ICON_RENDER_FALLBACK_MASK = 0,
    ICON_RENDER_WHITE_BG_ICON,
    ICON_RENDER_ALPHA_MASK_ICON
};

static IconRenderType currentIconType = ICON_RENDER_FALLBACK_MASK;
static uint32_t iconTransparentCount = 0;
static uint32_t iconSemiTransparentCount = 0;
static uint32_t iconDarkCount = 0;
static uint32_t iconWhiteCount = 0;
static uint32_t iconOtherCount = 0;

// Icon foreground color; defaults to black and can be overridden per button later.
static uint16_t iconFgColor = COLOR_BLACK;

// Background color sampled from the PNG itself (for app icons). We treat
// pixels close to this sampled color as background and other pixels as the
// icon shape when rendering a white symbol over the cyberpunk button face.
static bool iconBgSampled = false;
static uint8_t iconBgSampleR = 0;
static uint8_t iconBgSampleG = 0;
static uint8_t iconBgSampleB = 0;

// PNGdec filesystem callbacks (adapted from TFT_eSPI LittleFS_PNG example)
void* pngOpen(const char* filename, int32_t* size) {
    Serial.print("[PNGdec] pngOpen filename='");
    Serial.print(filename);
    Serial.println("'");
    pngfile = FileSys.open(filename, "r");
    if (!pngfile) {
        Serial.println("[PNGdec] FileSys.open FAILED");
        *size = 0;
        return nullptr;
    }
    *size = pngfile.size();
    Serial.print("[PNGdec] file size=");
    Serial.println(*size);
    return &pngfile;
}

void pngClose(void* handle) {
    (void)handle;  // handle is not used; we close the global pngfile
    if (pngfile) {
        pngfile.close();
    }
}

int32_t pngRead(PNGFILE* page, uint8_t* buffer, int32_t length) {
    (void)page;  // unused
    if (!pngfile) return 0;
    return pngfile.read(buffer, length);
}

int32_t pngSeek(PNGFILE* page, int32_t position) {
    (void)page;  // unused
    if (!pngfile) return 0;
    return pngfile.seek(position);
}

// First-pass PNG callback: analyze pixels as RGBA to detect icon type and build statistics.
static int pngDrawAnalyze(PNGDRAW* pDraw) {
    uint8_t* p = pDraw->pPixels;
    int w = pDraw->iWidth;
    if (!p || w <= 0) {
        return 1;
    }

    if (pDraw->iPixelType == PNG_PIXEL_TRUECOLOR_ALPHA && pDraw->iBpp == 8) {
        for (int x = 0; x < w; ++x) {
            int idx = x * 4;
            uint8_t r = p[idx + 0];
            uint8_t g = p[idx + 1];
            uint8_t b = p[idx + 2];
            uint8_t a = p[idx + 3];

            if (a == 0) {
                iconTransparentCount++;
                continue;
            }

            if (a < 255) {
                iconSemiTransparentCount++;
            }

            if (r > 240 && g > 240 && b > 240) {
                iconWhiteCount++;
            } else if (r < 32 && g < 32 && b < 32) {
                iconDarkCount++;
            } else {
                iconOtherCount++;
            }

            // Use the first fully-opaque, non-white pixel as a background
            // sample candidate. For icons like Claud's, this will pick up
            // the flat colored background behind the white symbol.
            if (!iconBgSampled && a == 255) {
                iconBgSampleR = r;
                iconBgSampleG = g;
                iconBgSampleB = b;
                iconBgSampled = true;
            }
        }
    } else {
        // Fallback: treat any non-zero source pixel as a dark icon pixel.
        for (int x = 0; x < w; ++x) {
            iconDarkCount++;
        }
    }

    return 1;
}

// Second-pass PNG callback: render using the detected icon type and a clean mask.
static int pngDrawRender(PNGDRAW* pDraw) {
    static uint16_t dstLine[320];

    if (iconDrawW <= 0 || iconDrawH <= 0 || iconSrcW <= 0 || iconSrcH <= 0) {
        return 0;
    }

    int16_t outW = iconDrawW;
    if (outW > 320) {
        outW = 320;
    }

    uint8_t* src = pDraw->pPixels;
    int w = pDraw->iWidth;
    if (!src || w <= 0) {
        return 1;
    }

    for (int16_t x = 0; x < outW; ++x) {
        int32_t srcX = (int32_t)x * iconSrcW / iconDrawW;
        if (srcX < 0) srcX = 0;
        if (srcX >= w) srcX = w - 1;

        uint8_t r = 0, g = 0, b = 0, a = 255;
        if (pDraw->iPixelType == PNG_PIXEL_TRUECOLOR_ALPHA && pDraw->iBpp == 8) {
            int idx = srcX * 4;
            r = src[idx + 0];
            g = src[idx + 1];
            b = src[idx + 2];
            a = src[idx + 3];
        } else if (pDraw->iPixelType == PNG_PIXEL_TRUECOLOR && pDraw->iBpp == 8) {
            int idx = srcX * 3;
            r = src[idx + 0];
            g = src[idx + 1];
            b = src[idx + 2];
            a = 255;
        } else {
            // Other formats: treat as opaque dark pixel.
            r = g = b = 0;
            a = 255;
        }

        // Simple rule for application icons:
        // - White and light grey hues are treated as transparent and replaced
        //   by the button background color.
        // - All other colors are rendered directly from the PNG.
        // - Alpha is only used to discard fully (or nearly) transparent
        //   pixels; for non-white colors we ignore semi-transparency.
        uint16_t rgb565;
        if (a < 32) {
            // Fully transparent: show button background
            rgb565 = iconBgColor;
        } else {
            // Treat as white / light grey if ALL channels are high. This is
            // more robust for icons like Claude's where the burst is very
            // bright and near-neutral.
            bool isWhiteLike = (r >= 220 && g >= 220 && b >= 220);

            if (isWhiteLike) {
                rgb565 = iconBgColor;
            } else {
                rgb565 = display.getTFT()->color565(r, g, b);
            }
        }

        dstLine[x] = rgb565;
    }

    int16_t destY = iconY + (int32_t)pDraw->y * iconDrawH / iconSrcH;
    display.getTFT()->pushImage(iconX, destY, outW, 1, dstLine);

    return 1;  // continue decoding
}

static const Esp32Icon* findEsp32Icon(const String& id) {
    for (uint16_t i = 0; i < ESP32_ICON_COUNT; ++i) {
        if (id.equalsIgnoreCase(ESP32_ICONS[i].name)) {
            return &ESP32_ICONS[i];
        }
    }
    return nullptr;
}

static bool drawEsp32Icon(const Button& btn, uint16_t faceColor) {
    (void)faceColor;

    const Esp32Icon* icon = findEsp32Icon(btn.iconId);
    if (!icon) {
        Serial.print("[ButtonRenderer] No ESP32 icon for '");
        Serial.print(btn.iconId);
        Serial.println("'");
        return false;
    }

    int16_t innerX = btn.x + 2;
    // Move icon 1px closer to the top edge of the button face
    int16_t innerY = btn.y + 1;
    int16_t innerW = btn.w - 4;
    int16_t innerH = btn.h - 4;

    uint16_t srcW = icon->width;
    uint16_t srcH = icon->height;
    if (srcW == 0 || srcH == 0 || innerW <= 0 || innerH <= 0) {
        return false;
    }

    int32_t scaleW = (int32_t)innerW * 1000 / srcW;
    int32_t scaleH = (int32_t)innerH * 1000 / srcH;
    int32_t scale = scaleW < scaleH ? scaleW : scaleH;
    if (scale <= 0) {
        scale = 1;
    }
    if (scale > 1000) {
        scale = 1000;
    }

    iconDrawW = (int16_t)(srcW * scale / 1000);
    iconDrawH = (int16_t)(srcH * scale / 1000);
    if (iconDrawW <= 0 || iconDrawH <= 0) {
        return false;
    }

    iconX = innerX + (innerW - iconDrawW) / 2;
    iconY = innerY + (innerH - iconDrawH) / 2;

    TFT_eSPI* tft = display.getTFT();
    int bytesPerRow = (srcW + 7) / 8;

    for (int dy = 0; dy < iconDrawH; ++dy) {
        int srcY = (int32_t)dy * srcH / iconDrawH;
        int destY = iconY + dy;
        for (int dx = 0; dx < iconDrawW; ++dx) {
            int srcX = (int32_t)dx * srcW / iconDrawW;
            int byteIndex = srcY * bytesPerRow + (srcX >> 3);
            uint8_t byte = pgm_read_byte(&(icon->data[byteIndex]));
            bool visible = byte & (1 << (7 - (srcX & 7)));
            if (visible) {
                tft->drawPixel(iconX + dx, destY, iconFgColor);
            }
        }
    }

    return true;
}

ButtonRenderer buttonRenderer;

ButtonRenderer::ButtonRenderer()
    : activeButton(-1),
      pressStartTime(0),
      longPressStartTime(0),
      longPressActive(false),
      use24hFormat(false),
      showAmPm(true),
      timezoneOffsetMinutes(0),
      currentPage(1),
      totalPages(1),
      buttonsPerPage(0) {}

bool ButtonRenderer::begin() {
    // Clear to a dark industrial background when the renderer initializes
    display.fillScreen(COLOR_BG_DARK);
    return true;
}

static uint16_t hexToRgb565(const String& hex, uint16_t fallback) {
    // Expect formats like "#RRGGBB" or "RRGGBB"; return fallback on parse error.
    if (hex.length() == 0) {
        return fallback;
    }

    int start = 0;
    if (hex.charAt(0) == '#') {
        if (hex.length() < 7) {
            return fallback;
        }
        start = 1;
    } else if (hex.length() < 6) {
        return fallback;
    }

    auto parse2 = [&](int idx) -> int {
        char buf[3] = {0, 0, 0};
        buf[0] = hex.charAt(start + idx);
        buf[1] = hex.charAt(start + idx + 1);
        char* endptr = nullptr;
        long v = strtol(buf, &endptr, 16);
        if (endptr == buf) return -1;
        if (v < 0) v = 0;
        if (v > 255) v = 255;
        return (int)v;
    };

    int r = parse2(0);
    int g = parse2(2);
    int b = parse2(4);
    if (r < 0 || g < 0 || b < 0) {
        return fallback;
    }

    // Convert 8-bit RGB to 16-bit RGB565
    uint16_t r5 = (uint16_t)(r >> 3);
    uint16_t g6 = (uint16_t)(g >> 2);
    uint16_t b5 = (uint16_t)(b >> 3);
    return (r5 << 11) | (g6 << 5) | b5;
}

void ButtonRenderer::loadConfig(const PadConfig& config) {
    buttons.clear();

    // Capture time configuration for taskbar
    use24hFormat = config.use24h;
    showAmPm = config.showAmPm;
    timezoneOffsetMinutes = config.timezoneOffsetMinutes;

    // Track whether this pad is currently in Task Keypad mode. In this
    // mode we will only render buttons whose associated applications are
    // reported as running by the API via the task_app_state WebSocket
    // messages.
    isTaskKeypadMode = (config.mode == "task_keypad");

    // Paging info
    currentPage = 1;
    totalPages = config.pageCount > 0 ? config.pageCount : 1;
    buttonsPerPage = config.buttonCount > 0 ? config.buttonCount : (int)config.buttons.size();

    for (const auto& bc : config.buttons) {
        Button btn;
        btn.page = bc.page;
        btn.slot = bc.slot;
        btn.x = bc.x;
        btn.y = bc.y;
        btn.w = bc.w;
        // Make the rendered button slightly taller than the layout rect
        btn.h = bc.h + 5;
        btn.label = bc.label;
        btn.iconId = bc.iconId;
        btn.actionId = bc.actionId;
        btn.pressed = false;

        // Per-button colors from config with sensible defaults:
        // BG defaults to COLOR_BUTTON_BG, text defaults to COLOR_BUTTON_TEXT.
        btn.bgColor = hexToRgb565(bc.bgColorHex, COLOR_BUTTON_BG);
        btn.textColor = hexToRgb565(bc.textColorHex, COLOR_BUTTON_TEXT);
        btn.iconColor = hexToRgb565(bc.iconColorHex, COLOR_BLACK);

        btn.showText = bc.showText;

        // Application icon metadata for Launch Application buttons
        btn.applicationId = bc.applicationId;
        btn.hasApplicationIcon = bc.hasApplicationIcon;
        btn.applicationIconKey = "";
        if (btn.hasApplicationIcon && btn.applicationId > 0) {
            // Build a stable cache key. If the server provides a
            // application_icon_version (typically a hash or timestamp),
            // include it so that when the icon changes we fetch a fresh copy
            // under a new filename in LittleFS.
            if (bc.applicationIconVersion.length() > 0) {
                btn.applicationIconKey = String("app_") + String(btn.applicationId) + "_" + bc.applicationIconVersion;
            } else {
                btn.applicationIconKey = String("app_") + String(btn.applicationId);
            }
        }

        // Icon color is handled in drawButton via iconFgColor; we keep
        // per-button icon color in the same hex field and convert there.

        // Debug: log how this button is configured from the API.
        Serial.print("[ButtonRenderer] Config button page=");
        Serial.print(btn.page);
        Serial.print(" slot=");
        Serial.print(btn.slot);
        Serial.print(" label='");
        Serial.print(btn.label);
        Serial.print("' iconId='");
        Serial.print(btn.iconId);
        Serial.print("' appId=");
        Serial.print(btn.applicationId);
        Serial.print(" hasAppIcon=");
        Serial.print(btn.hasApplicationIcon ? "true" : "false");
        Serial.print(" appIconKey='");
        Serial.print(btn.applicationIconKey);
        Serial.println("'");

        // By default, Task Keypad buttons are considered "not running" until
        // the API sends a task_app_state update. Macro Keypad buttons ignore
        // this flag and are always rendered.
        btn.taskAppRunning = false;

        buttons.push_back(btn);
    }
}

void ButtonRenderer::clearButtons() {
    buttons.clear();
}

void ButtonRenderer::clearTaskAppState() {
    for (auto &btn : buttons) {
        btn.taskAppRunning = false;
    }
}

void ButtonRenderer::setTaskAppRunning(int slot, bool running) {
    for (auto &btn : buttons) {
        if (btn.slot == slot) {
            btn.taskAppRunning = running;
        }
    }
}

void ButtonRenderer::forceRefresh() {
    // Redraw industrial-style background before everything
    display.fillScreen(COLOR_BG_DARK);
    drawTaskbar();
    drawPageIndicators();
    if (isTaskKeypadMode) {
        // In Task Keypad mode, render running applications packed from
        // left-to-right using the first N layout slots on the current page,
        // so there are no visual gaps when some apps are not running.
        // The underlying button configuration (slots, actions) is preserved;
        // this only affects where the icons are drawn.

        // Build an ordered list of layout slots (positions) for this page.
        std::vector<const Button*> layoutSlots;
        layoutSlots.reserve(buttons.size());
        for (const auto &btn : buttons) {
            if (btn.page == currentPage) {
                layoutSlots.push_back(&btn);
            }
        }

        // Build the list of buttons whose applications are currently running
        // on this page.
        std::vector<const Button*> runningButtons;
        runningButtons.reserve(layoutSlots.size());
        for (const auto &btn : buttons) {
            if (btn.page == currentPage && btn.taskAppRunning) {
                runningButtons.push_back(&btn);
            }
        }

        if (!layoutSlots.empty() && !runningButtons.empty()) {
            // Sort layout slots by their configured slot number so that we
            // fill positions from left-to-right/top-to-bottom as defined by
            // the server layout.
            std::sort(
                layoutSlots.begin(),
                layoutSlots.end(),
                [](const Button* a, const Button* b) {
                    return a->slot < b->slot;
                }
            );

            size_t count = runningButtons.size();
            if (count > layoutSlots.size()) {
                count = layoutSlots.size();
            }

            for (size_t i = 0; i < count; ++i) {
                const Button* content = runningButtons[i];
                const Button* layout = layoutSlots[i];

                // Draw a temporary button that uses the visual position and
                // size from the i-th layout slot, but all other properties
                // (label, icon, action, etc.) from the running button.
                Button drawBtn = *content;
                drawBtn.x = layout->x;
                drawBtn.y = layout->y;
                drawBtn.w = layout->w;
                drawBtn.h = layout->h;

                drawButton(drawBtn, content->pressed);
            }
        }
    } else {
        for (size_t i = 0; i < buttons.size(); i++) {
            if (buttons[i].page == currentPage) {
                renderButton(i);
            }
        }
    }
}

void ButtonRenderer::drawTaskbar() {
    // 16px height taskbar at top with cyberpunk styling
    const int taskbarHeight = 16;
    const int iconSize = 14;  // 14px config icon

    // Taskbar background: dark panel with a subtle top/bottom stripe
    display.fillRect(0, 0, SCREEN_WIDTH, taskbarHeight, COLOR_BG_DARKER);
    display.drawLine(0, 0, SCREEN_WIDTH, 0, COLOR_NEON_PURPLE);
    display.drawLine(0, taskbarHeight - 1, SCREEN_WIDTH, taskbarHeight - 1, COLOR_NEON_CYAN);

    // Draw time on the left (small text, 12/24-hour per config). NTP is
    // configured with UTC (offset 0), so time() returns UTC. Apply the
    // server's timezone offset from the pad config so the ESP32 clock matches
    // the DisplayPad API host.
    time_t now = time(nullptr);
    if (now > 0) {
        time_t adjusted = now + (time_t)timezoneOffsetMinutes * 60;
        struct tm* timeinfo = gmtime(&adjusted);
        int hour24 = timeinfo->tm_hour;
        int minute = timeinfo->tm_min;

        char timeStr[12];

        if (use24hFormat) {
            // 24-hour format: HH:MM
            sprintf(timeStr, "%02d:%02d", hour24, minute);
        } else {
            // 12-hour format, optional AM/PM
            int hour = hour24;
            bool isPM = false;
            if (hour == 0) {
                hour = 12;           // 00:xx -> 12:xx AM
            } else if (hour == 12) {
                isPM = true;         // 12:xx -> 12:xx PM
            } else if (hour > 12) {
                hour -= 12;          // 13-23 -> 1-11 PM
                isPM = true;
            }

            if (showAmPm) {
                sprintf(timeStr, "%d:%02d %s", hour, minute, isPM ? "PM" : "AM");
            } else {
                sprintf(timeStr, "%d:%02d", hour, minute);
            }
        }

        display.setTextSize(1);
        display.setTextDatum(ML_DATUM);  // middle-left
        display.setTextColor(COLOR_NEON_CYAN, COLOR_BG_DARKER);
        display.drawString(timeStr, 2, taskbarHeight / 2);
    }

    // Host name in the center (API host from storage)
    extern SecureStorage storage;
    String host = storage.getApiHost();
    if (host.length() > 0) {
        display.setTextSize(1);
        display.setTextDatum(MC_DATUM);
        display.setTextColor(COLOR_WHITE, COLOR_DARK_GRAY);

        // Constrain host name width so it doesn't collide with time or icon
        int leftReserved = 40;   // space for time text
        int rightReserved = 24;  // space for config icon
        int maxHostWidth = SCREEN_WIDTH - leftReserved - rightReserved - 4;
        while (display.textWidth(host) > maxHostWidth && host.length() > 0) {
            host.remove(host.length() - 1);
        }

        display.drawString(host, SCREEN_WIDTH / 2, taskbarHeight / 2);
    }

    // Draw config gear icon at right side (14x14 area)
    int iconRight = SCREEN_WIDTH - 2;
    int iconLeft = iconRight - iconSize + 1;
    int iconTop = 1;
    int iconBottom = iconTop + iconSize - 1;
    int cx = (iconLeft + iconRight) / 2;
    int cy = (iconTop + iconBottom) / 2;

    int radius = iconSize / 2 - 1;  // keep inside 14px box
    // Neon gear "orb"
    display.fillCircle(cx, cy, radius - 2, COLOR_NEON_PURPLE);
    display.drawCircle(cx, cy, radius, COLOR_NEON_CYAN);
}

void ButtonRenderer::drawPageIndicators() {
    if (totalPages <= 1) {
        return;  // nothing to show
    }

    const int taskbarHeight = 16;
    const int indicatorSize = 18;
    const int radius = indicatorSize / 2;
    const int centerY = taskbarHeight + radius + 1;  // just below the top bar

    int pagesToShow = totalPages;
    if (pagesToShow > 4) {
        pagesToShow = 4;  // currently support up to 4 visual indicators
    }

    int totalWidth = pagesToShow * indicatorSize + (pagesToShow - 1) * 6;
    int startX = (SCREEN_WIDTH - totalWidth) / 2 + radius;

    for (int i = 0; i < pagesToShow; ++i) {
        int page = i + 1;
        int cx = startX + i * (indicatorSize + 6);

        bool active = (page == currentPage);
        uint16_t fill = active ? COLOR_NEON_CYAN : COLOR_BG_DARKER;
        uint16_t border = active ? COLOR_NEON_YELLOW : COLOR_NEON_PURPLE;
        uint16_t text = active ? COLOR_BG_DARKER : COLOR_NEON_CYAN;

        display.fillCircle(cx, centerY, radius, fill);
        display.drawCircle(cx, centerY, radius, border);

        // Draw page number in the center
        display.setTextSize(1);
        display.setTextDatum(MC_DATUM);
        display.setTextColor(text, fill);
        display.drawCentreString(String(page), cx, centerY);
    }
}

bool ButtonRenderer::checkTaskbarTouch(int x, int y) {
    // Hit-test for config icon in 16px-high taskbar at top
    const int taskbarHeight = 16;
    const int iconSize = 14;

    int iconRight = SCREEN_WIDTH - 2;
    int iconLeft = iconRight - iconSize + 1;
    int iconTop = 1;
    int iconBottom = iconTop + iconSize - 1;

    if (y >= iconTop && y <= iconBottom && x >= iconLeft && x <= iconRight) {
        // Config gear area clicked
        return true;
    }

    return false;
}

void ButtonRenderer::render() {
    // Only clear and draw on first render or when buttons change
    static bool firstRender = true;
    if (firstRender) {
        display.fillScreen(COLOR_BG_DARK);
        drawTaskbar();
        drawPageIndicators();
        firstRender = false;
    }

    if (isTaskKeypadMode) {
        // In Task Keypad mode, render running applications packed from
        // left-to-right using the first N layout slots on the current page,
        // so there are no visual gaps when some apps are not running.
        // The underlying button configuration (slots, actions) is preserved;
        // this only affects where the icons are drawn.

        // Build an ordered list of layout slots (positions) for this page.
        std::vector<const Button*> layoutSlots;
        layoutSlots.reserve(buttons.size());
        for (const auto &btn : buttons) {
            if (btn.page == currentPage) {
                layoutSlots.push_back(&btn);
            }
        }

        // Build the list of buttons whose applications are currently running
        // on this page.
        std::vector<const Button*> runningButtons;
        runningButtons.reserve(layoutSlots.size());
        for (const auto &btn : buttons) {
            if (btn.page == currentPage && btn.taskAppRunning) {
                runningButtons.push_back(&btn);
            }
        }

        if (!layoutSlots.empty() && !runningButtons.empty()) {
            // Sort layout slots by their configured slot number so that we
            // fill positions from left-to-right/top-to-bottom as defined by
            // the server layout.
            std::sort(
                layoutSlots.begin(),
                layoutSlots.end(),
                [](const Button* a, const Button* b) {
                    return a->slot < b->slot;
                }
            );

            size_t count = runningButtons.size();
            if (count > layoutSlots.size()) {
                count = layoutSlots.size();
            }

            for (size_t i = 0; i < count; ++i) {
                const Button* content = runningButtons[i];
                const Button* layout = layoutSlots[i];

                // Draw a temporary button that uses the visual position and
                // size from the i-th layout slot, but all other properties
                // (label, icon, action, etc.) from the running button.
                Button drawBtn = *content;
                drawBtn.x = layout->x;
                drawBtn.y = layout->y;
                drawBtn.w = layout->w;
                drawBtn.h = layout->h;

                drawButton(drawBtn, content->pressed);
            }
        }
    } else {
        for (size_t i = 0; i < buttons.size(); i++) {
            if (buttons[i].page == currentPage) {
                renderButton(i);
            }
        }
    }

    // Redraw taskbar and page indicators (to update time and highlight)
    drawTaskbar();
    drawPageIndicators();
}

void ButtonRenderer::drawResetButton() {
    Serial.println("[ButtonRenderer] Drawing reset button");

    // Draw at bottom of screen
    int btnHeight = 30;
    int btnY = SCREEN_HEIGHT - btnHeight - 5;
    int btnX = 5;
    int btnW = SCREEN_WIDTH - 10;

    Serial.println("[ButtonRenderer] Reset button at y=" + String(btnY));

    display.fillRoundRect(btnX, btnY, btnW, btnHeight, 5, COLOR_DARK_GRAY);
    display.drawRoundRect(btnX, btnY, btnW, btnHeight, 5, COLOR_RED);

    display.setTextSize(1);
    display.setTextDatum(MC_DATUM);
    display.setTextColor(COLOR_RED, COLOR_DARK_GRAY);
    display.drawCentreString("[ Reset Pairing ]", SCREEN_WIDTH / 2, btnY + btnHeight / 2);
}

void ButtonRenderer::renderButton(int index) {
    if (index >= 0 && index < (int)buttons.size()) {
        renderButton(buttons[index]);
    }
}

void ButtonRenderer::renderButton(const Button& btn) {
    drawButton(btn, btn.pressed);
}

void ButtonRenderer::drawButton(const Button& btn, bool highlight) {
    uint16_t baseColor = highlight ? COLOR_NEON_YELLOW : btn.bgColor;
    uint16_t edgeColor = highlight ? COLOR_NEON_CYAN : COLOR_NEON_PURPLE;
    // Use the same base button background color for the inner face so any
    // transparent pixels in the icon (which use faceColor) blend perfectly
    // with the button and do not appear as a darker box.
    uint16_t faceColor = highlight ? COLOR_NEON_CYAN : btn.bgColor;

    // Simple drop shadow (offset down-right)
    int r = 8;
    int shadowOffset = 2;
    display.fillRoundRect(btn.x + shadowOffset, btn.y + shadowOffset,
                          btn.w, btn.h, r, COLOR_BG_DARKER);

    // Button base
    display.fillRoundRect(btn.x, btn.y, btn.w, btn.h, r, baseColor);

    // Inner face to simulate 3D inset
    display.fillRoundRect(btn.x + 2, btn.y + 2, btn.w - 4, btn.h - 4,
                          r - 2, faceColor);

    // Bright top/left edge, darker bottom/right edge for 3D effect
    display.drawRoundRect(btn.x, btn.y, btn.w, btn.h, r, edgeColor);

    bool iconDrawn = false;

    // If this button has an associated application PNG icon, prefer that
    // over the built-in monochrome ESP32 icon set.
    if (btn.hasApplicationIcon && btn.applicationId > 0) {
        // Determine the local cache key for this application's PNG icon.
        // applicationIconKey may include a version/hash suffix so that
        // updated icons are re-fetched rather than reusing stale files.
        String appIconId = btn.applicationIconKey.length() > 0
            ? btn.applicationIconKey
            : String("app_") + String(btn.applicationId);

        Serial.print("[ButtonRenderer] drawButton page=");
        Serial.print(btn.page);
        Serial.print(" slot=");
        Serial.print(btn.slot);
        Serial.print(" appId=");
        Serial.print(btn.applicationId);
        Serial.print(" hasAppIcon=");
        Serial.print(btn.hasApplicationIcon ? "true" : "false");
        Serial.print(" appIconId='");
        Serial.print(appIconId);
        Serial.println("'");

        if (iconCache.ensureIcon(appIconId)) {
            String path = iconCache.getIconPath(appIconId);
            Serial.println("[ButtonRenderer] Using app icon from '" + path + "'");

            // Compute icon placement within the inner face, similar to
            // drawEsp32Icon but using the PNG's native dimensions.
            int16_t innerX = btn.x + 2;
            int16_t innerY = btn.y + 1;
            int16_t innerW = btn.w - 4;
            int16_t innerH = btn.h - 4;
            if (innerW > 0 && innerH > 0) {
                // Decode twice: first pass to detect icon type, second to render.
                iconBgColor = faceColor;
                iconFgColor = COLOR_BLACK;

                // Reset sampled background color for this icon
                iconBgSampled = false;

                bool refreshedOnce = false;

            retry_png_open:
                // Open PNG and read header to get width/height.
                // PNGdec::open returns PNG_SUCCESS (0) on success, not a
                // boolean, so we must compare explicitly.
                int16_t analyzeOpen = png.open(path.c_str(), pngOpen, pngClose, pngRead, pngSeek, pngDrawAnalyze);
                if (analyzeOpen == PNG_SUCCESS) {
                    Serial.println("[ButtonRenderer] PNG open OK for app icon");
                    iconSrcW = png.getWidth();
                    iconSrcH = png.getHeight();
                    if (iconSrcW > 0 && iconSrcH > 0) {
                        // Reset statistics
                        iconTransparentCount = 0;
                        iconSemiTransparentCount = 0;
                        iconDarkCount = 0;
                        iconWhiteCount = 0;
                        iconOtherCount = 0;

                        // Analyze pass using pngDrawAnalyze callback
                        png.decode(nullptr, 0);

                        // Choose render type based on statistics
                        if (iconTransparentCount > 0 || iconSemiTransparentCount > 0) {
                            currentIconType = ICON_RENDER_ALPHA_MASK_ICON;
                        } else if (iconWhiteCount > iconDarkCount) {
                            currentIconType = ICON_RENDER_WHITE_BG_ICON;
                        } else {
                            currentIconType = ICON_RENDER_FALLBACK_MASK;
                        }

                        // Compute scaled draw size preserving aspect ratio
                        int32_t scaleW = (int32_t)innerW * 1000 / iconSrcW;
                        int32_t scaleH = (int32_t)innerH * 1000 / iconSrcH;
                        int32_t scale = scaleW < scaleH ? scaleW : scaleH;
                        if (scale <= 0) scale = 1;
                        if (scale > 1000) scale = 1000;
                        iconDrawW = (int16_t)(iconSrcW * scale / 1000);
                        iconDrawH = (int16_t)(iconSrcH * scale / 1000);

                        if (iconDrawW > 0 && iconDrawH > 0) {
                            iconX = innerX + (innerW - iconDrawW) / 2;
                            iconY = innerY + (innerH - iconDrawH) / 2;

                            // Re-open and render with the selected mode
                            png.close();
                            int16_t renderOpen = png.open(path.c_str(), pngOpen, pngClose, pngRead, pngSeek, pngDrawRender);
                            if (renderOpen == PNG_SUCCESS) {
                                Serial.println("[ButtonRenderer] Rendering PNG app icon...");
                                png.decode(nullptr, 0);
                                png.close();
                                iconDrawn = true;
                                Serial.println("[ButtonRenderer] App icon render complete");
                            } else {
                                Serial.print("[ButtonRenderer] PNG open (render) failed rc=");
                                Serial.println(renderOpen);
                            }
                        } else {
                            png.close();
                        }
                    } else {
                        png.close();
                    }
                } else {
                    Serial.print("[ButtonRenderer] PNG open (analyze) failed rc=");
                    Serial.println(analyzeOpen);
                    Serial.println("[ButtonRenderer] PNG open FAILED for app icon, attempting refresh...");
                    // If we have not yet refreshed this icon, delete the local
                    // file and re-download it once to recover from a corrupt
                    // cache entry.
                    if (!refreshedOnce) {
                        refreshedOnce = true;
                        if (pngfile) {
                            pngfile.close();
                        }
                        if (FileSys.exists(path)) {
                            FileSys.remove(path);
                        }
                        if (iconCache.ensureIcon(appIconId)) {
                            path = iconCache.getIconPath(appIconId);
                            Serial.println("[ButtonRenderer] Refreshed app icon file, retrying PNG open");
                            goto retry_png_open;
                        }
                    } else {
                        // We already refreshed once and still cannot open the
                        // PNG. Dump the first few bytes so we can see whether
                        // this is actually a PNG file or some error payload.
                        if (FileSys.exists(path)) {
                            fs::File debugFile = FileSys.open(path, "r");
                            if (debugFile) {
                                uint8_t header[16];
                                int n = debugFile.read(header, sizeof(header));
                                debugFile.close();
                                Serial.print("[ButtonRenderer] PNG header bytes (");
                                Serial.print(n);
                                Serial.print("): ");
                                for (int i = 0; i < n; ++i) {
                                    if (i > 0) Serial.print(" ");
                                    if (header[i] < 16) Serial.print("0");
                                    Serial.print(String(header[i], HEX));
                                }
                                Serial.println();
                            }
                        }
                    }
                    // Final failure path: give up on this app icon and fall
                    // back to the monochrome icon renderer.
                }
            }
        }
        else {
            Serial.println("[ButtonRenderer] iconCache.ensureIcon FAILED for appIconId='" + appIconId + "'");
        }
    }

    // Fallback: use the built-in monochrome ESP32 icon set if we either
    // do not have an application icon or rendering the PNG failed.
    if (!iconDrawn) {
        String iconId = btn.iconId;
        if (iconId.length() > 0) {
            uint16_t iconColor = btn.iconColor;
            iconFgColor = iconColor;
            iconDrawn = drawEsp32Icon(btn, faceColor);
        }
    }

    // Draw label (centered; slightly lower if icon present), honouring
    // per-button showText flag and per-page button-count thresholds.
    if (btn.showText) {
        int perPage = buttonsPerPage > 0 ? buttonsPerPage : (int)buttons.size();
        int limitChars = 16;
        if (perPage >= 22) {
            limitChars = 0;
        } else if (perPage >= 16) {
            limitChars = 8;
        } else if (perPage >= 12) {
            limitChars = 12;
        } else if (perPage >= 8) {
            limitChars = 16;
        }

        if (limitChars > 0) {
            display.setTextSize(1);
            // Bottom-center anchor so the text stays fully inside the button
            display.setTextDatum(BC_DATUM);
            uint16_t textColor = highlight ? COLOR_BLACK : btn.textColor;
            // Use the button face color as the text background so the label
            // integrates cleanly with the button surface.
            display.setTextColor(textColor, faceColor);

            String label = btn.label;
            if (label.length() > limitChars) {
                label = label.substring(0, limitChars);
            }

            int maxWidth = btn.w - 10;
            while (display.textWidth(label) > maxWidth && label.length() > 0) {
                label = label.substring(0, label.length() - 1);
            }

            // Place text slightly higher so it sits fully inside the button,
            // visually aligned with the bottom edge of the rounded rect
            int16_t labelY = btn.y + btn.h - 10;
            display.drawCentreString(label, btn.x + btn.w / 2, labelY);
        }
    }
}

int ButtonRenderer::checkTouch(int x, int y) {
    // In Task Keypad mode, hit-testing must mirror the packed layout logic
    // used in render()/forceRefresh so that the visual button positions match
    // the actions that are triggered. Only buttons whose applications are
    // currently running (taskAppRunning == true) should be clickable.
    if (isTaskKeypadMode) {
        // Build ordered layout slots for this page.
        std::vector<const Button*> layoutSlots;
        layoutSlots.reserve(buttons.size());
        for (const auto &btn : buttons) {
            if (btn.page == currentPage) {
                layoutSlots.push_back(&btn);
            }
        }

        // Build running buttons for this page.
        std::vector<const Button*> runningButtons;
        runningButtons.reserve(layoutSlots.size());
        for (const auto &btn : buttons) {
            if (btn.page == currentPage && btn.taskAppRunning) {
                runningButtons.push_back(&btn);
            }
        }

        if (!layoutSlots.empty() && !runningButtons.empty()) {
            std::sort(
                layoutSlots.begin(),
                layoutSlots.end(),
                [](const Button* a, const Button* b) {
                    return a->slot < b->slot;
                }
            );

            size_t count = runningButtons.size();
            if (count > layoutSlots.size()) {
                count = layoutSlots.size();
            }

            for (size_t i = 0; i < count; ++i) {
                const Button* content = runningButtons[i];
                const Button* layout = layoutSlots[i];

                Button hitBtn = *content;
                hitBtn.x = layout->x;
                hitBtn.y = layout->y;
                hitBtn.w = layout->w;
                hitBtn.h = layout->h;

                if (x >= hitBtn.x && x < hitBtn.x + hitBtn.w &&
                    y >= hitBtn.y && y < hitBtn.y + hitBtn.h) {
                    // Map back to the index in the buttons vector.
                    int index = static_cast<int>(content - &buttons[0]);
                    if (index >= 0 && index < (int)buttons.size()) {
                        return index;
                    }
                }
            }
        }
    } else {
        // Macro keypad mode: simple rectangular hit-test against configured
        // button positions.
        for (size_t i = 0; i < buttons.size(); i++) {
            const Button& btn = buttons[i];
            if (btn.page == currentPage &&
                x >= btn.x && x < btn.x + btn.w &&
                y >= btn.y && y < btn.y + btn.h) {
                return i;
            }
        }
    }

    // Check Reset Pairing button (returns special index -2)
    int btnHeight = 30;
    int btnY = SCREEN_HEIGHT - btnHeight - 5;
    if (x >= 5 && x < SCREEN_WIDTH - 5 && y >= btnY && y < btnY + btnHeight) {
        return -2;  // Special code for Reset Pairing
    }

    return -1;
}

void ButtonRenderer::handleTouch(int x, int y) {
    // Check page indicators first (below the taskbar)
    int newPage = checkPageIndicatorTouch(x, y);
    if (newPage > 0 && newPage <= totalPages && newPage != currentPage) {
        currentPage = newPage;
        forceRefresh();
        return;
    }

    int index = checkTouch(x, y);
    if (index >= 0) {
        pressButton(index);
    } else if (index == -2) {
        // Reset Pairing button pressed - show confirmation
        handleResetPairing();
    }
}

void ButtonRenderer::handleResetPairing() {
    // Show confirmation screen
    display.clear();
    display.setTextSize(2);
    display.setTextDatum(TC_DATUM);
    display.setTextColor(COLOR_RED, COLOR_BLACK);
    display.drawCentreString("Reset Pairing?", SCREEN_WIDTH/2, 40);

    display.setTextSize(1);
    display.setTextColor(COLOR_WHITE, COLOR_BLACK);
    display.drawCentreString("This will unpair the device", SCREEN_WIDTH/2, 80);
    display.drawCentreString("and require re-pairing.", SCREEN_WIDTH/2, 95);

    // Draw Yes button
    display.fillRoundRect(30, 130, 80, 40, 8, COLOR_RED);
    display.drawRoundRect(30, 130, 80, 40, 8, COLOR_WHITE);
    display.setTextColor(COLOR_WHITE, COLOR_RED);
    display.setTextSize(2);
    display.drawCentreString("YES", 70, 150);

    // Draw No button
    display.fillRoundRect(130, 130, 80, 40, 8, COLOR_GREEN);
    display.drawRoundRect(130, 130, 80, 40, 8, COLOR_WHITE);
    display.setTextColor(COLOR_BLACK, COLOR_GREEN);
    display.drawCentreString("NO", 170, 150);

    // Wait for user choice
    while (true) {
        int tx, ty;
        if (display.getTouch(&tx, &ty)) {
            // Check Yes button
            if (tx >= 30 && tx < 110 && ty >= 130 && ty < 170) {
                // Reset pairing confirmed
                extern SecureStorage storage;
                extern bool configLoaded;

                storage.setPaired(false);
                storage.setApiUUID("");
                storage.setApiHost("");
                storage.setApiIP("");
                storage.setDeviceToken("");
                configLoaded = false;

                display.clear();
                display.setTextSize(2);
                display.setTextColor(COLOR_GREEN, COLOR_BLACK);
                display.drawCentreString("Pairing Reset!", SCREEN_WIDTH/2, 100);
                delay(2000);

                // Reboot to enter pairing mode
                ESP.restart();
                return;
            }
            // Check No button
            else if (tx >= 130 && tx < 210 && ty >= 130 && ty < 170) {
                // Cancelled - redraw buttons
                render();
                return;
            }
        }
        delay(50);
    }
}

void ButtonRenderer::pressButton(int index) {
    if (index < 0 || index >= (int)buttons.size()) return;

    activeButton = index;
    buttons[index].pressed = true;
    pressStartTime = millis();

    // Visual feedback: in macro keypad mode we can redraw just this button.
    // In Task Keypad mode, buttons are packed into different visual slots, so
    // we ask the main loop to perform a full packed re-render instead of
    // drawing at the original macro layout coordinates.
    if (isTaskKeypadMode) {
        extern bool buttonsDirty;
        buttonsDirty = true;
    } else {
        showPressFeedback(index);
    }

    // Send to server
    const Button& btn = buttons[index];
    if (btn.actionId.length() > 0) {
        apiClient.sendButtonPress(btn.slot, "tap");
    }
}

void ButtonRenderer::releaseButton(int index) {
    if (index < 0 || index >= (int)buttons.size()) return;

    buttons[index].pressed = false;
    if (isTaskKeypadMode) {
        extern bool buttonsDirty;
        buttonsDirty = true;
    } else {
        renderButton(index);
    }

    if (activeButton == index) {
        activeButton = -1;
    }
}

bool ButtonRenderer::isButtonPressed(int index) {
    if (index < 0 || index >= (int)buttons.size()) return false;
    return buttons[index].pressed;
}

void ButtonRenderer::showPressFeedback(int index) {
    if (index < 0 || index >= (int)buttons.size()) return;

    // Redraw with highlight
    drawButton(buttons[index], true);
}

void ButtonRenderer::clearFeedback() {
    unsigned long now = millis();

    if (activeButton >= 0 && now - pressStartTime > FEEDBACK_DURATION_MS) {
        releaseButton(activeButton);
    }
}

bool ButtonRenderer::checkLongPress() {
    // Check if screen is being touched anywhere
    int x, y;
    if (display.getTouch(&x, &y)) {
        if (!longPressActive) {
            // Start tracking long press
            longPressActive = true;
            longPressStartTime = millis();
        } else {
            // Check if held long enough
            unsigned long heldDuration = millis() - longPressStartTime;
            if (heldDuration >= LONG_PRESS_DURATION_MS) {
                // Long press detected
                return true;
            }
        }
    } else {
        // Touch released, reset tracking
        resetLongPress();
    }
    return false;
}

void ButtonRenderer::resetLongPress() {
    longPressActive = false;
    longPressStartTime = 0;
}

int ButtonRenderer::checkPageIndicatorTouch(int x, int y) {
    if (totalPages <= 1) {
        return 0;
    }

    const int taskbarHeight = 16;
    const int indicatorSize = 18;
    const int radius = indicatorSize / 2;
    const int centerY = taskbarHeight + radius + 1;

    int pagesToShow = totalPages;
    if (pagesToShow > 4) {
        pagesToShow = 4;
    }

    int totalWidth = pagesToShow * indicatorSize + (pagesToShow - 1) * 6;
    int startX = (SCREEN_WIDTH - totalWidth) / 2 + radius;

    for (int i = 0; i < pagesToShow; ++i) {
        int page = i + 1;
        int cx = startX + i * (indicatorSize + 6);

        int dx = x - cx;
        int dy = y - centerY;
        if (dx * dx + dy * dy <= radius * radius) {
            return page;
        }
    }

    return 0;
}
