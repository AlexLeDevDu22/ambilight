#include "modes.h"
#include "leds.h"


ModeState gState = {MODE_FIXED, COLOR_CYAN, 128, true, 0};

CRGB ColorMap[] = {
    CRGB::Red,
    CRGB::Green,
    CRGB::Blue,
    CRGB::Cyan,
    CRGB::Magenta,
    CRGB::Yellow,
    CRGB::White,
    CRGB(255, 140, 0),  // Orange
    CRGB(255, 105, 180) // Pink
};

CRGB modes_get_color() {
    return ColorMap[gState.color];
}

uint8_t speed_to_delay(uint8_t speed) {
    return map(speed, 0, 255, 500, 10);
}

// ─ FIXED COLOR ────────────────────────────────────────────────────
void mode_fixed() {
    CRGB color = modes_get_color();
    // Serial.print("Mode: FIXED, color: ");
    // Serial.print(color.r);
    // Serial.print(",");
    // Serial.print(color.g);
    // Serial.print(",");
    // Serial.print(color.b);
    // Serial.println();
    if (gState.animating) {
        leds_fill(color);
    }
}

// ─ RAINBOW ────────────────────────────────────────────────────────
void mode_rainbow() {
    static uint8_t hue = 0;
    if (!gState.animating) {
        leds_clear();
        return;
    }

    unsigned long now = millis();
    if (now - gState.lastUpdate > speed_to_delay(gState.speed)) {
        fill_rainbow(leds, NUM_LEDS, hue, 255 / NUM_LEDS);
        leds_show();
        hue += 2;
        gState.lastUpdate = now;
    }
}

// ─ BREATHING ──────────────────────────────────────────────────────
void mode_breathing() {
    static uint8_t brightness = 50;
    static int8_t direction = 1;

    if (!gState.animating) {
        leds_clear();
        return;
    }

    unsigned long now = millis();
    if (now - gState.lastUpdate > speed_to_delay(gState.speed)) {
        leds_fill(modes_get_color());
        leds_set_brightness(brightness);

        brightness += direction * 2;
        if (brightness >= 200) direction = -1;
        if (brightness <= 50) direction = 1;

        gState.lastUpdate = now;
    }
}

// ─ PULSE ──────────────────────────────────────────────────────────
void mode_pulse() {
    static uint8_t brightness = 100;
    static uint8_t phase = 0;

    if (!gState.animating) {
        leds_clear();
        return;
    }

    unsigned long now = millis();
    if (now - gState.lastUpdate > speed_to_delay(gState.speed) * 2) {
        leds_fill(modes_get_color());

        if (phase < 50) {
            brightness = 50 + phase;
        } else {
            brightness = 150 - (phase - 50);
        }

        leds_set_brightness(brightness);
        phase = (phase + 1) % 100;
        gState.lastUpdate = now;
    }
}

// ─ FIRE ───────────────────────────────────────────────────────────
void mode_fire() {
    if (!gState.animating) {
        leds_clear();
        return;
    }

    unsigned long now = millis();
    if (now - gState.lastUpdate > speed_to_delay(gState.speed)) {
        for (int i = 0; i < NUM_LEDS; i++) {
            uint8_t flicker = random(50, 255);
            // Use direct hue value for orange (approx 20) instead of undefined hue2rgb()
            leds[i] = CHSV(20, 255, flicker);  // Orange with flicker
        }
        leds_show();
        gState.lastUpdate = now;
    }
}

// ─ TWINKLE ────────────────────────────────────────────────────────
void mode_twinkle() {
    static unsigned long lastTwinkle = 0;

    if (!gState.animating) {
        leds_clear();
        return;
    }

    unsigned long now = millis();
    leds_fill(modes_get_color());

    if (now - lastTwinkle > speed_to_delay(gState.speed)) {
        for (int i = 0; i < 5; i++) {
            int idx = random(NUM_LEDS);
            leds[idx] = CRGB::White;
        }
        leds_show();
        lastTwinkle = now;
    } else {
        for (int i = 0; i < NUM_LEDS; i++) {
            leds[i] = leds[i].fadeToBlackBy(10);
        }
        leds_show();
    }
}

