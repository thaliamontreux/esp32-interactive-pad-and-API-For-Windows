#include "button_renderer.h"
#include "api_client.h"
#include "icon_cache.h"
#include "../../../esp32_icons.h"
#include "storage.h"
#include "connection_mode.h"
#include "bluetooth_manager.h"
#include "penta_star_studios_new_png.h"

#include <WiFi.h>
#include <algorithm>

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

static void drawOrbIndicator(int cx, int cy, int radius, uint16_t fill, uint16_t border);
static const int TOP_BAR_X = 4;
static const int TOP_BAR_Y = 2;
static const int TOP_BAR_W = SCREEN_WIDTH - 8;
static const int TOP_BAR_H = 18;
static const int PAGE_STRIP_Y = TOP_BAR_Y + TOP_BAR_H + 2;
static const int PAGE_STRIP_H = 24;
static const int PAGE_INDICATOR_SIZE = 18;
static const int PAGE_INDICATOR_RADIUS = PAGE_INDICATOR_SIZE / 2;
static const int PAGE_INDICATOR_CENTER_Y = PAGE_STRIP_Y + PAGE_INDICATOR_RADIUS + 1;

static int dayOfWeek(int year, int month, int day) {
    static const int t[] = {0, 3, 2, 5, 0, 3, 5, 1, 4, 6, 2, 4};
    if (month < 3) {
        year -= 1;
    }
    int w = year + year / 4 - year / 100 + year / 400 + t[month - 1] + day;
    return w % 7;  // 0 = Sunday, 1 = Monday, ...
}

static bool isUsDstActiveForDate(const struct tm& utc) {
    int year = utc.tm_year + 1900;
    int month = utc.tm_mon + 1;  // 1-12
    int day = utc.tm_mday;

    if (month < 3 || month > 11) {
        return false;
    }
    if (month > 3 && month < 11) {
        return true;
    }

    if (month == 3) {
        int dowMar1 = dayOfWeek(year, 3, 1);  // 0 = Sunday
        int firstSunday = 1 + ((7 - dowMar1) % 7);
        int secondSunday = firstSunday + 7;
        return day > secondSunday;
    }

    if (month == 11) {
        int dowNov1 = dayOfWeek(year, 11, 1);
        int firstSunday = 1 + ((7 - dowNov1) % 7);
        return day < firstSunday;
    }

    return false;
}

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

// PNGdec callbacks for the embedded lock-screen PNG. These read directly from
// the PentaStarStudiosPng byte array in flash, so they do not depend on
// LittleFS at all and cannot fail due to filesystem space constraints.
static int32_t g_lockPngPos = 0;

void* pngOpenLock(const char* filename, int32_t* size) {
    (void)filename;
    g_lockPngPos = 0;
    *size = (int32_t)PentaStarStudiosNewPngSize;
    return (void*)1;  // dummy non-null handle
}

void pngCloseLock(void* handle) {
    (void)handle;
}

int32_t pngReadLock(PNGFILE* page, uint8_t* buffer, int32_t length) {
    (void)page;
    int32_t remaining = (int32_t)PentaStarStudiosNewPngSize - g_lockPngPos;
    if (remaining <= 0) {
        return 0;
    }
    if (length > remaining) {
        length = remaining;
    }
    memcpy(buffer, PentaStarStudiosNewPng + g_lockPngPos, length);
    g_lockPngPos += length;
    return length;
}

