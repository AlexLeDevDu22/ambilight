#ifndef BUFFER_H
#define BUFFER_H

#include "leds.h"

#define RECEIVE_TIMEOUT 2000

// Paquets reçus du serveur :
//   0xAA 0xBB | uint16_le n | RGB * n   → trame LED (réponse "OK")
//   0xAA 0xCC 0x00 0x00                 → ping : le serveur est là
enum PacketType {
    PACKET_NONE = 0,
    PACKET_FRAME,
    PACKET_PING
};

PacketType buffer_check();
bool buffer_has_data();

#endif
