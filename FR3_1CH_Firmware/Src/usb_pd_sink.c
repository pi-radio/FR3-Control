#include "usb_pd_sink.h"
#include "main.h"

void USBPDSink_Init(void)
{
  LL_UCPD_InitTypeDef init;

  /* Timing config only (clock prescaler/bit timing) - ST's own defaults,
   * unrelated to CC current sensing itself but required before the
   * peripheral will enable. LL_UCPD_Init() disables UCPD1 internally
   * before writing CFG1, matching the "CFG1 only changes while disabled"
   * rule. */
  LL_UCPD_StructInit(&init);
  (void)LL_UCPD_Init(UCPD1, &init);

  /* Enable before touching CR - confirmed via debugger that CR (role,
   * CCENABLE) reads back as 0 if SetSNKRole()/SetccEnable() are called
   * before Enable(): the peripheral silently drops whatever was written to
   * CR before UCPDEN's 0->1 transition, even though CFGR1 itself keeps
   * whatever was written to it. Enabling first, then setting the role and
   * CC enable, is the order that actually sticks. */
  LL_UCPD_Enable(UCPD1);

  /* Sink role + Rd on both CC1 and CC2 - only one is ever actually
   * connected (cable orientation), enabling both costs nothing. */
  LL_UCPD_SetSNKRole(UCPD1);
  LL_UCPD_SetccEnable(UCPD1, LL_UCPD_CCENABLE_CC1CC2);
}

static USBPDSink_CurrentTier_t USBPDSink_DecodeVstate(uint32_t vstate, uint32_t vrp_default,
                                                        uint32_t vrp_1_5a, uint32_t vrp_3_0a)
{
  if (vstate == vrp_3_0a)
  {
    return USB_PD_SINK_CURRENT_3_0A;
  }
  if (vstate == vrp_1_5a)
  {
    return USB_PD_SINK_CURRENT_1_5A;
  }
  if (vstate == vrp_default)
  {
    return USB_PD_SINK_CURRENT_DEFAULT;
  }
  return USB_PD_SINK_CURRENT_NONE;
}

USBPDSink_CurrentTier_t USBPDSink_GetCurrentTier(void)
{
  USBPDSink_CurrentTier_t cc1_tier = USBPDSink_DecodeVstate(
      LL_UCPD_GetTypeCVstateCC1(UCPD1), LL_UCPD_SNK_CC1_VRP, LL_UCPD_SNK_CC1_VRP15A, LL_UCPD_SNK_CC1_VRP30A);
  USBPDSink_CurrentTier_t cc2_tier = USBPDSink_DecodeVstate(
      LL_UCPD_GetTypeCVstateCC2(UCPD1), LL_UCPD_SNK_CC2_VRP, LL_UCPD_SNK_CC2_VRP15A, LL_UCPD_SNK_CC2_VRP30A);

  /* Only one CC line is ever actually connected - the other reads as "no
   * valid state". Whichever isn't NONE wins. */
  return (cc1_tier != USB_PD_SINK_CURRENT_NONE) ? cc1_tier : cc2_tier;
}
