#include "ina229.h"
#include "main.h"
#include "spi.h"

/* Register addresses (TI INA229 register map). Write-only chip on this
 * board (see ina229.h) - only the registers we ever write are listed. */
#define INA229_REG_CONFIG      0x00U  /* 16-bit */
#define INA229_REG_ADC_CONFIG  0x01U  /* 16-bit */
#define INA229_REG_SHUNT_CAL   0x02U  /* 16-bit */
#define INA229_REG_DIAG_ALRT   0x0BU  /* 16-bit */
#define INA229_REG_SOVL        0x0CU  /* 16-bit */
#define INA229_REG_SUVL        0x0DU  /* 16-bit */
#define INA229_REG_BOVL        0x0EU  /* 16-bit */
#define INA229_REG_BUVL        0x0FU  /* 16-bit */

/* CONFIG.RST (bit 15): full system reset, self-clearing, resets every
 * register to its POR default - including SHUNT_CAL/thresholds/DIAG_ALRT,
 * not just the alert latch. This is the only way to clear a latched
 * DIAG_ALRT alert on this board: TI documents the normal clear mechanism
 * as "reading DIAG_ALRT resets the ALERT pin," but this chip's SDO is
 * physically disconnected here (see ina229.h) so no read is possible -
 * RST is a write-only operation that clears the latch unambiguously by
 * resetting the whole device, at the cost of needing a full
 * reconfigure afterward. */
#define INA229_CONFIG_RST_BIT       0x8000U

/* CONFIG.ADCRANGE (bit 4): 0 = +-163.84mV shunt full scale, 1 = +-40.96mV.
 * 1.8A (our over-current threshold) * 20mOhm = 36mV, which only fits the
 * narrower range - use it for the better resolution it buys us there. */
#define INA229_CONFIG_ADCRANGE_BIT  0x0010U

/* ADC_CONFIG.MODE = 0xF (continuous bus voltage + shunt voltage +
 * temperature), in bits [15:12]. VBUSCT/VSHCT/VTCT = 4 (1052us each, the
 * datasheet's own POR default conversion time), AVG = 0 (no averaging) -
 * none of this is dictated by the board's requirements, just reasonable
 * general-purpose defaults. Conversions still run continuously even
 * though nothing on this board can ever read the result (see ina229.h) -
 * harmless, and cheap insurance if SDO is ever reconnected via a proper
 * level shifter later. */
#define INA229_ADC_CONFIG_VALUE  0xFDB6U

/* DIAG_ALRT bit positions (also the alarm ENABLE bits when written). */
#define INA229_DIAG_BIT_BUL     0x0008U  /* Bus under-limit */
#define INA229_DIAG_BIT_BOL     0x0010U  /* Bus over-limit */
#define INA229_DIAG_BIT_SOL     0x0040U  /* Shunt (current) over-limit */
#define INA229_DIAG_BIT_APOL    0x1000U  /* Alert pin polarity: 1 = active-high */
#define INA229_DIAG_BIT_ALATCH  0x8000U  /* Latch alerts instead of transparent */

/* Enable SOL/BOL/BUL only - SUVL (undercurrent) and TMPOL (over-temp)
 * left disabled per board requirements. ALATCH set: once tripped, the
 * ALARM LED stays lit until explicitly cleared, rather than self-clearing
 * the instant the fault condition goes away - the whole point being that
 * a transient fault stays visible on the LED for the operator to notice.
 *
 * APOL set (active-high): the ALARM/ALERT net feeds a BSS138 N-channel
 * FET gate (LED between 3V3 and the FET's drain, source to GND) - an
 * inverting stage. ALERT is open-drain and can only pull low or release
 * (10k pull-up to 5V provides the released/high level); with the default
 * APOL=0, "no alarm" idles the net released/high, which turns the FET ON
 * and lights the LED - i.e. default polarity shows the LED lit during
 * *normal* operation and OFF during a real alarm, backwards from what an
 * "ALARM LED" should do. APOL=1 inverts it: idle drives the net low (FET
 * off, LED off), alarm releases it high (FET on, LED on) - matching the
 * intended behavior of lighting up only when there's actually a fault,
 * and going off once INA229_ClearAlarms() succeeds. */
#define INA229_DIAG_ALRT_VALUE  (INA229_DIAG_BIT_SOL | INA229_DIAG_BIT_BOL | INA229_DIAG_BIT_BUL | INA229_DIAG_BIT_APOL | INA229_DIAG_BIT_ALATCH)

/* CURRENT_LSB = MaxExpectedCurrent / 2^19 (datasheet formula), for a 1.7A
 * max expected board current. */
#define INA229_CURRENT_LSB_A  (1.7 / 524288.0)

