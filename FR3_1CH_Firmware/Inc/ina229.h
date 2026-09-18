#ifndef INA229_H
#define INA229_H

#include <stdbool.h>
#include <stdint.h>

/* This chip is write-only from firmware's perspective: the INA229's SDO
 * runs at 5V0 (its VS pin is tied to USB_VBUS), and would damage the
 * STM32/LMX2820 if it shared the SPI4 MISO net at that voltage - so the
 * series resistor connecting its SDO to the shared MISO line has been
 * depopulated on the PCB, permanently isolating it. That means VBUS,
 * current, and alarm status can never be read back; only configuration
 * (this function) and clearing alarms are possible. See the
 * fr3-1ch-ina229-5v-sdo-cannot-share-3v3-miso note for the full story -
 * don't add a register-read function here without a hardware fix first. */

/* Resets the chip and writes CONFIG/ADC_CONFIG/SHUNT_CAL/SOVL/BOVL/BUVL/
 * DIAG_ALRT (alarm enables, latched - see INA229_ClearAlarms()), via
 * INA229_ClearAlarms(). Called once at boot, after the power rails are up
 * (performs no rail-settling delay of its own - the rails must already be
 * stable) and before LMX2820 programming, per the board's power-up
 * sequencing. Blind writes only - there is no way to confirm the chip
 * received them. */
void INA229_Init(void);

/* Alerts are configured latched (ALATCH=1) and active-high (APOL=1 - see
 * ina229.c for why the default active-low polarity has it backwards on
 * this board's inverting BSS138 FET/LED stage): once an alarm trips, the
 * ALARM LED (wired to the INA229's ALERT pin - the STM32 itself never
 * reads that pin; its 5V signal level was judged unsafe) lights and stays
 * lit even after the fault condition clears, so a transient fault doesn't
 * go unnoticed. TI's documented way to clear a latched DIAG_ALRT is to
 * read it, which is impossible here (see the file-level comment above) -
 * so this instead writes CONFIG's RST bit (a full, self-clearing chip
 * reset) and then re-applies the entire configuration (APOL included,
 * since a reset wipes SHUNT_CAL/thresholds/DIAG_ALRT back to POR
 * defaults), which should turn the LED back off if there's no longer a
 * real fault. Also used internally by INA229_Init(). All writes - no way
 * to confirm the chip received them or that the LED actually went out. */
void INA229_ClearAlarms(void);

#endif /* INA229_H */
