#ifndef USB_PD_SINK_H
#define USB_PD_SINK_H

/* Configures UCPD1 as a passive USB Type-C sink (Rd on both CC1/CC2) so a
 * compliant USB-C source advertises and actually supplies up to 1.5A/3A
 * instead of the bare default current - no USB-PD message negotiation,
 * just the CC-resistor-based current tiers. This alone is the whole fix:
 * a source decides how much current to offer purely from sensing a valid
 * Rd on CC, with no message exchange required - it doesn't wait for
 * anything else here.
 *
 * Call as early as possible in boot (before PowerSequence_Init(), which is
 * what actually starts drawing meaningful current), so the source has as
 * much time as possible to recognize a valid sink and ramp up before the
 * board needs it. */
void USBPDSink_Init(void);

typedef enum
{
  USB_PD_SINK_CURRENT_NONE = 0,  /* no valid source detected on either CC line */
  USB_PD_SINK_CURRENT_DEFAULT,   /* USB default current (source-dependent, typically 500mA-900mA) */
  USB_PD_SINK_CURRENT_1_5A,
  USB_PD_SINK_CURRENT_3_0A
} USBPDSink_CurrentTier_t;

/* Fresh read of the CC voltage-sensed tier the attached source is
 * advertising, on whichever of CC1/CC2 is actually connected (depends on
 * cable orientation). Diagnostic only - doesn't affect what the source
 * does; it already decided the tier as soon as it saw a valid Rd,
 * regardless of whether this is ever called. */
USBPDSink_CurrentTier_t USBPDSink_GetCurrentTier(void);

#endif /* USB_PD_SINK_H */
