#ifndef MODES_H
#define MODES_H

#include "leds.h"

enum ModeType {
    MODE_FIXED = 0,      // Couleur fixe
    MODE_RAINBOW = 1,    // Arc-en-ciel
    MODE_BREATHING = 2,  // Respiration
    MODE_PULSE = 3,      // Pulse lent
    MODE_FIRE = 4,       // Feu doux
    MODE_TWINKLE = 5,    // Scintillement
    MODE_CHASE = 6,      // Theater chase
    MODE_WAVE = 7,       // Vague
    MODE_AURORA = 8      // Aurore boréale
};

enum ColorPalette {
    COLOR_RED = 0,
    COLOR_GREEN = 1,
    COLOR_BLUE = 2,
    COLOR_CYAN = 3,
    COLOR_MAGENTA = 4,
    COLOR_YELLOW = 5,
    COLOR_WHITE = 6,
    COLOR_ORANGE = 7,
    COLOR_PINK = 8
};

struct ModeState {
    ModeType mode;
    ColorPalette color;
    uint8_t speed;        // 0-255, 128 = normal
    bool animating;
    unsigned long lastUpdate;
};

extern ModeState gState;

void modes_init();
void modes_update();
void modes_set_mode(ModeType mode);
void modes_next_mode();
void modes_set_color(ColorPalette color);
void modes_next_color();
void modes_set_speed(uint8_t speed);
void modes_toggle_animation();
void modes_brightness_up();
void modes_brightness_down();

CRGB modes_get_color();

#endif