/* SHUNT_CAL = 13107.2e6 * CURRENT_LSB * RSHUNT, x4 because ADCRANGE=1
 * (datasheet requirement) - see INA229_CONFIG_ADCRANGE_BIT. RSHUNT=20mOhm.
 * 13107.2e6 * (1.7/524288) * 0.02 * 4 = 3400.064, rounds to 3400. */
#define INA229_SHUNT_CAL_VALUE  3400U

/* SOVL LSB = 1.25uV when ADCRANGE=1 (5uV when ADCRANGE=0) - 16x coarser
 * than VSHUNT's own 78.125nV/20nV LSB, same relationship BOVL/BUVL have to
 * VBUS (see below). Over-current threshold 1.8A * 20mOhm = 36000uV;
 * 36000 / 1.25 = 28800. */
#define INA229_SOVL_VALUE  28800U

/* BOVL/BUVL LSB = 3.125mV (fixed, independent of ADCRANGE) - confirmed
 * against a working INA229 SPI implementation, not just recalled from
 * memory, given how much this SPI driver work has been bitten by
 * mis-remembered register scaling elsewhere on this board. */
#define INA229_BOVL_VALUE  1760U  /* 5.5V * 1000 / 3.125 */
#define INA229_BUVL_VALUE  1440U  /* 4.5V * 1000 / 3.125 */

/* Conservative post-RST settling delay - not a datasheet-specified value
 * (no way to confirm it via readback on this board), just a small margin
 * before trusting the chip to accept the reconfiguration writes below. */
#define INA229_RESET_SETTLE_MS  1U

static void INA229_Select(void)
{
  HAL_GPIO_WritePin(SPI_INA_CSb_GPIO_Port, SPI_INA_CSb_Pin, GPIO_PIN_RESET);
}

static void INA229_Deselect(void)
{
  HAL_GPIO_WritePin(SPI_INA_CSb_GPIO_Port, SPI_INA_CSb_Pin, GPIO_PIN_SET);
}

/* Command byte per the INA229 SPI protocol: bits[7:2] = 6-bit register
 * address, bit 1 = reserved (0), bit 0 = R/nW (1 = read, 0 = write) - a
 * different framing than the LMX2820's (7-bit address + R/W as the MSB),
 * confirmed against a working community SPI implementation rather than
 * assumed by analogy to the LMX2820 driver next to it. rx is discarded -
 * the INA229's SDO is physically disconnected from this board's shared
 * MISO net (a depopulated series resistor), so there is nothing valid to
 * read back even for a write's echo. */
static void INA229_WriteRegister(uint8_t reg, uint16_t data)
{
  uint8_t tx[3];
  uint8_t rx[3];

  tx[0] = (uint8_t)((reg << 2) & 0xFCU);
  tx[1] = (uint8_t)(data >> 8);
  tx[2] = (uint8_t)(data & 0xFFU);

  INA229_Select();
  HAL_SPI_TransmitReceive(&hspi4, tx, rx, 3U, HAL_MAX_DELAY);
  INA229_Deselect();
}

/* Full known-good configuration - CONFIG/ADC_CONFIG/SHUNT_CAL/thresholds/
 * DIAG_ALRT. Used both at boot and after a reset, since a reset wipes all
 * of these back to POR defaults, not just the alert latch. */
static void INA229_Configure(void)
{
  INA229_WriteRegister(INA229_REG_CONFIG, INA229_CONFIG_ADCRANGE_BIT);
  INA229_WriteRegister(INA229_REG_ADC_CONFIG, INA229_ADC_CONFIG_VALUE);
  INA229_WriteRegister(INA229_REG_SHUNT_CAL, INA229_SHUNT_CAL_VALUE);
  INA229_WriteRegister(INA229_REG_SOVL, INA229_SOVL_VALUE);
  INA229_WriteRegister(INA229_REG_SUVL, 0U);
  INA229_WriteRegister(INA229_REG_BOVL, INA229_BOVL_VALUE);
  INA229_WriteRegister(INA229_REG_BUVL, INA229_BUVL_VALUE);
  INA229_WriteRegister(INA229_REG_DIAG_ALRT, INA229_DIAG_ALRT_VALUE);
}

void INA229_Init(void)
{
  INA229_Deselect();

  /* Reset unconditionally, even though the chip should already be at POR
   * defaults after a cold board power-up: if only the STM32 has reset
   * (reflash, watchdog, etc.) without the INA229 losing power, it could
   * still be holding a latched alarm from before this boot. */
  INA229_ClearAlarms();
}

void INA229_ClearAlarms(void)
{
  INA229_WriteRegister(INA229_REG_CONFIG, INA229_CONFIG_RST_BIT);
  HAL_Delay(INA229_RESET_SETTLE_MS);
  INA229_Configure();
}
