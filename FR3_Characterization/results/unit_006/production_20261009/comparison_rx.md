# Unit #6 vs golden #5, RX production test (production_20261009)

Golden: Unit #5 hot RX re-run of 2026-10-09 (LMX ~69-84 C). TX side in normal use with each unit's own nulls.

## R1: conversion gain (500 MHz window average, dB)

| LO side | FR1 / FR3 (GHz) | LO (GHz) | Filter | Unit gain | Golden | Unit - golden | Unit temp (C) |
|---|---|---|---|---|---|---|---|
| high | 1 / 7 | 8 | bypass 0x00 | 57.9 | 57.5 | 0.3 | 64.4 |
| high | 1 / 7 | 8 | optimal 0x30 | 51.2 | 50.8 | 0.4 | 64.4 |
| high | 2 / 6 | 8 | bypass 0x00 | 47.5 | 47.3 | 0.2 | 65.3 |
| high | 2 / 6 | 8 | optimal 0x30 | 41.3 | 40.8 | 0.5 | 65.3 |
| high | 1 / 15 | 16 | bypass 0x00 | 51.3 | 53.3 | −2.0 | 64.4 |
| high | 1 / 15 | 16 | optimal 0x15 | 43.7 | 43.5 | 0.2 | 64.4 |
| high | 2 / 14 | 16 | bypass 0x00 | 47.2 | 46.7 | 0.5 | 64.4 |
| high | 2 / 14 | 16 | optimal 0x14 | 38.5 | 38.4 | 0.1 | 64.4 |
| high | 3.5 / 12.5 | 16 | bypass 0x00 | 42.1 | 42.7 | −0.6 | 65.3 |
| high | 3.5 / 12.5 | 16 | optimal 0x1A | 34.1 | 33.4 | 0.7 | 65.3 |
| high | 1 / 19 | 20 | bypass 0x00 | 49.8 | 49.8 | −0.0 | 66.1 |
| high | 1 / 19 | 20 | optimal 0x1F | 41.3 | 41.6 | −0.2 | 66.1 |
| high | 2 / 18 | 20 | bypass 0x00 | 46.7 | 46.1 | 0.6 | 66.1 |
| high | 2 / 18 | 20 | optimal 0x1E | 36.9 | 36.2 | 0.7 | 66.1 |
| high | 3.5 / 16.5 | 20 | bypass 0x00 | 40.2 | 40.2 | 0.1 | 66.1 |
| high | 3.5 / 16.5 | 20 | optimal 0x1F | 34.7 | 34.2 | 0.5 | 66.1 |
| low | 1 / 9 | 8 | bypass 0x00 | 55.2 | 54.8 | 0.4 | 63.6 |
| low | 1 / 9 | 8 | optimal 0x3E | 52.7 | 52.3 | 0.3 | 63.6 |
| low | 2 / 10 | 8 | bypass 0x00 | 49.9 | 49.8 | 0.1 | 64.4 |
| low | 2 / 10 | 8 | optimal 0x3E | 46.4 | 46.0 | 0.4 | 64.4 |
| low | 3.5 / 11.5 | 8 | bypass 0x00 | 42.6 | 45.2 | −2.6 | 65.3 |
| low | 3.5 / 11.5 | 8 | optimal 0x3E | 39.0 | 38.9 | 0.1 | 65.3 |
| low | 1 / 17 | 16 | bypass 0x00 | 53.5 | 53.1 | 0.4 | 63.6 |
| low | 1 / 17 | 16 | optimal 0x24 | 43.2 | 42.1 | 1.1 | 63.6 |
| low | 2 / 18 | 16 | bypass 0x00 | 47.8 | 47.3 | 0.5 | 63.6 |
| low | 2 / 18 | 16 | optimal 0x27 | 36.2 | 35.1 | 1.0 | 63.6 |
| low | 3.5 / 19.5 | 16 | bypass 0x00 | 37.6 | 37.7 | −0.1 | 64.4 |
| low | 3.5 / 19.5 | 16 | optimal 0x27 | 30.7 | 30.6 | 0.0 | 64.4 |
| low | 1 / 21 | 20 | bypass 0x00 | 52.1 | 52.0 | 0.1 | 65.3 |
| low | 1 / 21 | 20 | optimal 0x2D | 44.3 | 43.8 | 0.6 | 65.3 |
| low | 2 / 22 | 20 | bypass 0x00 | 46.5 | 46.8 | −0.3 | 66.1 |
| low | 2 / 22 | 20 | optimal 0x2E | 40.9 | 40.3 | 0.6 | 66.1 |
| low | 3.5 / 23.5 | 20 | bypass 0x00 | 41.7 | 42.3 | −0.6 | 66.1 |
| low | 3.5 / 23.5 | 20 | optimal 0x2F | 38.0 | 38.1 | −0.1 | 66.1 |

