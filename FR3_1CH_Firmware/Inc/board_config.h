#ifndef BOARD_CONFIG_H
#define BOARD_CONFIG_H

/* Board/revision is selected at compile time via a preprocessor symbol in
 * the build configuration (Project Properties > C/C++ Build > Settings >
 * MCU GCC Compiler > Preprocessor) - exactly one of:
 *   BOARD_FR3_1CH_REV1_1
 *   BOARD_FR3_1CH_REV1_4
 *   BOARD_OCTOLO_REV1_4
 *
 * OctoLO has its own revision line, independent of FR3 1CH's. Add
 * BOARD_OCTOLO_REVx_x blocks here as later revisions appear.
 *
 * Each block defines the board's identity (used in *IDN?) and which
 * BOARD_HAS_* features it has - board_commands.c guards each
 * feature-specific command block accordingly, so unsupported commands
 * don't exist in that board's compiled binary. */

/* Reported in *IDN? as "FW<this>" (see BOARD_IDN_STRING). Shared by every
 * board variant - keep in sync with the GUI's own version
 * (fr3_gui/version.py) whenever either changes. */
#define FIRMWARE_VERSION "1.00"

#if defined(BOARD_FR3_1CH_REV1_1)

#define BOARD_NAME                  "FR3 1CH"
#define BOARD_REVISION              "1.1"
#define BOARD_HAS_LMX2820           1
#define BOARD_HAS_LTC2668           1
#define BOARD_HAS_CLOCK_SWITCH      1
#define BOARD_HAS_IQ_SWAP           1
#define BOARD_HAS_LO_SWITCH         1
#define BOARD_HAS_POWER_SEQUENCING  0
#define BOARD_HAS_RF_FILTERS        0
#define BOARD_HAS_INA229            0

/* CRITICAL - DO NOT REMOVE THIS WARNING: on this specific revision, the
 * STM32 pins used by rev 1.4 for power-sequencing (INRUSH_EN, BUCK_EN_5V3,
 * BUCK_EN_3V7) and both AM3153 RF filters' control lines (PD8, PA0, PA1,
 * PB4-PB9, PD9-PD14) are all hard-wired directly to GND on this board.
 * Driving any of them to a logic HIGH would force the GPIO driver to sink
 * a large current straight into the GND plane, thermally destroying the
 * MCU. This is exactly why BOARD_HAS_POWER_SEQUENCING and
 * BOARD_HAS_RF_FILTERS must both stay 0 here, and why power_sequence.c/
 * rf_filter.c must never drive those pins when built for this board. */

#elif defined(BOARD_FR3_1CH_REV1_4)

#define BOARD_NAME                  "FR3 1CH"
#define BOARD_REVISION              "1.4"
#define BOARD_HAS_LMX2820           1
#define BOARD_HAS_LTC2668           1
#define BOARD_HAS_CLOCK_SWITCH      1
#define BOARD_HAS_IQ_SWAP           1
#define BOARD_HAS_LO_SWITCH         1
#define BOARD_HAS_POWER_SEQUENCING  1
#define BOARD_HAS_RF_FILTERS        1
#define BOARD_HAS_INA229            1

#elif defined(BOARD_OCTOLO_REV1_4)

/* OctoLO rev 1.4: has an LMX2820, no LTC2668, no CLK_SEL/LO_CTRL GPIOs.
 * Exact pin assignments and power-sequencing GPIOs still unconfirmed -
 * don't add further OCTOLO_HAS_* assumptions without checking first. */
#define BOARD_NAME                  "OctoLO"
#define BOARD_REVISION              "1.4"
#define BOARD_HAS_LMX2820           1
#define BOARD_HAS_LTC2668           0
#define BOARD_HAS_CLOCK_SWITCH      0
#define BOARD_HAS_IQ_SWAP           0
#define BOARD_HAS_LO_SWITCH         0
#define BOARD_HAS_POWER_SEQUENCING  1
#define BOARD_HAS_RF_FILTERS        0
#define BOARD_HAS_INA229            0

#else
#error "No board selected - define BOARD_FR3_1CH_REV1_1, BOARD_FR3_1CH_REV1_4, or BOARD_OCTOLO_REV1_4 in this build configuration's preprocessor symbols."
#endif

#endif /* BOARD_CONFIG_H */
