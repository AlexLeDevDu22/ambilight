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

// Touches physiques de la télécommande
enum RemoteButton {
    BTN_NONE = 0,
    BTN_POWER, BTN_VOL_UP, BTN_VOL_DOWN, BTN_FUNC, BTN_EQ, BTN_ST,
    BTN_PREV, BTN_PLAY, BTN_NEXT, BTN_UP, BTN_DOWN,
    BTN_0, BTN_1, BTN_2, BTN_3, BTN_4, BTN_5, BTN_6, BTN_7, BTN_8, BTN_9
};

struct RemoteEvent {
    RemoteButton button;
    bool repeat;          // touche maintenue (trame de répétition NEC)
    unsigned long raw;    // code brut (utile pour une touche inconnue)
};

void remote_init();
RemoteEvent remote_read();
const char *remote_name(RemoteButton b);   // nom envoyé au serveur ("POWER", "VOL_UP"…)
void remote_wait_idle(uint16_t max_ms);    // attend la fin d'une trame IR en cours

#endif
