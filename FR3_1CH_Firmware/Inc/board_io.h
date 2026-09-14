#ifndef BOARD_IO_H
#define BOARD_IO_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define BOARD_IO_TEST_POINT_COUNT  2U

uint8_t BoardIO_IsValidTestPoint(uint32_t index);
void BoardIO_SetTestPoint(uint32_t index, uint8_t state);
uint8_t BoardIO_GetTestPoint(uint32_t index);

#ifdef __cplusplus
}
#endif

#endif /* BOARD_IO_H */
