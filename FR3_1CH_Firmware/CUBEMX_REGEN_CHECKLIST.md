# CubeMX Regeneration Checklist

Every time `.ioc` is edited and "Generate Code" is run (from CubeMX itself,
or via STM32CubeIDE's embedded CubeMX editor), CubeMX rewrites the files
below **in full**. Any of our own hand-edits inside these files that live
**outside** a `/* USER CODE BEGIN ... */` / `/* USER CODE END ... */` pair
gets silently discarded and replaced with CubeMX's own computed defaults -
with no warning, no diff shown, and a clean compile either way (it's not a
build error, it's a silent behavior regression).

**After every single "Generate Code," re-check every item on this list
before assuming the firmware is unchanged.** Do not rely on memory or on
"I don't think I touched that file" - CubeMX touches all of these
regardless of what was actually edited in the `.ioc`.

## 1. Memory pool / stack size `#define`s - reset to CubeMX's tiny defaults

All three of these live in generated headers, outside any USER CODE block,
and get reset to CubeMX's generic small defaults (1024) on every
regeneration. All three have caused real, hard-to-diagnose hangs/faults
when left at the default:

| File | Define | Must be at least | Symptom if left at default |
|---|---|---|---|
| `Inc/app_azure_rtos_config.h` | `UX_APP_MEM_POOL_SIZE` | 24576 | Hangs in `tx_application_define()`'s `MX_USBX_Init_Error` `while(1)` loop before USB hardware is ever touched (`tx_byte_allocate()` for `USBX_MEMORY_STACK_SIZE` exhausts the pool immediately) |
| `Inc/app_usbx.h` | `USBX_MEMORY_STACK_SIZE` | 16384 | `ux_device_stack_initialize()` returns `UX_MEMORY_INSUFFICIENT` (0x12) - same outward symptom as above, just fails one level deeper (only visible by debugging into `_ux_device_stack_initialize`, e.g. breakpoint at its `if (status == UX_SUCCESS)` check) |
| `Inc/app_usbx_device.h` | `UX_DEVICE_APP_THREAD_STACK_SIZE` | 4096 | Device boots and USB enumerates fine, but a HardFault hits inside newlib's `__ssvfscanf_r` (the unconditional `sscanf()` in `Commands_ProcessLine()`, `board_commands.c`) on almost every command - i.e. `*IDN?` works, everything else HardFaults |

These three are easy to miss because they're each in a different header,
none of them causes a *build* error, and two of the three failure modes
only show up once you're several stack frames deep in USBX's own source
under `Middlewares/`.

## 2. `gpio.c` - CLK_SEL default reverts to External

`MX_GPIO_Init()` is regenerated in full, and the CLK_SEL default output
level (Internal, i.e. `GPIO_PIN_SET`) gets folded back into the general
`GPIO_PIN_RESET` group alongside `LO_CTRL_3V3_Pin`/`IQ_SWAP_SW_3V3_Pin`.
Fix: move `CLK_SEL_Pin` out of that combined `HAL_GPIO_WritePin(...,
GPIO_PIN_RESET)` call and add a separate
`HAL_GPIO_WritePin(GPIOE, CLK_SEL_Pin, GPIO_PIN_SET);` line after it.

This only matters after a full/mass chip erase - on a normal reflash,
`Settings_Init()`'s persisted `settings.clock_internal` value overrides
this default at runtime regardless. But it will bite the next mass-erase
test if left wrong.

## 3. `main.c` - `MX_USB_PCD_Init()` gets re-added to `main()`

CubeMX re-inserts a call to `MX_USB_PCD_Init();` into the peripheral-init
list in `main()`, right after the other `MX_*_Init()` calls. This must be
deleted by hand every time. USB PCD hardware init is deliberately deferred
to run later, from inside `app_ux_device_thread_entry()`
(`app_usbx_device.c`), after the ThreadX scheduler has started - not during
pre-scheduler `main()`. Leaving the re-added call in doesn't necessarily
break anything by itself, but it's redundant/wrong and worth removing to
keep the actual init flow matching what the surrounding comments describe.

## 3b. `gpio.c` - `SPI_INA_CSb` (PC8) must default High (deselected)

Same class of regression as CLK_SEL above (section 2): `SPI_INA_CSb` (the
INA229's chip select, rev 1.4 only) must come up **High** (deselected) as
part of `MX_GPIO_Init()`'s own output-level setup, before `MX_SPI4_Init()`
or any SPI4 traffic happens. This isn't just a "nice to have" default -
this pin was floating (no pull, analog mode) for a long time before the
INA229 was wired into firmware at all, and is suspected of having caused
real, hard-to-diagnose SPI4 bus contention with the LMX2820's MISO line
(a floating active-low CS on a shared bus can pick up enough coupling from
SCLK/MOSI to falsely select the INA229 mid-transaction). If a future
regeneration ever puts `SPI_INA_CSb` back into a combined `GPIO_PIN_RESET`
group (the same failure pattern CLK_SEL hit) or drops it from the pinout
entirely, re-check and re-split it out explicitly, same fix pattern as
CLK_SEL.

Also re-check SPI4's **Prescaler (for Baud Rate)** is still **8** (4MHz)
in the Connectivity view after any regeneration that touches SPI4 - it was
raised from 2 (16MHz) specifically because the INA229 sharing that bus is
only rated to 10MHz; a stray edit back to 2 wouldn't break the LMX2820 or
LTC2668 (both handle 16MHz fine) but would put the INA229 out of spec.

## 4. Check for brand-new files/calls added by a *new* CubeMX component

This list covers the *known* recurring regressions from regenerating with
UCPD1/USBPD already present. Adding a genuinely new peripheral or
middleware component for the first time (like we did for UCPD1, then
later the full USBPD stack) can introduce **new** one-time integration
work that isn't "wrong," just needs review - e.g., when the USBPD
middleware was first added, CubeMX generated a call to `MX_USBPD_Init()`
inside `tx_application_define()` with its own byte pool, and our
pre-existing hand-rolled `usb_pd_sink.c`'s `USBPDSink_Init()` had to be
removed from `main()` since it would otherwise fight the new middleware
for control of the same UCPD1 registers. That kind of conflict won't
recur on routine regenerations once resolved, but *any* newly-added
peripheral/middleware is worth a full read-through of what CubeMX
generated before assuming it's inert.

## 5. Files with custom code that must stay inside specific USER CODE markers

Already handled correctly today, but worth remembering the pattern:

- `Src/app_usbx_device.c`: `CDC_EchoString`/`CDC_EraseChars`/`CmdHistory_*`
  function *definitions* (not just prototypes) must live inside
  `/* USER CODE BEGIN PFP */` / `/* USER CODE END PFP */` specifically.
  Placing them in the unprotected zone above `app_ux_device_thread_entry`
  gets them silently wiped on regeneration.

## How to actually check, in practice

There's no git CLI on this machine (GitHub Desktop only), so `git diff`
isn't available for a quick post-regen scan. After every "Generate Code":

1. Re-read this checklist file top to bottom.
2. Explicitly re-open and check the exact values in the three headers in
   section 1 - don't trust "I didn't touch that file" reasoning, and don't
   trust a stale in-memory recollection of a file's contents from earlier
   in the same session either. Re-read the file fresh.
3. Check `gpio.c` and `main.c` per sections 2, 3, and 3b.
4. If GitHub Desktop is open, its Changes list is the fastest way to see
   the full set of files CubeMX actually touched this time - review each
   one, not just the ones expected to change.
