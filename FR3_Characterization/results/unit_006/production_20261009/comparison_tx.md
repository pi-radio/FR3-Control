# Unit #6 vs golden #5, TX production test (production_20261009)

Golden: Unit #5 datasheet data (TX tests hot, LMX ~80-85 C; T1 also against its cold calibration, 57-63 C).

## T1: LO leakage after the unit's own null (every usable filter setting)

| LO (GHz) | Unit temp (C) | Unit median / worst (dBm) | Unit: readings <= -20 dBm | Golden cold median / worst | Golden hot median / worst | Unit null I, Q (mV) | Golden cold null I, Q (mV) |
|---|---|---|---|---|---|---|---|
| 8 | 62.7 | −42.4 / −29.2 | 6 of 6 | −40.4 / −24.9 | −41.3 / −27.1 | 19.9, 61.3 | 20.5, 60.8 |
| 16 | 66.1 | −24.8 / −21.6 | 15 of 15 | −34.0 / −29.0 | −34.3 / −29.8 | -41.7, 38.3 | -48.1, 36.4 |
| 20 | 66.1 | −24.1 / −20.4 | 7 of 7 | −22.1 / −16.9 | −23.0 / −17.7 | -13.2, -2.2 | -28.9, -8.1 |

## T2: 2xLO after the unit's own null (every usable filter setting)

| LO (GHz) | Unit median / worst (dBm) | Golden (hot, 10.1) median / worst (dBm) |
|---|---|---|
| 8 | −31.8 / −24.2 | −40.8 / −21.3 |

## T3: conversion gain (500 MHz window average, dB)

| Sideband | FR1 / FR3 (GHz) | LO (GHz) | Filter | Unit gain | Golden | Unit - golden | Unit temp (C) |
|---|---|---|---|---|---|---|---|
| lower | 1 / 7 | 8 | bypass 0x00 | 48.4 | 47.8 | 0.6 | 64.4 |
| lower | 1 / 7 | 8 | optimal 0x30 | 42.1 | 41.4 | 0.7 | 64.4 |
| lower | 2 / 6 | 8 | bypass 0x00 | 39.3 | 38.8 | 0.5 | 65.3 |
| lower | 2 / 6 | 8 | optimal 0x30 | 32.5 | 31.7 | 0.8 | 65.3 |
| lower | 1 / 15 | 16 | bypass 0x00 | 44.8 | 44.3 | 0.5 | 64.4 |
| lower | 1 / 15 | 16 | optimal 0x15 | 35.6 | 34.7 | 0.9 | 64.4 |
| lower | 2 / 14 | 16 | bypass 0x00 | 34.9 | 34.0 | 0.9 | 64.4 |
| lower | 2 / 14 | 16 | optimal 0x14 | 27.0 | 26.1 | 0.9 | 64.4 |
| lower | 3.5 / 12.5 | 16 | bypass 0x00 | 33.0 | 33.6 | −0.7 | 65.3 |
| lower | 3.5 / 12.5 | 16 | optimal 0x1A | 23.4 | 23.2 | 0.2 | 65.3 |
| lower | 1 / 19 | 20 | bypass 0x00 | 39.8 | 42.1 | −2.3 | 66.1 |
| lower | 1 / 19 | 20 | optimal 0x1F | 30.3 | 32.1 | −1.8 | 66.1 |
| lower | 2 / 18 | 20 | bypass 0x00 | 34.0 | 34.2 | −0.2 | 66.1 |
| lower | 2 / 18 | 20 | optimal 0x1E | 21.9 | 23.1 | −1.2 | 66.1 |
| lower | 3.5 / 16.5 | 20 | bypass 0x00 | 32.8 | 33.5 | −0.7 | 66.1 |
| lower | 3.5 / 16.5 | 20 | optimal 0x1F | 24.6 | 24.4 | 0.2 | 66.1 |
| upper | 1 / 9 | 8 | bypass 0x00 | 49.6 | 48.6 | 1.0 | 63.6 |
| upper | 1 / 9 | 8 | optimal 0x3E | 44.5 | 43.7 | 0.8 | 63.6 |
| upper | 2 / 10 | 8 | bypass 0x00 | 38.7 | 38.1 | 0.6 | 65.3 |
| upper | 2 / 10 | 8 | optimal 0x3E | 35.0 | 34.2 | 0.7 | 65.3 |
| upper | 3.5 / 11.5 | 8 | bypass 0x00 | 35.2 | 35.5 | −0.4 | 65.3 |
| upper | 3.5 / 11.5 | 8 | optimal 0x3E | 30.9 | 31.3 | −0.4 | 65.3 |
| upper | 1 / 17 | 16 | bypass 0x00 | 44.2 | 44.4 | −0.2 | 63.6 |
| upper | 1 / 17 | 16 | optimal 0x24 | 33.7 | 33.6 | 0.2 | 63.6 |
| upper | 2 / 18 | 16 | bypass 0x00 | 35.0 | 35.6 | −0.6 | 63.6 |
| upper | 2 / 18 | 16 | optimal 0x27 | 22.6 | 23.4 | −0.8 | 63.6 |
| upper | 3.5 / 19.5 | 16 | bypass 0x00 | 26.0 | 28.9 | −2.9 | 64.4 |
| upper | 3.5 / 19.5 | 16 | optimal 0x27 | 19.3 | 21.5 | −2.2 | 64.4 |
| upper | 1 / 21 | 20 | bypass 0x00 | 39.9 | 40.2 | −0.4 | 65.3 |
| upper | 1 / 21 | 20 | optimal 0x2D | 33.0 | 33.3 | −0.3 | 65.3 |
| upper | 2 / 22 | 20 | bypass 0x00 | 32.3 | 32.4 | −0.1 | 66.1 |
| upper | 2 / 22 | 20 | optimal 0x2E | 26.8 | 26.4 | 0.4 | 66.1 |
| upper | 3.5 / 23.5 | 20 | bypass 0x00 | 31.1 | 29.7 | 1.5 | 66.1 |
| upper | 3.5 / 23.5 | 20 | optimal 0x2F | 25.9 | 23.5 | 2.4 | 66.1 |

