#include "remote.h"
#include <IRremote.hpp>

void remote_init() {
    IrReceiver.begin(RECV_PIN);
}

RemoteCode remote_read() {
    if (!IrReceiver.decode()) return REMOTE_NONE;
    
    auto &code = IrReceiver.decodedIRData;
    unsigned long val = code.decodedRawData ? code.decodedRawData : code.command;
    IrReceiver.resume();
    
    String codeStr = String(val, HEX);
    if (val != 0)
        Serial.println("Received IR code: " + codeStr);
    

        // Buttons
    if (val == REMOTE_POWER)   return REMOTE_OFF;
    if (val == REMOTE_VOL_UP)  return REMOTE_BRIGHT_UP;
    if (val == REMOTE_VOL_DOWN) return REMOTE_BRIGHT_DOWN;
    if (val == REMOTE_FUNC)    return REMOTE_NEXT_MODE;
    if (val == REMOTE_PREV)    return REMOTE_PREV_COLOR;
    if (val == REMOTE_NEXT)    return REMOTE_NEXT_COLOR;
    if (val == REMOTE_PLAY)    return REMOTE_TOGGLE_ANIM;
    if (val == REMOTE_UP)      return REMOTE_SPEED_UP;
    if (val == REMOTE_DOWN)    return REMOTE_SPEED_DOWN;
    if (val == REMOTE_1)       return REMOTE_MODE_1;
    if (val == REMOTE_2)       return REMOTE_MODE_2;
    if (val == REMOTE_3)       return REMOTE_MODE_3;
    if (val == REMOTE_4)       return REMOTE_MODE_4;
    if (val == REMOTE_5)       return REMOTE_MODE_5;
    if (val == REMOTE_6)       return REMOTE_MODE_6;
    if (val == REMOTE_7)       return REMOTE_MODE_7;
    if (val == REMOTE_8)       return REMOTE_MODE_8;
    if (val == REMOTE_9)       return REMOTE_MODE_9;
    
    return REMOTE_NONE;
}