// ─ CHASE ──────────────────────────────────────────────────────────
void mode_chase() {
    static uint8_t pos = 0;

    if (!gState.animating) {
        leds_clear();
        return;
    }

    unsigned long now = millis();
    if (now - gState.lastUpdate > speed_to_delay(gState.speed)) {
        leds_clear();
        for (int i = 0; i < 3; i++) {
            int idx = (pos + i * (NUM_LEDS / 3)) % NUM_LEDS;
            leds[idx] = modes_get_color();
        }
        leds_show();
        pos = (pos + 1) % NUM_LEDS;
        gState.lastUpdate = now;
    }
}

// ─ WAVE ───────────────────────────────────────────────────────────
void mode_wave() {
    static uint8_t offset = 0;

    if (!gState.animating) {
        leds_clear();
        return;
    }

    unsigned long now = millis();
    if (now - gState.lastUpdate > speed_to_delay(gState.speed)) {
        for (int i = 0; i < NUM_LEDS; i++) {
            uint8_t brightness = 128 + 127 * sin8((i + offset) * 2);
            leds[i] = modes_get_color();
            leds[i].nscale8(brightness);
        }
        leds_show();
        offset += 4;
        gState.lastUpdate = now;
    }
}

// ─ AURORA ─────────────────────────────────────────────────────────
void mode_aurora() {
    static uint8_t hue = 0;

    if (!gState.animating) {
        leds_clear();
        return;
    }

    unsigned long now = millis();
    if (now - gState.lastUpdate > speed_to_delay(gState.speed)) {
        for (int i = 0; i < NUM_LEDS; i++) {
            uint8_t h = hue + (i * 255 / NUM_LEDS);
            uint8_t sat = 200;
            uint8_t val = 150 + 50 * sin8(i * 2 + hue);
            leds[i] = CHSV(h, sat, val);
        }
        leds_show();
        hue += 2;
        gState.lastUpdate = now;
    }
}

// ────────────────────────────────────────────────────────────────────
void modes_init() {
    gState.mode = MODE_FIXED;
    gState.color = COLOR_CYAN;
    gState.speed = 128;
    gState.animating = true;
    leds_fill(modes_get_color());
}

void modes_update() {
    switch (gState.mode) {
        case MODE_FIXED:    mode_fixed(); break;
        case MODE_RAINBOW:  mode_rainbow(); break;
        case MODE_BREATHING:mode_breathing(); break;
        case MODE_PULSE:    mode_pulse(); break;
        case MODE_FIRE:     mode_fire(); break;
        case MODE_TWINKLE:  mode_twinkle(); break;
        case MODE_CHASE:    mode_chase(); break;
        case MODE_WAVE:     mode_wave(); break;
        case MODE_AURORA:   mode_aurora(); break;
        default:            Serial.println("Invalid mode");   break;
    }

}

void log_mode_state() {
    Serial.print("Mode: ");
    Serial.print(gState.mode);
    Serial.print(", color: ");
    CRGB color = modes_get_color();
    Serial.print(color.r);
    Serial.print(",");
    Serial.print(color.g);
    Serial.print(",");
    Serial.print(color.b);
    Serial.print(", speed: ");
    Serial.print(gState.speed);
    Serial.print(", brightness: ");
    Serial.print(String(leds_get_brightness()));
    Serial.print(", animating: ");
    Serial.println(gState.animating);
}

void modes_set_mode(ModeType mode) {
    gState.animating = true;
    gState.mode = mode;
    gState.lastUpdate = millis();
    leds_clear();
}

void modes_next_mode() {
    ModeType next = (ModeType)((gState.mode + 1) % 9);
    modes_set_mode(next);
}

void modes_set_color(ColorPalette color) {
    gState.color = color;
    if (gState.mode == MODE_FIXED) {
        leds_fill(modes_get_color());
    }
}

void modes_next_color() {
    ColorPalette next = (ColorPalette)((gState.color + 1) % 9);
    modes_set_color(next);
}

void modes_set_speed(uint8_t speed) {
    gState.speed = speed;
}

void modes_toggle_animation() {
    gState.animating = !gState.animating;
    if (!gState.animating) { // Off
        leds_clear();
    } else { // On
        gState.lastUpdate = millis();
        modes_set_mode(gState.mode); // Restart the current mode to reset animations
    }
}

void modes_brightness_up() {
    uint8_t br = leds_get_brightness();
    leds_set_brightness(min(250, br * 2));
}

void modes_brightness_down() {
    uint8_t br = leds_get_brightness();
    leds_set_brightness(max(1, br / 2));
}
