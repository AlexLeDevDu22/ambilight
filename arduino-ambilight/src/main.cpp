
#include <Arduino.h>
#include <remote.h>
#include <modes.h>
#include <buffer.h>

#define BAUD_RATE       115200   // 12× plus rapide = 12× moins de risque d'overflow

enum SystemState {
    STATE_SERIAL,   // Reçoit du Serial
    STATE_REMOTE,   // Utilise la télécommande
    STATE_IDLE      // Aucun signal
};

SystemState gSystemState = STATE_IDLE;

void setup() {
    Serial.begin(BAUD_RATE);
    leds_init();
    remote_init();
    modes_init();
    Serial.println("READY");
}

void loop() {
    if (buffer_check()) {
        if (gSystemState != STATE_SERIAL) {
            gSystemState = STATE_SERIAL;
            modes_init();
        }
        return;  // Continue à recevoir Serial
    }
    RemoteCode code = remote_read();
    if (code != REMOTE_NONE)
    {

        if (gSystemState != STATE_REMOTE) {
            gSystemState = STATE_REMOTE;
            modes_init();
        }

        switch (code) {
            case REMOTE_OFF:
                modes_toggle_animation();
                break;
            case REMOTE_BRIGHT_UP:
                modes_brightness_up();
                break;
            case REMOTE_BRIGHT_DOWN:
                modes_brightness_down();
                break;
            case REMOTE_NEXT_MODE:
                modes_next_mode();
                break;
            case REMOTE_PREV_COLOR:
                modes_set_color((ColorPalette)((gState.color - 1 + 9) % 9));
                break;
            case REMOTE_NEXT_COLOR:
                modes_next_color();
                break;
            case REMOTE_TOGGLE_ANIM:
                modes_toggle_animation();
                break;
            case REMOTE_SPEED_UP:
                modes_set_speed(min(255, gState.speed + 20));
                break;
            case REMOTE_SPEED_DOWN:
                modes_set_speed(max(0, gState.speed - 20));
                break;
            case REMOTE_MODE_1:
                Serial.println("Mode 1 selected");
                modes_set_mode(MODE_FIXED);
                break;
            case REMOTE_MODE_2:
                Serial.println("Mode 2 selected");
                modes_set_mode(MODE_RAINBOW);
                break;
            case REMOTE_MODE_3:
                Serial.println("Mode 3 selected");
                modes_set_mode(MODE_BREATHING);
                break;
            case REMOTE_MODE_4:
                Serial.println("Mode 4 selected");
                modes_set_mode(MODE_PULSE);
                break;
            case REMOTE_MODE_5:
                Serial.println("Mode 5 selected");
                modes_set_mode(MODE_FIRE);
                break;
            case REMOTE_MODE_6:
                Serial.println("Mode 6 selected");
                modes_set_mode(MODE_TWINKLE);
                break;
            case REMOTE_MODE_7:
                Serial.println("Mode 7 selected");
                modes_set_mode(MODE_CHASE);
                break;
            case REMOTE_MODE_8:
                Serial.println("Mode 8 selected");
                modes_set_mode(MODE_WAVE);
                break;
            case REMOTE_MODE_9:
                Serial.println("Mode 9 selected");
                modes_set_mode(MODE_AURORA);
                break;
            default:
                break;
        }
        log_mode_state();
        modes_update();
    }
    else if (gSystemState == STATE_REMOTE)
    {
        // Continuer à mettre à jour l'animation si on est en mode remote
        modes_update();
    }
}