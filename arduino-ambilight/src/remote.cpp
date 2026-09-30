#include "remote.h"
#include <IRremote.hpp>

static RemoteButton lastButton = BTN_NONE;
static unsigned long lastTime = 0;

void remote_init() {
    IrReceiver.begin(RECV_PIN);
}

static RemoteButton from_raw(unsigned long val) {
    switch (val) {
        case REMOTE_POWER:    return BTN_POWER;
        case REMOTE_VOL_UP:   return BTN_VOL_UP;
        case REMOTE_VOL_DOWN: return BTN_VOL_DOWN;
        case REMOTE_FUNC:     return BTN_FUNC;
        case REMOTE_EQ:       return BTN_EQ;
        case REMOTE_ST:       return BTN_ST;
        case REMOTE_PREV:     return BTN_PREV;
        case REMOTE_PLAY:     return BTN_PLAY;
        case REMOTE_NEXT:     return BTN_NEXT;
        case REMOTE_UP:       return BTN_UP;
        case REMOTE_DOWN:     return BTN_DOWN;
        case REMOTE_0:        return BTN_0;
        case REMOTE_1:        return BTN_1;
        case REMOTE_2:        return BTN_2;
        case REMOTE_3:        return BTN_3;
        case REMOTE_4:        return BTN_4;
        case REMOTE_5:        return BTN_5;
        case REMOTE_6:        return BTN_6;
        case REMOTE_7:        return BTN_7;
        case REMOTE_8:        return BTN_8;
        case REMOTE_9:        return BTN_9;
        default:              return BTN_NONE;
    }
}

RemoteEvent remote_read() {
    RemoteEvent ev = {BTN_NONE, false, 0};
    if (!IrReceiver.decode()) return ev;

    auto &data = IrReceiver.decodedIRData;
    bool isRepeat = data.flags & IRDATA_FLAGS_IS_REPEAT;
    unsigned long val = data.decodedRawData;
    bool valid = data.protocol == NEC;   // NEC vérifie son intégrité : le reste = trame abîmée
    IrReceiver.resume();
    if (!valid) return ev;

    unsigned long now = millis();
    if (isRepeat || val == 0) {
        // Répétition : seulement juste après une vraie touche
        if (lastButton != BTN_NONE && now - lastTime < 250) {
            ev.button = lastButton;
            ev.repeat = true;
            lastTime = now;
        }
        return ev;
    }
    ev.button = from_raw(val);
    ev.raw = val;
    lastButton = ev.button;
    lastTime = now;
    return ev;
}

const char *remote_name(RemoteButton b) {
    switch (b) {
        case BTN_POWER:    return "POWER";
        case BTN_VOL_UP:   return "VOL_UP";
        case BTN_VOL_DOWN: return "VOL_DOWN";
        case BTN_FUNC:     return "FUNC";
        case BTN_EQ:       return "EQ";
        case BTN_ST:       return "ST";
        case BTN_PREV:     return "PREV";
        case BTN_PLAY:     return "PLAY";
        case BTN_NEXT:     return "NEXT";
        case BTN_UP:       return "UP";
        case BTN_DOWN:     return "DOWN";
        case BTN_0:        return "0";
        case BTN_1:        return "1";
        case BTN_2:        return "2";
        case BTN_3:        return "3";
        case BTN_4:        return "4";
        case BTN_5:        return "5";
        case BTN_6:        return "6";
        case BTN_7:        return "7";
        case BTN_8:        return "8";
        case BTN_9:        return "9";
        default:           return "?";
    }
}

// Les LEDs WS2812 coupent les interruptions pendant leur rafraîchissement
// (~3,4 ms pour 113 LEDs) : si une trame IR arrive à ce moment elle est
// abîmée. On évite donc de rafraîchir pendant une réception en cours.
void remote_wait_idle(uint16_t max_ms) {
    unsigned long t0 = millis();
    while (!IrReceiver.isIdle() && millis() - t0 < max_ms) {}
}
