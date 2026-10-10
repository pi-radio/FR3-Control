#ifndef SETTINGS_H
#define SETTINGS_H

#include <stdbool.h>
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

/* Call this after any command that changes a persisted parameter, so the
 * change survives a power cycle. Writes the live state to flash via
 * Settings_SaveNow() while persistence is enabled (the boot default, see
 * Settings_SetPersist()); does nothing while it is disabled. */
void Settings_Save(void);

/* Captures the current live state of every persisted parameter and writes
 * it to the EDATA region (erasing and reprogramming the whole settings
 * blob each time), regardless of the persistence setting. Used directly
 * where a write must never be skipped (first-boot init, "SET BOARD
 * SERIAL", re-enabling persistence). */
void Settings_SaveNow(void);

/* Runtime persistence switch, for automated characterization sweeps that
 * issue thousands of setting changes and would otherwise wear out flash.
 * Always ON after any reset (never itself stored in flash), so a power
 * cycle restores normal behavior. While OFF, Settings_Save() is a no-op and
 * the live state is not written to flash. Turning it back ON immediately
 * writes the current live state, so whenever persistence is ON the flash
 * mirrors the live state. */
void Settings_SetPersist(bool enable);
bool Settings_GetPersist(void);

/* Board serial: set once at the factory via "SET BOARD SERIAL", persists
   like every other setting. Present on every board, defaults to 0. */
uint32_t Settings_GetBoardSerial(void);
void Settings_SetBoardSerial(uint32_t serial);

#endif /* SETTINGS_H */