int32_t pngSeekLock(PNGFILE* page, int32_t position) {
    (void)page;
    if (position < 0) {
        position = 0;
    }
    if (position > (int32_t)PentaStarStudiosNewPngSize) {
        position = (int32_t)PentaStarStudiosNewPngSize;
    }
    g_lockPngPos = position;
    return g_lockPngPos;
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


void ButtonRenderer::showHostLockScreen() {
    display.clear();
    display.fillScreen(COLOR_BG_DARK);
    needsFullSurfaceClear = true;
    display.fillRect(0, 0, SCREEN_WIDTH, 18, COLOR_BG_DARKER);
    display.fillRect(0, SCREEN_HEIGHT - 36, SCREEN_WIDTH, 36, COLOR_BG_DARKER);
    display.drawLine(0, 0, SCREEN_WIDTH, 0, COLOR_NEON_PURPLE);
    display.drawLine(0, 17, SCREEN_WIDTH, 17, COLOR_NEON_CYAN);
    display.drawLine(0, SCREEN_HEIGHT - 37, SCREEN_WIDTH, SCREEN_HEIGHT - 37, COLOR_NEON_PURPLE);

    drawOrbIndicator(16, 9, 6, COLOR_NEON_PURPLE, COLOR_NEON_CYAN);
    display.setTextSize(1);
    display.setTextDatum(ML_DATUM);
    display.setTextColor(COLOR_WHITE, COLOR_BG_DARKER);
    display.drawString("HOST LOCKED", 28, 9);

    // The lock-screen image is provided as an embedded PNG in firmware and
    // decoded directly from flash using dedicated PNGdec callbacks so that
    // BLE-only pads never require WiFi or LittleFS space to display it.
    Serial.println("[ButtonRenderer] Rendering embedded host lock screen");

    int16_t innerX = 10;
    int16_t innerY = 24;
    int16_t innerW = display.width() - 20;
    int16_t innerH = display.height() - 72;

    if (innerW <= 0 || innerH <= 0) {
        return;
    }

    display.fillRoundRect(innerX - 4, innerY - 4, innerW + 8, innerH + 8, 10, COLOR_BG_MID);
    display.fillRoundRect(innerX - 2, innerY - 2, innerW + 4, innerH + 4, 8, COLOR_BG_DARK);
    display.drawRoundRect(innerX - 4, innerY - 4, innerW + 8, innerH + 8, 10, COLOR_NEON_PURPLE);
    display.drawRoundRect(innerX - 2, innerY - 2, innerW + 4, innerH + 4, 8, COLOR_NEON_CYAN);

    // Reset global PNG state for this decode.
    iconBgColor = COLOR_BLACK;
    iconFgColor = COLOR_BLACK;
    iconBgSampled = false;
    iconTransparentCount = 0;
    iconSemiTransparentCount = 0;
    iconDarkCount = 0;
    iconWhiteCount = 0;
    iconOtherCount = 0;

    int16_t analyzeOpen = png.open("embedded_lock", pngOpenLock, pngCloseLock, pngReadLock, pngSeekLock, pngDrawAnalyze);
    if (analyzeOpen != PNG_SUCCESS) {
        Serial.print("[ButtonRenderer] PNG open (analyze) failed for embedded lock screen rc=");
        Serial.println(analyzeOpen);
        return;
    }

    iconSrcW = png.getWidth();
    iconSrcH = png.getHeight();
    if (iconSrcW <= 0 || iconSrcH <= 0) {
        png.close();
        return;
    }

    // Analyze pass
    png.decode(nullptr, 0);

    // Compute scaled draw size preserving aspect ratio
    int32_t scaleW = (int32_t)innerW * 1000 / iconSrcW;
    int32_t scaleH = (int32_t)innerH * 1000 / iconSrcH;
    int32_t scale = scaleW < scaleH ? scaleW : scaleH;
    if (scale <= 0) scale = 1;
    if (scale > 1000) scale = 1000;
    iconDrawW = (int16_t)(iconSrcW * scale / 1000);
    iconDrawH = (int16_t)(iconSrcH * scale / 1000);

    if (iconDrawW <= 0 || iconDrawH <= 0) {
        png.close();
        return;
    }

    iconX = innerX + (innerW - iconDrawW) / 2;
    iconY = innerY + (innerH - iconDrawH) / 2;

    // Re-open and render the PNG using the existing pngDrawRender callback.
    png.close();
    int16_t renderOpen = png.open("embedded_lock", pngOpenLock, pngCloseLock, pngReadLock, pngSeekLock, pngDrawRender);
    if (renderOpen != PNG_SUCCESS) {
        Serial.print("[ButtonRenderer] PNG open (render) failed for embedded lock screen rc=");
        Serial.println(renderOpen);
        png.close();
        return;
    }

    png.decode(nullptr, 0);
    png.close();

    display.drawRoundRect(innerX - 4, innerY - 4, innerW + 8, innerH + 8, 10, COLOR_NEON_PURPLE);
    display.drawRoundRect(innerX - 2, innerY - 2, innerW + 4, innerH + 4, 8, COLOR_NEON_CYAN);

    display.fillRoundRect(12, SCREEN_HEIGHT - 30, SCREEN_WIDTH - 24, 20, 8, COLOR_BG_MID);
    display.drawRoundRect(12, SCREEN_HEIGHT - 30, SCREEN_WIDTH - 24, 20, 8, COLOR_NEON_YELLOW);
    drawOrbIndicator(26, SCREEN_HEIGHT - 20, 5, COLOR_NEON_YELLOW, COLOR_WHITE);
    display.setTextDatum(ML_DATUM);
    display.setTextColor(COLOR_WHITE, COLOR_BG_MID);
    display.drawString("Waiting for your PC to unlock", 38, SCREEN_HEIGHT - 20);

    extern SecureStorage storage;
    String host = storage.getApiHost();
    if (host.length() > 0) {
        if (host.length() > 22) {
            host = host.substring(0, 19) + "...";
        }
        display.setTextDatum(MR_DATUM);
        display.setTextColor(COLOR_NEON_CYAN, COLOR_BG_DARKER);
        display.drawString(host, SCREEN_WIDTH - 8, 9);
    }
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
      buttonsPerPage(0),
      isTaskKeypadMode(false),
      needsFullSurfaceClear(true) {}

bool ButtonRenderer::begin() {
    // Clear to a dark industrial background when the renderer initializes
    display.fillScreen(COLOR_BG_DARK);
    needsFullSurfaceClear = true;
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

static uint16_t blend565(uint16_t from, uint16_t to, uint8_t amount) {
    uint16_t fr = (from >> 11) & 0x1F;
    uint16_t fg = (from >> 5) & 0x3F;
    uint16_t fb = from & 0x1F;
    uint16_t tr = (to >> 11) & 0x1F;
    uint16_t tg = (to >> 5) & 0x3F;
    uint16_t tb = to & 0x1F;

    uint16_t rr = (uint16_t)((fr * (255 - amount) + tr * amount) / 255);
    uint16_t rg = (uint16_t)((fg * (255 - amount) + tg * amount) / 255);
    uint16_t rb = (uint16_t)((fb * (255 - amount) + tb * amount) / 255);
    return (rr << 11) | (rg << 5) | rb;
}

static uint16_t lighten565(uint16_t color, uint8_t amount) {
    return blend565(color, COLOR_WHITE, amount);
}

static uint16_t darken565(uint16_t color, uint8_t amount) {
    return blend565(color, COLOR_BLACK, amount);
}

static uint8_t pulseAmount(uint8_t maxAmount, unsigned long periodMs = 1200) {
    if (maxAmount == 0 || periodMs < 2) {
        return 0;
    }
    unsigned long half = periodMs / 2;
    unsigned long phase = millis() % periodMs;
    unsigned long ramp = phase <= half ? phase : (periodMs - phase);
    return (uint8_t)((ramp * maxAmount) / half);
}

static void drawOrbIndicator(int cx, int cy, int radius, uint16_t fill, uint16_t border) {
    uint16_t shadow = darken565(fill, 170);
    uint16_t shell = darken565(fill, 70);
    uint16_t core = lighten565(fill, 35);
    uint16_t gleam = lighten565(fill, 145);

    display.fillCircle(cx + 1, cy + 1, radius + 1, shadow);
    display.fillCircle(cx, cy, radius, shell);
    if (radius > 1) {
        display.fillCircle(cx, cy, radius - 1, core);
    }
    display.drawCircle(cx, cy, radius, border);
    if (radius > 2) {
        display.fillCircle(cx - 1, cy - 1, radius / 2, gleam);
    }
}

void ButtonRenderer::loadConfig(const PadConfig& config) {
    buttons.clear();
    needsFullSurfaceClear = true;

    // Capture time display preferences for taskbar. The actual clock value
    // is synced directly from the host (local time), so we do not apply any
    // additional timezone offsets here.
    use24hFormat = config.use24h;
    showAmPm = config.showAmPm;
    timezoneOffsetMinutes = 0;

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
    needsFullSurfaceClear = true;
}

void ButtonRenderer::invalidateLayout() {
    needsFullSurfaceClear = true;
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

std::vector<int> ButtonRenderer::getPressedSlots() const {
    std::vector<int> pressedSlots;
    for (const auto &btn : buttons) {
        if (btn.pressed) {
            pressedSlots.push_back(btn.slot);
        }
    }
    return pressedSlots;
}

std::vector<int> ButtonRenderer::getActiveTaskSlots() const {
    std::vector<int> activeSlots;
    for (const auto &btn : buttons) {
        if (btn.taskAppRunning) {
            activeSlots.push_back(btn.slot);
        }
    }
    return activeSlots;
}

void ButtonRenderer::clearButtonRegion(const Button& btn) {
    int x = btn.x - 4;
    int y = btn.y - 4;
    int w = btn.w + 8;
    int h = btn.h + 10;
    if (x < 0) {
        w += x;
        x = 0;
    }
    if (y < 0) {
        h += y;
        y = 0;
    }
    if (x + w > SCREEN_WIDTH) {
        w = SCREEN_WIDTH - x;
    }
    if (y + h > SCREEN_HEIGHT) {
        h = SCREEN_HEIGHT - y;
    }
    if (w > 0 && h > 0) {
        display.fillRect(x, y, w, h, COLOR_BG_DARK);
    }
}

void ButtonRenderer::clearAllButtonRegions() {
    for (const auto &btn : buttons) {
        clearButtonRegion(btn);
    }
}

void ButtonRenderer::drawCurrentPageButtons() {
    if (isTaskKeypadMode) {
        std::vector<const Button*> layoutSlots;
        layoutSlots.reserve(buttons.size());
        for (const auto &btn : buttons) {
            if (btn.page == currentPage) {
                layoutSlots.push_back(&btn);
            }
        }

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
                Button drawBtn = *content;
                drawBtn.x = layout->x;
                drawBtn.y = layout->y;
                drawBtn.w = layout->w;
                drawBtn.h = layout->h;
                drawButton(drawBtn, content->pressed);
            }
        }
        return;
    }

    for (size_t i = 0; i < buttons.size(); i++) {
        if (buttons[i].page == currentPage) {
            renderButton(i);
        }
    }
}

void ButtonRenderer::clearPageIndicatorArea() {
    display.fillRect(0, PAGE_STRIP_Y, SCREEN_WIDTH, PAGE_STRIP_H, COLOR_BG_DARK);
}

void ButtonRenderer::forceRefresh() {
    // Redraw industrial-style background before everything
    if (needsFullSurfaceClear) {
        display.fillScreen(COLOR_BG_DARK);
        needsFullSurfaceClear = false;
    }
    drawTaskbar();
    drawPageIndicators();
    clearAllButtonRegions();
    drawCurrentPageButtons();
}

void ButtonRenderer::drawTaskbar() {
    const int iconSize = 14;
    uint16_t barOuter = COLOR_BG_MID;
    uint16_t barInner = blend565(COLOR_BG_DARKER, COLOR_BG_MID, 28);
    uint16_t barTop = blend565(COLOR_BG_DARKER, COLOR_NEON_PURPLE, 36);

    display.fillRect(0, 0, SCREEN_WIDTH, TOP_BAR_Y + TOP_BAR_H + 2, COLOR_BG_DARK);
    display.fillRoundRect(TOP_BAR_X, TOP_BAR_Y, TOP_BAR_W, TOP_BAR_H, 6, barOuter);
    display.fillRoundRect(TOP_BAR_X + 1, TOP_BAR_Y + 1, TOP_BAR_W - 2, TOP_BAR_H - 2, 5, barInner);
    display.fillRoundRect(TOP_BAR_X + 2, TOP_BAR_Y + 2, TOP_BAR_W - 4, 5, 4, barTop);
    display.drawRoundRect(TOP_BAR_X, TOP_BAR_Y, TOP_BAR_W, TOP_BAR_H, 6, lighten565(COLOR_NEON_PURPLE, 60));
    display.drawRoundRect(TOP_BAR_X + 1, TOP_BAR_Y + 1, TOP_BAR_W - 2, TOP_BAR_H - 2, 5, COLOR_NEON_CYAN);

    // Draw time on the left (small text, 12/24-hour per config). The ESP32
    // system clock is kept in sync directly from the host's current wall
    // clock (via BLE or API), so we treat time() as already being in the
    // host's local timezone and do not apply any extra timezone or DST
    // adjustments here.
    time_t now = time(nullptr);
    if (now > 0) {
        struct tm* timeinfo = gmtime(&now);
        if (!timeinfo) {
            return;
        }

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
        display.setTextDatum(ML_DATUM);
        display.setTextColor(lighten565(COLOR_NEON_CYAN, 80), barInner);
        display.drawString(timeStr, TOP_BAR_X + 6, TOP_BAR_Y + TOP_BAR_H / 2);
    }

    // Host name in the center (API host from storage)
    extern SecureStorage storage;
    String host = storage.getApiHost();
    if (host.length() > 0) {
        display.setTextSize(1);
        display.setTextDatum(MC_DATUM);
        display.setTextColor(lighten565(COLOR_WHITE, 10), barInner);

        // Constrain host name width so it doesn't collide with time or icons
        int leftReserved = 48;   // space for time text
        int rightReserved = 56;  // space for config icon + status dots
        int maxHostWidth = SCREEN_WIDTH - leftReserved - rightReserved - 4;
        while (display.textWidth(host) > maxHostWidth && host.length() > 0) {
            host.remove(host.length() - 1);
        }

        display.drawString(host, SCREEN_WIDTH / 2, TOP_BAR_Y + TOP_BAR_H / 2);
    }

    // Connection status indicators just left of the config icon. In WiFi
    // modes we show WiFi/API dots; in Bluetooth mode we show RX/TX activity
    // indicators driven by BLE traffic.
    const int statusRadius = 3;
    const int statusSpacing = 2;
    const int statusY = TOP_BAR_Y + TOP_BAR_H / 2;

    ConnectionMode mode = getConnectionMode();

    // Draw config gear icon at right side (14x14 area)
    int iconRight = TOP_BAR_X + TOP_BAR_W - 5;
    int iconLeft = iconRight - iconSize + 1;
    int iconTop = TOP_BAR_Y + (TOP_BAR_H - iconSize) / 2;
    int iconBottom = iconTop + iconSize - 1;
    int cx = (iconLeft + iconRight) / 2;
    int cy = (iconTop + iconBottom) / 2;

    if (mode == ConnectionMode::BLUETOOTH) {
        // BLE RX/TX indicators: two dots labelled RX and TX. Dots turn green
        // briefly when traffic is seen, red when idle.
        unsigned long nowMs = millis();
        const unsigned long ACTIVE_WINDOW_MS = 1000;  // 1s activity window

        unsigned long lastRx = btManager.getLastRxActivityMs();
        unsigned long lastTx = btManager.getLastTxActivityMs();

        bool rxActive = (lastRx != 0) && (nowMs - lastRx < ACTIVE_WINDOW_MS);
        bool txActive = (lastTx != 0) && (nowMs - lastTx < ACTIVE_WINDOW_MS);

        uint16_t rxColor = rxActive ? COLOR_GREEN : COLOR_RED;
        uint16_t txColor = txActive ? COLOR_GREEN : COLOR_RED;

        int txX = iconLeft - 4 - statusRadius;                   // closest to gear
        int rxX = txX - (statusRadius * 2 + statusSpacing);       // to the left

        drawOrbIndicator(rxX, statusY, statusRadius, rxColor, lighten565(rxColor, 60));
        drawOrbIndicator(txX, statusY, statusRadius, txColor, lighten565(txColor, 60));

        // Tiny labels 'R' and 'T' above the dots for clarity.
        display.setTextSize(1);
        display.setTextDatum(BC_DATUM);
        display.setTextColor(COLOR_WHITE, barInner);
        display.drawString("R", rxX, statusY - statusRadius - 1);
        display.drawString("T", txX, statusY - statusRadius - 1);
    } else {
        bool wifiConnected = (WiFi.status() == WL_CONNECTED);
        bool apiConnected = apiClient.isWebSocketConnected();

        uint16_t wifiColor = wifiConnected ? COLOR_GREEN : COLOR_RED;

        uint16_t apiColor;
        if (wifiConnected && !apiConnected) {
            // WiFi is up but API/WebSocket is down: flash yellow to indicate
            // we are attempting to (re)connect.
            unsigned long ms = millis();
            bool phaseOn = ((ms / 500) % 2) == 0;  // 500ms on/off
            apiColor = phaseOn ? COLOR_YELLOW : COLOR_DARK_GRAY;
        } else {
            // Normal states: green when connected, red when disconnected.
            apiColor = apiConnected ? COLOR_GREEN : COLOR_RED;
        }

        // Draw API status dot closest to gear
        int apiX = iconLeft - 4 - statusRadius;  // 4px gap from gear
        drawOrbIndicator(apiX, statusY, statusRadius, apiColor, lighten565(apiColor, 60));

        int wifiX = apiX - (statusRadius * 2 + statusSpacing);
        drawOrbIndicator(wifiX, statusY, statusRadius, wifiColor, lighten565(wifiColor, 60));
    }

    int radius = iconSize / 2 - 1;
    drawOrbIndicator(cx, cy, radius, COLOR_NEON_PURPLE, COLOR_NEON_CYAN);
    display.fillCircle(cx, cy, radius - 4, lighten565(COLOR_NEON_PURPLE, 55));
    display.drawCircle(cx, cy, radius - 2, lighten565(COLOR_NEON_CYAN, 70));
}

void ButtonRenderer::drawPageIndicators() {
    clearPageIndicatorArea();
    if (totalPages <= 1) {
        return;
    }

    const int indicatorSize = PAGE_INDICATOR_SIZE;
    const int radius = PAGE_INDICATOR_RADIUS;
    const int centerY = PAGE_INDICATOR_CENTER_Y;

    int pagesToShow = totalPages;
    if (pagesToShow > 4) {
        pagesToShow = 4;
    }

    int totalWidth = pagesToShow * indicatorSize + (pagesToShow - 1) * 6;
    int startX = (SCREEN_WIDTH - totalWidth) / 2 + radius;

    for (int i = 0; i < pagesToShow; ++i) {
        int page = i + 1;
        int cx = startX + i * (indicatorSize + 6);

        bool active = (page == currentPage);
        uint16_t fill = active ? COLOR_NEON_CYAN : blend565(COLOR_BG_DARKER, COLOR_NEON_PURPLE, 36);
        uint16_t border = active ? COLOR_NEON_YELLOW : COLOR_NEON_PURPLE;
        uint16_t text = active ? COLOR_BLACK : lighten565(COLOR_NEON_CYAN, 80);

        drawOrbIndicator(cx, centerY, radius, fill, border);

        display.setTextSize(1);
        display.setTextDatum(MC_DATUM);
        display.setTextColor(text, fill);
        display.drawCentreString(String(page), cx, centerY);
    }
}

bool ButtonRenderer::checkTaskbarTouch(int x, int y) {
    // Hit-test for config icon in 16px-high taskbar at top
    const int iconSize = 14;

    int iconRight = TOP_BAR_X + TOP_BAR_W - 5;
    int iconLeft = iconRight - iconSize + 1;
    int iconTop = TOP_BAR_Y + (TOP_BAR_H - iconSize) / 2;
    int iconBottom = iconTop + iconSize - 1;

    if (y >= iconTop && y <= iconBottom && x >= iconLeft && x <= iconRight) {
        // Config gear area clicked
        return true;
    }

    return false;
}

void ButtonRenderer::render() {
    forceRefresh();
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
    clearButtonRegion(btn);
    drawButton(btn, btn.pressed);
}

void ButtonRenderer::drawButton(const Button& btn, bool highlight) {
    int r = 8;
    int pressOffsetY = highlight ? 1 : 0;
    int shadowOffsetX = highlight ? 1 : 3;
    int shadowOffsetY = highlight ? 2 : 4;
    uint8_t flash = highlight ? pulseAmount(56, 420) : 0;

    uint16_t shellColor = highlight
        ? blend565(btn.bgColor, COLOR_NEON_CYAN, 120 + flash / 3)
        : darken565(btn.bgColor, 30);
    uint16_t faceTop = highlight
        ? blend565(btn.bgColor, COLOR_WHITE, 120 + flash / 3)
        : lighten565(btn.bgColor, 78);
    uint16_t faceMid = highlight
        ? blend565(btn.bgColor, COLOR_NEON_CYAN, 70 + flash / 4)
        : lighten565(btn.bgColor, 26);
    uint16_t faceBottom = highlight
        ? darken565(blend565(btn.bgColor, COLOR_NEON_PURPLE, 70), 20)
        : darken565(btn.bgColor, 42);
    uint16_t faceColor = faceMid;
    uint16_t outerBorder = highlight
        ? lighten565(COLOR_NEON_CYAN, flash / 2)
        : blend565(btn.bgColor, COLOR_NEON_PURPLE, 96);
    uint16_t innerBorder = highlight
        ? lighten565(COLOR_NEON_YELLOW, flash / 3)
        : lighten565(btn.bgColor, 96);
    uint16_t shadowColorFar = darken565(btn.bgColor, 190);
    uint16_t shadowColorNear = darken565(btn.bgColor, 125);
    uint16_t glossColor = highlight
        ? lighten565(COLOR_NEON_CYAN, 120 + flash / 3)
        : lighten565(btn.bgColor, 150);
    uint16_t lowlightColor = darken565(btn.bgColor, 120);

    display.fillRoundRect(btn.x + shadowOffsetX, btn.y + shadowOffsetY,
                          btn.w, btn.h, r, shadowColorFar);
    display.fillRoundRect(btn.x + (shadowOffsetX > 1 ? shadowOffsetX - 1 : shadowOffsetX),
                          btn.y + (shadowOffsetY > 1 ? shadowOffsetY - 1 : shadowOffsetY),
                          btn.w, btn.h, r, shadowColorNear);

    int shellX = btn.x;
    int shellY = btn.y + pressOffsetY;
    display.fillRoundRect(shellX, shellY, btn.w, btn.h, r, shellColor);

    int faceX = shellX + 2;
    int faceY = shellY + 2;
    int faceW = btn.w - 4;
    int faceH = btn.h - 4;
    int faceR = r - 2;

    if (faceW > 0 && faceH > 0) {
        display.fillRoundRect(faceX, faceY, faceW, faceH, faceR, faceBottom);

        int midH = (faceH * 62) / 100;
        if (midH < 4) midH = faceH;
        display.fillRoundRect(faceX + 1, faceY + 1, faceW - 2, faceH - 2, faceR > 1 ? faceR - 1 : 1, faceMid);
        if (midH > 2 && faceW > 6) {
            display.fillRoundRect(faceX + 2, faceY + 1, faceW - 4, midH, faceR > 2 ? faceR - 2 : 1, faceTop);
        }

        int glossW = faceW - 12;
        if (glossW > 6) {
            int glossH = faceH > 24 ? 7 : 5;
            display.fillRoundRect(faceX + 4, faceY + 3, glossW, glossH, glossH / 2, glossColor);
        }

        if (highlight) {
            int flashW = faceW - 18;
            if (flashW > 8) {
                uint16_t flashColor = lighten565(COLOR_NEON_CYAN, 145 + flash / 4);
                display.fillRoundRect(faceX + 9, faceY + faceH / 2 - 2, flashW, 4, 2, flashColor);
            }
        }

        display.drawRoundRect(shellX, shellY, btn.w, btn.h, r, outerBorder);
        display.drawRoundRect(faceX, faceY, faceW, faceH, faceR, innerBorder);

        int innerTopY = faceY + 2;
        int innerBottomY = faceY + faceH - 3;
        if (innerBottomY > innerTopY) {
            display.drawLine(faceX + 4, innerTopY, faceX + faceW - 5, innerTopY, glossColor);
            display.drawLine(faceX + 4, innerBottomY, faceX + faceW - 5, innerBottomY, lowlightColor);
        }
    } else {
        display.drawRoundRect(shellX, shellY, btn.w, btn.h, r, outerBorder);
    }

    Button contentBtn = btn;
    contentBtn.x = shellX;
    contentBtn.y = shellY;

    bool iconDrawn = false;

    // If this button has an associated application PNG icon, prefer that
    // over the built-in monochrome ESP32 icon set.
    if (btn.hasApplicationIcon && btn.applicationId > 0) {
        // Determine the local cache key for this application's PNG icon.
        // applicationIconKey may include a version/hash suffix so that
        // updated icons are re-fetched rather than reusing stale files.
        String appIconId = contentBtn.applicationIconKey.length() > 0
            ? contentBtn.applicationIconKey
            : String("app_") + String(contentBtn.applicationId);

        Serial.print("[ButtonRenderer] drawButton page=");
        Serial.print(contentBtn.page);
        Serial.print(" slot=");
        Serial.print(contentBtn.slot);
        Serial.print(" appId=");
        Serial.print(contentBtn.applicationId);
        Serial.print(" hasAppIcon=");
        Serial.print(contentBtn.hasApplicationIcon ? "true" : "false");
        Serial.print(" appIconId='");
        Serial.print(appIconId);
        Serial.println("'");

        if (iconCache.ensureIcon(appIconId)) {
            String path = iconCache.getIconPath(appIconId);
            Serial.println("[ButtonRenderer] Using app icon from '" + path + "'");

            // Compute icon placement within the inner face, similar to
            // drawEsp32Icon but using the PNG's native dimensions.
            int16_t innerX = contentBtn.x + 2;
            int16_t innerY = contentBtn.y + 1;
            int16_t innerW = contentBtn.w - 4;
            int16_t innerH = contentBtn.h - 4;
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
            iconDrawn = drawEsp32Icon(contentBtn, faceColor);
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

            int maxWidth = contentBtn.w - 10;
            while (display.textWidth(label) > maxWidth && label.length() > 0) {
                label = label.substring(0, label.length() - 1);
            }

            int16_t labelY = contentBtn.y + contentBtn.h - 10;
            display.drawCentreString(label, contentBtn.x + contentBtn.w / 2, labelY);
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
    // In Task Keypad mode, avoid forcing a full-screen refresh on press;
    // Taskpad visuals are driven by task_app_state updates from the host.
    if (!isTaskKeypadMode) {
        showPressFeedback(index);
    }

    // Send to server or host bridge. In Bluetooth mode (or AUTO with an
    // active BLE connection), we send a JSON message over BLE so the
    // ble_bluetooth_bridge can forward the press to the HTTP API. In pure
    // WiFi mode we keep using the existing HTTP endpoint.
    const Button& btn = buttons[index];
    if (btn.actionId.length() > 0) {
        ConnectionMode mode = getConnectionMode();
        bool useBle = false;

        if (mode == ConnectionMode::BLUETOOTH) {
            useBle = true;
        } else if (mode == ConnectionMode::AUTO && btManager.isConnected()) {
            useBle = true;
        }

        if (useBle) {
            extern SecureStorage storage;
            String padUUID = storage.getPadUUID();

            // Minimal JSON payload; the BLE bridge will translate this into
            // an HTTP POST /press call on the API server.
            String line = "{";
            line += "\"type\":\"button_press\",";
            line += "\"pad_uuid\":\"" + padUUID + "\",";
            line += "\"slot\":" + String(btn.slot) + ",";
            line += "\"press_type\":\"tap\"";
            line += "}";

            btManager.sendJsonLine(line);
        } else {
            apiClient.sendButtonPress(btn.slot, "tap");
        }
    }
}

void ButtonRenderer::releaseButton(int index) {
    if (index < 0 || index >= (int)buttons.size()) return;

    buttons[index].pressed = false;
    if (!isTaskKeypadMode) {
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
    clearButtonRegion(buttons[index]);
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

    const int indicatorSize = PAGE_INDICATOR_SIZE;
    const int radius = PAGE_INDICATOR_RADIUS;
    const int centerY = PAGE_INDICATOR_CENTER_Y;

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
