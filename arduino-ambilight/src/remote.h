
#ifndef REMOTE_H
#define REMOTE_H
#include <Arduino.h>


#define RECV_PIN 7

// Codes IR Elegoo 21-button remote (NEC protocol)
#define REMOTE_POWER    0xBA45FF00
#define REMOTE_VOL_UP   0xB946FF00
#define REMOTE_VOL_DOWN 0xEA15FF00
#define REMOTE_FUNC     0xB847FF00
#define REMOTE_PREV     0xBB44FF00   // |<<
#define REMOTE_PLAY     0xBF40FF00   // Play/Pause
#define REMOTE_NEXT     0xBC43FF00   // >>|
#define REMOTE_DOWN     0xF807FF00   // ↓
#define REMOTE_EQ       0xE619FF00
#define REMOTE_UP       0xF609FF00   // ↑
#define REMOTE_0        0xE916FF00
#define REMOTE_1        0xF30CFF00
#define REMOTE_2        0xE718FF00
#define REMOTE_3        0xA15EFF00
#define REMOTE_4        0xF708FF00
#define REMOTE_5        0xE31CFF00
#define REMOTE_6        0xA55AFF00
#define REMOTE_7        0xBD42FF00
#define REMOTE_8        0xAD52FF00
#define REMOTE_9        0xB54AFF00
#define REMOTE_ST       0xF20DFF00

enum RemoteCode {
    REMOTE_NONE = 0,
    REMOTE_OFF,
    REMOTE_ON,
    REMOTE_BRIGHT_UP,
    REMOTE_BRIGHT_DOWN,
    REMOTE_NEXT_MODE,
    REMOTE_PREV_COLOR,
    REMOTE_NEXT_COLOR,
    REMOTE_TOGGLE_ANIM,
    REMOTE_SPEED_DOWN,
    REMOTE_SPEED_UP,
    REMOTE_MODE_1,
    REMOTE_MODE_2,
    REMOTE_MODE_3,
    REMOTE_MODE_4,
    REMOTE_MODE_5,
    REMOTE_MODE_6,
    REMOTE_MODE_7,
    REMOTE_MODE_8,
    REMOTE_MODE_9
};

void remote_init();
RemoteCode remote_read();

#endif
