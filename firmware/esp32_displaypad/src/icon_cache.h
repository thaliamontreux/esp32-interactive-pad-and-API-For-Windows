#ifndef DISPLAYPAD_ICON_CACHE_H
#define DISPLAYPAD_ICON_CACHE_H

#include <Arduino.h>

class IconCache {
public:
    bool begin();
    bool ensureIcon(const String& iconId);
    bool hasIcon(const String& iconId);
    String getIconPath(const String& iconId);
};

extern IconCache iconCache;

#endif
