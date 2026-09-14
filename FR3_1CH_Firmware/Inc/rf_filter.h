#ifndef RF_FILTER_H
#define RF_FILTER_H

#include <stdint.h>

/* Drives an AM3153 filter's 6 control lines from value's low 6 bits, MSB
 * to LSB: VA VB V3 V2 V1 V0. See the AM3153 datasheet's state table for
 * what each combination selects.
 *
 * Safe to call unconditionally: a no-op on boards where BOARD_HAS_RF_FILTERS
 * is 0 - see board_config.h's warning (those pins are grounded on rev 1.1). */
void RFFilter_SetTx(uint8_t value);

/* Same as RFFilter_SetTx(), for the RX-side filter. */
void RFFilter_SetRx(uint8_t value);

/* Reads back the TX-side filter's current control-line state, reconstructed
 * from the live GPIO pin levels, in the same bit layout as RFFilter_SetTx().
 * Returns 0 on boards without BOARD_HAS_RF_FILTERS. */
uint8_t RFFilter_GetTx(void);

/* Same as RFFilter_GetTx(), for the RX-side filter. */
uint8_t RFFilter_GetRx(void);

#endif /* RF_FILTER_H */