Unit - golden, median (min to max): bypass 0.1 dB (−2.6 to 0.6); optimal 0.4 dB (−0.2 to 1.1)

## R2: RMS gain flatness (dB)

| LO side | FR1 / FR3 (GHz) | LO (GHz) | Filter | Unit flatness | Golden | Unit - golden | Unit temp (C) |
|---|---|---|---|---|---|---|---|
| high | 1 / 7 | 8 | bypass 0x00 | 1.2 | 1.1 | 0.0 | 65.3 |
| high | 1 / 7 | 8 | optimal 0x30 | 1.1 | 1.1 | 0.1 | 65.3 |
| high | 2 / 6 | 8 | bypass 0x00 | 2.5 | 2.0 | 0.6 | 65.3 |
| high | 2 / 6 | 8 | optimal 0x30 | 2.6 | 1.8 | 0.8 | 65.3 |
| high | 1 / 15 | 16 | bypass 0x00 | 1.2 | 1.3 | −0.0 | 63.6 |
| high | 1 / 15 | 16 | optimal 0x15 | 1.1 | 1.2 | −0.0 | 63.6 |
| high | 2 / 14 | 16 | bypass 0x00 | 1.1 | 0.9 | 0.1 | 64.4 |
| high | 2 / 14 | 16 | optimal 0x14 | 0.8 | 0.9 | −0.0 | 64.4 |
| high | 3.5 / 12.5 | 16 | bypass 0x00 | 1.0 | 0.9 | 0.2 | 65.3 |
| high | 3.5 / 12.5 | 16 | optimal 0x1A | 1.7 | 1.7 | 0.0 | 65.3 |
| high | 1 / 19 | 20 | bypass 0x00 | 0.8 | 0.9 | −0.0 | 66.1 |
| high | 1 / 19 | 20 | optimal 0x1F | 1.1 | 1.0 | 0.1 | 66.1 |
| high | 2 / 18 | 20 | bypass 0x00 | 1.4 | 1.3 | 0.0 | 66.1 |
| high | 2 / 18 | 20 | optimal 0x1E | 1.1 | 1.1 | 0.0 | 66.1 |
| high | 3.5 / 16.5 | 20 | bypass 0x00 | 1.4 | 1.2 | 0.1 | 66.1 |
| high | 3.5 / 16.5 | 20 | optimal 0x1F | 1.7 | 1.6 | 0.1 | 66.1 |
| low | 1 / 9 | 8 | bypass 0x00 | 0.6 | 0.7 | −0.0 | 63.6 |
| low | 1 / 9 | 8 | optimal 0x3E | 0.7 | 0.6 | 0.1 | 63.6 |
| low | 2 / 10 | 8 | bypass 0x00 | 1.8 | 1.4 | 0.4 | 65.3 |
| low | 2 / 10 | 8 | optimal 0x3E | 1.9 | 1.6 | 0.3 | 65.3 |
| low | 3.5 / 11.5 | 8 | bypass 0x00 | 0.7 | 1.0 | −0.3 | 65.3 |
| low | 3.5 / 11.5 | 8 | optimal 0x3E | 0.9 | 0.9 | 0.0 | 65.3 |
| low | 1 / 17 | 16 | bypass 0x00 | 0.9 | 1.0 | −0.0 | 63.6 |
| low | 1 / 17 | 16 | optimal 0x24 | 0.9 | 0.8 | 0.2 | 63.6 |
| low | 2 / 18 | 16 | bypass 0x00 | 1.3 | 1.0 | 0.2 | 63.6 |
| low | 2 / 18 | 16 | optimal 0x27 | 1.4 | 1.2 | 0.2 | 63.6 |
| low | 3.5 / 19.5 | 16 | bypass 0x00 | 1.7 | 1.6 | 0.1 | 64.4 |
| low | 3.5 / 19.5 | 16 | optimal 0x27 | 1.5 | 1.3 | 0.1 | 64.4 |
| low | 1 / 21 | 20 | bypass 0x00 | 0.9 | 0.8 | 0.0 | 65.3 |
| low | 1 / 21 | 20 | optimal 0x2D | 0.8 | 0.9 | −0.1 | 65.3 |
| low | 2 / 22 | 20 | bypass 0x00 | 1.2 | 1.0 | 0.2 | 65.3 |
| low | 2 / 22 | 20 | optimal 0x2E | 1.0 | 1.0 | 0.1 | 65.3 |
| low | 3.5 / 23.5 | 20 | bypass 0x00 | 1.7 | 1.6 | 0.1 | 66.1 |
| low | 3.5 / 23.5 | 20 | optimal 0x2F | 1.5 | 1.4 | 0.1 | 66.1 |

