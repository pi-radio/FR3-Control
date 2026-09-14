#ifndef SETTINGS_H
#define SETTINGS_H

#include <stdint.h>

/* Loads persisted settings from EDATA flash (if present) and applies them
 * to hardware (LMX2820, LTC2668, clock/LO/IQ GPIOs); otherwise leaves each
 * driver's own Init() defaults.
 *
 * First boot after flashing also enables EDATA via a one-time option-byte
 * write, triggering an automatic MCU reset mid-call - happens once per
 * chip, ever.
 *
 * Call once at startup, after LMX2820_Init()/LTC2668_Init(). */
void Settings_Init(void);

/* Captures the current live state of every persisted parameter and writes
 * it to the EDATA region (erasing and reprogramming the whole settings
 * blob each time). Call this after any command that changes a persisted
 * parameter, so the change survives a power cycle. */
void Settings_Save(void);

/* Board serial: set once at the factory via "SET BOARD SERIAL", persists
   like every other setting. Present on every board, defaults to 0. */
uint32_t Settings_GetBoardSerial(void);
void Settings_SetBoardSerial(uint32_t serial);

#endif /* SETTINGS_H */
