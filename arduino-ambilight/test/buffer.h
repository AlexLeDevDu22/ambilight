#ifndef BUFFER_H
#define BUFFER_H

#include "leds.h"

#define RECEIVE_TIMEOUT 2000

bool buffer_check();
bool buffer_has_data();

#endif