Unit - golden, median (min to max): bypass 0.1 dB (−0.3 to 0.6); optimal 0.1 dB (−0.1 to 0.8)

## R3: compression

| Panel | Unit gain / in P1dB / out P1dB / out P3dB | Golden gain / in P1dB / out P1dB / out P3dB | Delta gain / out P1dB / out P3dB | Unit / golden temp (C) |
|---|---|---|---|---|
| low-side 1 / 9 GHz | 52.5 / −33.4 / 18.1 / 20.7 | 52.0 / −32.6 / 18.4 / 20.9 | 0.6 / −0.3 / −0.1 | 63.6 / 72.1 |
| low-side 2 / 22 GHz | 42.3 / −28.4 / 12.9 / 16.2 | 41.5 / −27.3 / 13.3 / 16.4 | 0.8 / −0.4 / −0.2 | 66.1 / 78.0 |
| high-side 2 / 14 GHz | 38.8 / −24.9 / 12.9 / 16.2 | 38.5 / −24.3 / 13.2 / 16.4 | 0.3 / −0.3 / −0.2 | 66.9 / 78.8 |

## R4: image rejection (dB)

| LO side | FR1 / FR3 (GHz) | LO (GHz) | Filter | Unit rejection | Golden | Unit - golden | Unit temp (C) |
|---|---|---|---|---|---|---|---|
| high | 1 / 7 | 8 | bypass 0x00 | 2.8 | 3.0 | −0.1 | 65.3 |
| high | 1 / 7 | 8 | optimal 0x30 | 24.0 | 21.0 | 3.0 | 65.3 |
| high | 2 / 6 | 8 | bypass 0x00 | −2.9 | −2.9 | −0.1 | 65.3 |
| high | 2 / 6 | 8 | optimal 0x30 | 50.4 | 45.1 | 5.3 | 65.3 |
| high | 1 / 15 | 16 | bypass 0x00 | −0.1 | 0.1 | −0.2 | 64.4 |
| high | 1 / 15 | 16 | optimal 0x15 | 17.6 | 16.5 | 1.1 | 64.4 |
| high | 2 / 14 | 16 | bypass 0x00 | −1.2 | −1.4 | 0.2 | 64.4 |
| high | 2 / 14 | 16 | optimal 0x14 | 41.1 | 41.1 | −0.1 | 64.4 |
| high | 3.5 / 12.5 | 16 | bypass 0x00 | 4.3 | 4.8 | −0.5 | 66.1 |
| high | 3.5 / 12.5 | 16 | optimal 0x1A | 38.7 | 35.0 | 3.8 | 66.1 |
| high | 1 / 19 | 20 | bypass 0x00 | −1.1 | −1.0 | −0.0 | 66.1 |
| high | 1 / 19 | 20 | optimal 0x1F | 12.3 | 11.8 | 0.6 | 66.1 |
| high | 2 / 18 | 20 | bypass 0x00 | −0.1 | −1.1 | 0.9 | 66.1 |
| high | 2 / 18 | 20 | optimal 0x1E | 23.4 | 23.2 | 0.2 | 66.1 |
| high | 3.5 / 16.5 | 20 | bypass 0x00 | −1.1 | −1.8 | 0.7 | 66.1 |
| high | 3.5 / 16.5 | 20 | optimal 0x1F | 35.2 | 34.5 | 0.7 | 66.1 |
| low | 1 / 9 | 8 | bypass 0x00 | −2.8 | −3.0 | 0.2 | 63.6 |
| low | 1 / 9 | 8 | optimal 0x3E | 33.8 | 38.6 | −4.9 | 63.6 |
| low | 2 / 10 | 8 | bypass 0x00 | 3.0 | 3.0 | −0.0 | 65.3 |
| low | 2 / 10 | 8 | optimal 0x3E | 59.9 | 60.0 | −0.1 | 65.3 |
| low | 3.5 / 11.5 | 8 | bypass 0x00 | 23.3 | 24.5 | −1.2 | 65.3 |
| low | 3.5 / 11.5 | 8 | optimal 0x3E | 74.9 | 61.6 | 13.3 | 65.3 |
| low | 1 / 17 | 16 | bypass 0x00 | 0.1 | −0.0 | 0.2 | 63.6 |
| low | 1 / 17 | 16 | optimal 0x24 | 18.1 | 21.0 | −2.9 | 63.6 |
| low | 2 / 18 | 16 | bypass 0x00 | 1.2 | 1.4 | −0.2 | 63.6 |
| low | 2 / 18 | 16 | optimal 0x27 | 58.4 | 63.8 | −5.4 | 63.6 |
| low | 3.5 / 19.5 | 16 | bypass 0x00 | −4.3 | −4.8 | 0.5 | 63.6 |
| low | 3.5 / 19.5 | 16 | optimal 0x27 | 57.0 | 53.1 | 3.9 | 63.6 |
| low | 1 / 21 | 20 | bypass 0x00 | 1.1 | 1.0 | 0.0 | 66.1 |
| low | 1 / 21 | 20 | optimal 0x2D | 15.5 | 18.1 | −2.7 | 66.1 |
| low | 2 / 22 | 20 | bypass 0x00 | 0.1 | 1.1 | −0.9 | 66.1 |
| low | 2 / 22 | 20 | optimal 0x2E | 46.7 | 48.3 | −1.5 | 66.1 |
| low | 3.5 / 23.5 | 20 | bypass 0x00 | 1.1 | 1.8 | −0.7 | 66.1 |
| low | 3.5 / 23.5 | 20 | optimal 0x2F | 47.8 | 54.1 | −6.3 | 66.1 |

