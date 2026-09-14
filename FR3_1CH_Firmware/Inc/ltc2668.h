#ifndef LTC2668_H
#define LTC2668_H

#include <stdbool.h>
#include <stdint.h>

/* Configures both used channels (VOUT2/CH1_I_DC, VOUT0/CH1_Q_DC) to the
 * +-2.5V bipolar span explicitly, regardless of the chip's POR default. */
void LTC2668_Init(void);

/* Sets CH1_I_DC (VOUT2) to volts, software-limited to +-0.5V even though
 * the DAC hardware span is +-2.5V. Returns false if volts is outside that
 * software limit (no SPI traffic in that case). */
bool LTC2668_SetVoltageI(double volts);

/* Sets CH1_Q_DC (VOUT0) to volts, same +-0.5V software limit. */
bool LTC2668_SetVoltageQ(double volts);

double LTC2668_GetVoltageI(void);
double LTC2668_GetVoltageQ(void);

#endif /* LTC2668_H */
