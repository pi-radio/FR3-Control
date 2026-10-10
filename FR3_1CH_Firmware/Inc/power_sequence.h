#ifndef POWER_SEQUENCE_H
#define POWER_SEQUENCE_H

#include <stdbool.h>

/* Brings up the board's power tree in order - INRUSH_EN, BUCK_EN_5V3,
 * BUCK_EN_3V7 - with a 10ms settle delay between steps. Call once at
 * boot, before anything depending on the downstream rails (LMX2820,
 * LTC2668, RF filters).
 *
 * Safe to call unconditionally: a no-op on boards where
 * BOARD_HAS_POWER_SEQUENCING is 0 - see board_config.h's warning (those
 * pins are grounded on rev 1.1). */
void PowerSequence_Init(void);

/* Switches the internal 10 MHz TCXO (TCXO_EN_3V3) on or off - "SET LO EXT" turns it off,
 * "SET LO INT" back on (firmware 1.4.1). Turning it on waits 10 ms for it to settle. A no-op on
 * boards without power sequencing (the pin is grounded on rev 1.1). */
void PowerSequence_SetTcxo(bool on);

#endif /* POWER_SEQUENCE_H */