Unit - golden, median (min to max): bypass −0.0 dB (−1.2 to 0.9); optimal 0.2 dB (−6.3 to 13.3)

## R5/R6: noise figure, optimal filter (dB)

| LO side | FR1 / FR3 (GHz) | Unit NF | Golden NF | Unit - golden | Unit gain / golden gain (dB) | Margin above FieldFox floor (dB) |
|---|---|---|---|---|---|---|
| high | 1 / 7 | 6.9 | 7.3 | −0.4 | 51.2 / 50.3 | 30.8 |
| high | 1 / 15 | 11.8 | 11.9 | −0.1 | 43.3 / 42.7 | 27.83 |
| high | 1 / 19 | 11.4 | 11.6 | −0.2 | 41.9 / 41.9 | 26.05 |
| high | 2 / 6 | 12.5 | 12.9 | −0.4 | 41.2 / 40.8 | 24.08 |
| high | 2 / 14 | 10.2 | 10.4 | −0.2 | 39.5 / 39.0 | 20.05 |
| high | 2 / 18 | 10.7 | 11.1 | −0.4 | 38.0 / 37.0 | 19.03 |
| high | 3.5 / 12.5 | 10.5 | 11.6 | −1.2 | 34.8 / 33.7 | 16.95 |
| high | 3.5 / 16.5 | 11.2 | 11.9 | −0.7 | 34.4 / 33.8 | 17.31 |
| low | 1 / 9 | 6.3 | 6.7 | −0.5 | 52.6 / 51.9 | 31.6 |
| low | 1 / 17 | 11.8 | 12.8 | −0.9 | 43.1 / 41.6 | 27.72 |
| low | 1 / 21 | 10.1 | 10.9 | −0.8 | 43.6 / 42.8 | 26.44 |
| low | 2 / 10 | 7.6 | 8.3 | −0.6 | 47.0 / 46.5 | 24.98 |
| low | 2 / 18 | 12.4 | 13.2 | −0.8 | 36.9 / 35.5 | 19.65 |
| low | 2 / 22 | 7.2 | 7.7 | −0.5 | 42.1 / 41.3 | 19.74 |
| low | 3.5 / 11.5 | 13.7 | 14.2 | −0.6 | 38.8 / 38.2 | 24.05 |
| low | 3.5 / 19.5 | 13.8 | 14.7 | −0.9 | 31.0 / 30.5 | 16.47 |
| low | 3.5 / 23.5 | 8.9 | 8.9 | 0.0 | 37.4 / 37.5 | 17.92 |

Unit - golden, median (min to max): −0.5 dB (−1.2 to 0.0)

## R7: LO / 2xLO leaking out of "RX-side FR3 RF In" (dBm)

| LO (GHz) | Unit LO / golden LO | Unit 2xLO / golden 2xLO | Unit: change with TX bias 5 mV off (LO / 2xLO) | Unit temp (C) |
|---|---|---|---|---|
| 8 | −73.5 / −73.8 | −80.3 / −69.4 | −0.0 / 1.0 | 62.7 |
| 16 | −59.1 / −55.5 |  /  | −0.0 /  | 65.3 |
| 20 | −64.9 / −63.2 |  /  | 0.2 /  | 66.1 |