Unit - golden, median (min to max): bypass −0.2 dB (−2.9 to 1.5); optimal 0.2 dB (−2.2 to 2.4)

## T4: RMS gain flatness (dB)

| Sideband | FR1 / FR3 (GHz) | LO (GHz) | Filter | Unit flatness | Golden | Unit - golden | Unit temp (C) |
|---|---|---|---|---|---|---|---|
| lower | 1 / 7 | 8 | bypass 0x00 | 0.9 | 0.7 | 0.1 | 64.4 |
| lower | 1 / 7 | 8 | optimal 0x30 | 0.5 | 0.4 | 0.0 | 64.4 |
| lower | 2 / 6 | 8 | bypass 0x00 | 1.9 | 1.8 | 0.1 | 65.3 |
| lower | 2 / 6 | 8 | optimal 0x30 | 2.1 | 2.3 | −0.2 | 65.3 |
| lower | 1 / 15 | 16 | bypass 0x00 | 0.5 | 0.4 | 0.1 | 63.6 |
| lower | 1 / 15 | 16 | optimal 0x15 | 0.5 | 0.4 | 0.1 | 63.6 |
| lower | 2 / 14 | 16 | bypass 0x00 | 1.4 | 1.6 | −0.2 | 64.4 |
| lower | 2 / 14 | 16 | optimal 0x14 | 0.9 | 0.9 | −0.0 | 64.4 |
| lower | 3.5 / 12.5 | 16 | bypass 0x00 | 1.9 | 1.9 | 0.0 | 65.3 |
| lower | 3.5 / 12.5 | 16 | optimal 0x1A | 2.7 | 2.8 | −0.1 | 65.3 |
| lower | 1 / 19 | 20 | bypass 0x00 | 0.6 | 0.4 | 0.2 | 65.3 |
| lower | 1 / 19 | 20 | optimal 0x1F | 0.6 | 0.4 | 0.2 | 65.3 |
| lower | 2 / 18 | 20 | bypass 0x00 | 2.2 | 2.1 | 0.1 | 66.1 |
| lower | 2 / 18 | 20 | optimal 0x1E | 1.1 | 1.3 | −0.2 | 66.1 |
| lower | 3.5 / 16.5 | 20 | bypass 0x00 | 1.5 | 1.9 | −0.4 | 66.1 |
| lower | 3.5 / 16.5 | 20 | optimal 0x1F | 2.0 | 2.1 | −0.2 | 66.1 |
| upper | 1 / 9 | 8 | bypass 0x00 | 0.3 | 0.2 | 0.1 | 63.6 |
| upper | 1 / 9 | 8 | optimal 0x3E | 0.2 | 0.2 | 0.0 | 63.6 |
| upper | 2 / 10 | 8 | bypass 0x00 | 1.7 | 1.7 | 0.0 | 65.3 |
| upper | 2 / 10 | 8 | optimal 0x3E | 1.6 | 1.6 | −0.0 | 65.3 |
| upper | 3.5 / 11.5 | 8 | bypass 0x00 | 2.3 | 2.5 | −0.1 | 65.3 |
| upper | 3.5 / 11.5 | 8 | optimal 0x3E | 2.8 | 3.0 | −0.2 | 65.3 |
| upper | 1 / 17 | 16 | bypass 0x00 | 1.2 | 1.2 | 0.0 | 63.6 |
| upper | 1 / 17 | 16 | optimal 0x24 | 1.1 | 0.9 | 0.2 | 63.6 |
| upper | 2 / 18 | 16 | bypass 0x00 | 1.4 | 1.9 | −0.4 | 63.6 |
| upper | 2 / 18 | 16 | optimal 0x27 | 1.5 | 1.7 | −0.3 | 63.6 |
| upper | 3.5 / 19.5 | 16 | bypass 0x00 | 2.6 | 3.0 | −0.4 | 63.6 |
| upper | 3.5 / 19.5 | 16 | optimal 0x27 | 2.7 | 2.6 | 0.0 | 63.6 |
| upper | 1 / 21 | 20 | bypass 0x00 | 0.5 | 0.6 | −0.2 | 65.3 |
| upper | 1 / 21 | 20 | optimal 0x2D | 0.5 | 0.8 | −0.3 | 65.3 |
| upper | 2 / 22 | 20 | bypass 0x00 | 1.1 | 1.8 | −0.7 | 66.1 |
| upper | 2 / 22 | 20 | optimal 0x2E | 0.9 | 1.5 | −0.7 | 66.1 |
| upper | 3.5 / 23.5 | 20 | bypass 0x00 | 3.0 | 2.3 | 0.7 | 66.1 |
| upper | 3.5 / 23.5 | 20 | optimal 0x2F | 3.1 | 2.4 | 0.7 | 66.1 |

