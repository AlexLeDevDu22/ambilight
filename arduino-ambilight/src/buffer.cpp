#include "buffer.h"

bool buffer_has_data() {
    return Serial.available() >= 4;
}

bool buffer_check() {
    if (!buffer_has_data()) return false;
    // Lire header
    if (Serial.read() != 0xAA) return false;
    if (Serial.read() != 0xBB) return false;
    
    // Lire nombre de LEDs
    uint16_t ledCount = (uint16_t)Serial.read();
    ledCount |= (uint16_t)Serial.read() << 8;
    
    if (ledCount == 0 || ledCount > NUM_LEDS) {
        Serial.println("ERR:BAD_COUNT: " + String(ledCount));
        return false;
    }

    // Lire les RGB
    const uint32_t expectedBytes = (uint32_t)ledCount * 3;
    uint32_t received = 0;
    
    while (received < expectedBytes) {
        unsigned long t0 = millis();
        //Serial.println(received);
        //delay(1000);
        //Serial.println(Serial.available());
        while (Serial.available() < 3) {

            if (millis() - t0 > RECEIVE_TIMEOUT) {
                Serial.println("ERR:TIMEOUT");
                leds_clear();
                return false;
            }
        }

        uint16_t idx = received / 3;
        leds[idx].r = Serial.read();
        leds[idx].g = Serial.read();
        leds[idx].b = Serial.read();
        received += 3;
    }

    leds_show();
    Serial.println("OK");
    return true;
}
