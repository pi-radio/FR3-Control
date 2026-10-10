#ifndef LMX2820_H
#define LMX2820_H

#include <stdbool.h>
#include <stdint.h>

/* Sets software-side defaults only - no SPI traffic. Actual hardware state
 * is established by the first LMX2820_Tune()/SetPower()/SetMute() call,
 * whether that comes from a serial command or from the persistence layer
 * restoring saved settings at boot. */
void LMX2820_Init(void);

/* Computes every register for freq_hz and writes all 123 (R122 down to R0)
 * over SPI4, then polls lock-detect for a short window. Returns true if
 * locked before timeout. freq_hz range: 6,000,000,000-22,600,000,000
 * inclusive. */
bool LMX2820_Tune(uint64_t freq_hz);

/* Single-register write (R79) to change OUTA_PWR (0-7) without touching
 * frequency or mute state. */
void LMX2820_SetPower(uint8_t power);

/* mute=true: full powerdown (R0 POWERDOWN, not just OUTA_PD) - avoids RF
 * leakage but needs a full re-init to come back. mute=false: retunes to
 * the last frequency via the same full cold-boot procedure as
 * LMX2820_Tune(), returning true if locked. Muting itself is instant and
 * always returns true. */
bool LMX2820_SetMute(bool mute);

uint64_t LMX2820_GetFrequency(void);
uint8_t LMX2820_GetPower(void);
bool LMX2820_GetMuted(void);

typedef enum
{
  LMX2820_LOCK_UNLOCKED = 0,
  LMX2820_LOCK_LOCKED,
  LMX2820_LOCK_INVALID
} LMX2820_LockStatus_t;

/* Fresh SPI readback of R74's rb_LD field, decoded into
 * UNLOCKED(00/01)/LOCKED(10)/INVALID(11). Fresh read every call; unlike
 * LMX2820_Tune()'s internal poll, does not retry/wait. */
LMX2820_LockStatus_t LMX2820_GetLockStatus(void);

/* Raw single-register SPI readback (0-122), for bring-up/debug via a
 * serial command rather than a live debugger session. */
uint16_t LMX2820_ReadRegisterRaw(uint8_t addr);

/* Raw single-register SPI write (0-122), debug sessions only. Bypasses the
 * firmware's frequency/mute bookkeeping (LMX FREQ? goes stale) and is not
 * persisted; the next LMX2820_Tune() or unmute rewrites all 123 registers. */
void LMX2820_WriteRegisterRaw(uint8_t addr, uint16_t data);

/* Die temperature via R76's rb_TEMP_SENS field (TEMPSENSE_EN is enabled
 * permanently in the register template - see lmx2820.c). Per datasheet:
 * +-5C accuracy, 0.6C/code resolution - treat as approximate, not precise
 * (TI's own E2E forum has an open question on the exact conversion). */
double LMX2820_GetTemperatureC(void);

/* Microseconds spent writing all 123 registers in the most recent
 * LMX2820_Tune() call (DWT cycle counter) - excludes the lock-detect poll. */
uint32_t LMX2820_GetLastTuneWriteDurationUs(void);

/* Per-phase breakdown of LMX2820_GetLastTuneWriteDurationUs(): CS assert,
 * SPI transfer, CS release, summed across all 123 writes. Diagnostic only. */
uint32_t LMX2820_GetLastTuneCsLowUs(void);
uint32_t LMX2820_GetLastTuneSpiUs(void);
uint32_t LMX2820_GetLastTuneCsHighUs(void);

#endif /* LMX2820_H */
