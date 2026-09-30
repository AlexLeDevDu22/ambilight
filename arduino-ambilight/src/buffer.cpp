#include "buffer.h"
#include "remote.h"

bool buffer_has_data() {
    return Serial.available() >= 4;
}

PacketType buffer_check() {
    if (!buffer_has_data()) return PACKET_NONE;
    // Lire header
    if (Serial.read() != 0xAA) return PACKET_NONE;
    int type = Serial.read();
    if (type == 0xCC) {           // ping : 2 octets de bourrage
        Serial.read();
        Serial.read();
        return PACKET_PING;
    }
    if (type != 0xBB) return PACKET_NONE;
    
    // Lire nombre de LEDs
    uint16_t ledCount = (uint16_t)Serial.read();
    ledCount |= (uint16_t)Serial.read() << 8;
    
    if (ledCount == 0 || ledCount > NUM_LEDS) {
        Serial.println("ERR:BAD_COUNT: " + String(ledCount));
        return PACKET_NONE;
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
                return PACKET_NONE;
            }
        }

        uint16_t idx = received / 3;
        leds[idx].r = Serial.read();
        leds[idx].g = Serial.read();
        leds[idx].b = Serial.read();
        received += 3;
    }

    remote_wait_idle(80);   // ne pas abîmer une trame IR en cours
    leds_show();
    Serial.println("OK");
    return PACKET_FRAME;
}
