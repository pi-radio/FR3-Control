#ifndef LO_CONTROL_H
#define LO_CONTROL_H

#include <stdbool.h>
#include <stdint.h>

/* LO control added in firmware 1.4.1 (FR3 1CH rev 1.4 only, BOARD_HAS_LO_CONTROL):
 *
 * 1. LMX2820 drive rule. In AUTO mode (the default) every tune sets OUTA_PWR from the LO
 *    frequency: 0 for LO <= 13 GHz, 2 for 13 < LO < 20 GHz, 4 for LO >= 20 GHz (the rule the
 *    datasheet was measured with). "LMX PWR n" switches to MANUAL until "LMX PWR AUTO".
 *
 * 2. Per-unit TX LO-null calibration. A table of I_V/Q_V bias pairs on a 100 MHz LO grid
 *    (7.0-22.5 GHz, 156 points), measured at two temperatures (cold and hot), each pair stored
 *    with the LMX2820 die temperature it was measured at. It lives in its own flash sector
 *    (bank 2, sector 1), separate from the settings blob, so ordinary setting saves never
 *    touch it. In AUTO bias mode (the default) the bias is looked up and interpolated on every
 *    tune and re-applied every 2 s as the die temperature changes - see LoControl_ComputeBias().
 *    "SET I_V"/"SET Q_V" switch to MANUAL until "IQBIAS AUTO". The auto bias pauses while the
 *    LO is external or the LMX2820 is muted (the frequency is then unknown / the sensor unused).
 *
 * All board hardware access from the USB command thread and from the 2 s bias thread is
 * serialized by LoControl_Lock()/LoControl_Unlock() (the LMX2820, LTC2668 and INA229 share
 * SPI4). */

#define LOCAL_N_POINTS        156U
#define LOCAL_F_START_HZ      7000000000ULL
#define LOCAL_F_STEP_HZ       100000000ULL
#define LOCAL_TEMP_COLD       0U
#define LOCAL_TEMP_HOT        1U

/* Called once at boot, before Settings_Init(): loads (and CRC-checks) the stored table. */
void LoControl_Init(void);

/* Creates the 2 s bias thread and the hardware lock. Called from App_ThreadX_Init(). */
unsigned int LoControl_ThreadCreate(void);

void LoControl_Lock(void);
void LoControl_Unlock(void);

/* ---- drive rule ---- */
uint8_t LoControl_DriveFor(uint64_t lo_hz);
bool LoControl_GetPowerAuto(void);
void LoControl_SetPowerAuto(bool on);
/* AUTO: sets OUTA_PWR for lo_hz before a tune (MANUAL: no-op). */
void LoControl_ApplyDriveFor(uint64_t lo_hz);

/* ---- LO-null bias ---- */
bool LoControl_GetBiasAuto(void);
void LoControl_SetBiasAuto(bool on);
bool LoControl_TableValid(void);
/* AUTO + valid table + internal LO + not muted: reads the die temperature, computes and applies
 * the bias. Returns true if a bias was applied. Never writes flash. */
bool LoControl_ApplyBiasNow(void);
/* Bias for lo_hz at temp_c from the active table; false if no valid table. */
bool LoControl_ComputeBias(uint64_t lo_hz, double temp_c, double *i_v, double *q_v);
/* Last bias applied by the auto mode and the temperature it was computed for. */
void LoControl_GetLastApplied(double *i_v, double *q_v, double *temp_c, bool *valid);

/* ---- calibration upload / readback (staging copy in RAM; COMMIT writes flash) ---- */
void LoControl_StageClear(void);
bool LoControl_StageEntry(unsigned idx, unsigned which, double i_v, double q_v, double temp_c);
void LoControl_StageDate(uint32_t yyyymmdd);
/* Returns NULL on success, else a short reason ("INCOMPLETE", "FLASH", "VERIFY"). */
const char *LoControl_Commit(uint32_t board_serial);
bool LoControl_GetEntry(unsigned idx, unsigned which, double *i_v, double *q_v, double *temp_c);
unsigned LoControl_StagedCount(void);
/* Active table summary for CAL INFO? / CAL TEMPS?. */
bool LoControl_GetInfo(unsigned *n_valid, unsigned *fmt, uint32_t *serial, uint32_t *date, bool *crc_ok);
bool LoControl_GetTempRange(unsigned which, double *t_min, double *t_max);

#endif /* LO_CONTROL_H */
