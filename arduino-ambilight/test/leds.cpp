#include "leds.h"

CRGB leds[NUM_LEDS];

void leds_init() {
    FastLED.addLeds<WS2812B, DATA_PIN, GRB>(leds, NUM_LEDS);
    FastLED.clear();
    FastLED.setBrightness(100);
    FastLED.show();
}

void leds_show() {
    FastLED.show();
}

void leds_clear() {
    FastLED.clear();
    FastLED.show();
}

void leds_fill(CRGB color) {
    fill_solid(leds, NUM_LEDS, color);
    leds_show();
}

void leds_set(int idx, CRGB color) {
    if (idx >= 0 && idx < NUM_LEDS) {
        leds[idx] = color;
    }
}

void leds_set_brightness(uint8_t brightness) {
    FastLED.setBrightness(brightness);
    leds_show();
}

uint8_t leds_get_brightness() {
    return FastLED.getBrightness();
}