Unit - golden, median (min to max): bypass 0.0 dB (−0.7 to 0.7); optimal −0.0 dB (−0.7 to 0.7)

## T5: sideband suppression (dB)

| Sideband | FR1 / FR3 (GHz) | LO (GHz) | Filter | Unit suppression | Golden | Unit - golden | Unit temp (C) |
|---|---|---|---|---|---|---|---|
| lower | 1 / 7 | 8 | bypass 0x00 | 19.0 | 20.7 | −1.8 | 65.3 |
| lower | 1 / 7 | 8 | optimal 0x30 | 39.4 | 39.3 | 0.1 | 65.3 |
| lower | 2 / 6 | 8 | bypass 0x00 | 10.5 | 10.9 | −0.4 | 65.3 |
| lower | 2 / 6 | 8 | optimal 0x30 | 65.2 | 56.9 | 8.3 | 65.3 |
| lower | 1 / 15 | 16 | bypass 0x00 | 18.6 | 19.0 | −0.3 | 64.4 |
| lower | 1 / 15 | 16 | optimal 0x15 | 37.8 | 35.8 | 2.0 | 64.4 |
| lower | 2 / 14 | 16 | bypass 0x00 | 8.4 | 7.5 | 0.9 | 63.6 |
| lower | 2 / 14 | 16 | optimal 0x14 | 55.6 | 47.4 | 8.2 | 63.6 |
| lower | 3.5 / 12.5 | 16 | bypass 0x00 | 23.1 | 20.1 | 3.0 | 65.3 |
| lower | 3.5 / 12.5 | 16 | optimal 0x1A | 48.9 | 50.8 | −1.9 | 65.3 |
| lower | 1 / 19 | 20 | bypass 0x00 | 21.5 | 24.6 | −3.1 | 66.1 |
| lower | 1 / 19 | 20 | optimal 0x1F | 31.1 | 32.8 | −1.7 | 66.1 |
| lower | 2 / 18 | 20 | bypass 0x00 | 10.7 | 10.8 | −0.1 | 66.1 |
| lower | 2 / 18 | 20 | optimal 0x1E | 34.6 | 50.1 | −15.5 | 66.1 |
| lower | 3.5 / 16.5 | 20 | bypass 0x00 | 14.8 | 16.3 | −1.6 | 66.1 |
| lower | 3.5 / 16.5 | 20 | optimal 0x1F | 49.5 | 57.1 | −7.6 | 66.1 |
| upper | 1 / 9 | 8 | bypass 0x00 | 16.0 | 15.9 | 0.1 | 63.6 |
| upper | 1 / 9 | 8 | optimal 0x3E | 55.4 | 51.5 | 3.9 | 63.6 |
| upper | 2 / 10 | 8 | bypass 0x00 | 17.1 | 15.0 | 2.1 | 65.3 |
| upper | 2 / 10 | 8 | optimal 0x3E | 56.0 | 66.2 | −10.2 | 65.3 |
| upper | 3.5 / 11.5 | 8 | bypass 0x00 | 19.7 | 21.4 | −1.7 | 65.3 |
| upper | 3.5 / 11.5 | 8 | optimal 0x3E | 57.6 | 66.0 | −8.4 | 65.3 |
| upper | 1 / 17 | 16 | bypass 0x00 | 20.5 | 22.5 | −2.1 | 63.6 |
| upper | 1 / 17 | 16 | optimal 0x24 | 38.2 | 45.2 | −6.9 | 63.6 |
| upper | 2 / 18 | 16 | bypass 0x00 | 14.1 | 15.8 | −1.8 | 64.4 |
| upper | 2 / 18 | 16 | optimal 0x27 | 43.0 | 50.8 | −7.8 | 64.4 |
| upper | 3.5 / 19.5 | 16 | bypass 0x00 | 3.1 | 5.4 | −2.3 | 64.4 |
| upper | 3.5 / 19.5 | 16 | optimal 0x27 | 48.0 | 63.9 | −15.9 | 64.4 |
| upper | 1 / 21 | 20 | bypass 0x00 | 17.1 | 15.9 | 1.3 | 65.3 |
| upper | 1 / 21 | 20 | optimal 0x2D | 32.2 | 35.4 | −3.1 | 65.3 |
| upper | 2 / 22 | 20 | bypass 0x00 | 9.9 | 10.2 | −0.2 | 66.1 |
| upper | 2 / 22 | 20 | optimal 0x2E | 68.4 | 46.4 | 22.0 | 66.1 |
| upper | 3.5 / 23.5 | 20 | bypass 0x00 | 6.3 | 4.3 | 2.0 | 66.1 |
| upper | 3.5 / 23.5 | 20 | optimal 0x2F | 50.8 | 43.0 | 7.8 | 66.1 |

Unit - golden, median (min to max): bypass −0.3 dB (−3.1 to 3.0); optimal −1.9 dB (−15.9 to 22.0)

## T6: compression

| Panel | Unit gain / out P1dB / out P3dB | Golden gain / out P1dB / out P3dB | Delta gain / P1dB / P3dB | Unit / golden temp (C) |
|---|---|---|---|---|
| upper 1 / 9 GHz | 44.3 / 18.2 / 18.7 | 43.5 / 18.2 / 18.7 | 0.7 / 0.0 / 0.0 | 62.7 / 79.7 |
| upper 2 / 22 GHz | 26.8 / 15.5 / 15.9 | 26.4 / 15.7 / 16.0 | 0.4 / −0.2 / −0.1 | 66.1 / 83.9 |
| lower 2 / 14 GHz | 25.7 / 15.8 / 16.1 | 24.8 / 15.8 / 16.2 | 0.9 / −0.0 / −0.1 | 66.9 / 83.9 |
