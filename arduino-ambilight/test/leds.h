#ifndef LEDS_H
#define LEDS_H
#include <Arduino.h>
#include <FastLED.h>

#define NUM_LEDS 113
#define DATA_PIN 6
#define BAUD_RATE 115200


extern CRGB leds[NUM_LEDS];

void leds_init();
void leds_show();
void leds_clear();
void leds_fill(CRGB color);
void leds_set(int idx, CRGB color);
void leds_set_brightness(uint8_t brightness);
uint8_t leds_get_brightness();

#endif
