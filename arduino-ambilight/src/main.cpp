#include <Arduino.h>
#include <remote.h>
#include <modes.h>
#include <buffer.h>

// Le serveur (Mac) est considéré présent s'il a envoyé une trame ou un ping
// depuis moins de HOST_TIMEOUT ms. Dans ce cas la télécommande pilote le
// serveur (les touches lui sont transmises : "IR:<TOUCHE>"). Sinon l'Arduino
// fonctionne seul avec ses modes intégrés.
#define HOST_TIMEOUT 3000

enum SystemState {
    STATE_SERIAL,   // Affiche les trames du serveur
    STATE_REMOTE,   // Modes autonomes (télécommande)
    STATE_IDLE      // Aucun signal
};

SystemState gSystemState = STATE_IDLE;
unsigned long gLastHost = 0;

static bool host_alive() {
    return gLastHost != 0 && millis() - gLastHost < HOST_TIMEOUT;
}

// Modes autonomes : comportement historique de la télécommande
static void handle_local(RemoteButton b) {
    if (gSystemState != STATE_REMOTE) {
        gSystemState = STATE_REMOTE;
        modes_init();
    }
    switch (b) {
        case BTN_POWER:    modes_toggle_animation(); break;
        case BTN_PLAY:     modes_toggle_animation(); break;
        case BTN_VOL_UP:   modes_brightness_up(); break;
        case BTN_VOL_DOWN: modes_brightness_down(); break;
        case BTN_FUNC:     modes_next_mode(); break;
        case BTN_PREV:     modes_set_color((ColorPalette)((gState.color - 1 + 9) % 9)); break;
        case BTN_NEXT:     modes_next_color(); break;
        case BTN_UP:       modes_set_speed(min(255, gState.speed + 20)); break;
        case BTN_DOWN:     modes_set_speed(max(0, gState.speed - 20)); break;
        case BTN_1:        modes_set_mode(MODE_FIXED); break;
        case BTN_2:        modes_set_mode(MODE_RAINBOW); break;
        case BTN_3:        modes_set_mode(MODE_BREATHING); break;
        case BTN_4:        modes_set_mode(MODE_PULSE); break;
        case BTN_5:        modes_set_mode(MODE_FIRE); break;
        case BTN_6:        modes_set_mode(MODE_TWINKLE); break;
        case BTN_7:        modes_set_mode(MODE_CHASE); break;
        case BTN_8:        modes_set_mode(MODE_WAVE); break;
        case BTN_9:        modes_set_mode(MODE_AURORA); break;
        default: break;
    }
    modes_update();
}

void setup() {
    Serial.begin(BAUD_RATE);
    leds_init();
    remote_init();
    modes_init();
    leds_clear();   // noir au démarrage : le serveur joue son animation d'allumage
    Serial.println("READY");
}

void loop() {
    PacketType packet = buffer_check();
    if (packet != PACKET_NONE) {
        gLastHost = millis();
        if (packet == PACKET_FRAME && gSystemState != STATE_SERIAL) {
            gSystemState = STATE_SERIAL;
        }
        return;  // Continue à recevoir Serial
    }

    RemoteEvent ev = remote_read();
    if (ev.button == BTN_NONE && ev.raw != 0 && host_alive()) {
        // Touche inconnue : on transmet le code brut (diagnostic)
        Serial.print("IR:RAW:");
        Serial.println(ev.raw, HEX);
    }
    if (ev.button != BTN_NONE) {
        if (host_alive()) {
            // Le serveur décide (interface, souris…)
            Serial.print("IR:");
            Serial.print(remote_name(ev.button));
            if (ev.repeat) Serial.print(":R");
            Serial.println();
        } else if (!ev.repeat || ev.button == BTN_VOL_UP || ev.button == BTN_VOL_DOWN) {
            handle_local(ev.button);
        }
    } else if (gSystemState == STATE_REMOTE) {
        // Continuer à animer le mode autonome
        modes_update();
    }
}
