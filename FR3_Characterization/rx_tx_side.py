"""The TX side "in normal use" during an RX-side measurement (user rule 2026-10-05, applied to the 2026-10-09 hot RX re-run).

The LO is shared, so whatever the RX side is doing, the TX side must look the way it does for a user: its LO-leakage null
applied (the stored cold/hot calibration interpolated to the LMX temperature, lo_cal_tables.py), and its optimal filter
engaged. The TX configuration that shares the RX point's LO is the one at the same (FR1, FR3):

    RX low-side  (FR3 = LO + FR1)  <->  TX upper sideband, IQ THRU
    RX high-side (FR3 = LO - FR1)  <->  TX lower sideband, IQ SWAP

and its optimal TX filter is the same rule as everywhere else (rx_nf_campaign.optimal_rx_filter for that FR3 and LO).
Both TX ports ("TX-side FR1 IF In" and "TX-side FR3 RF Out") must be 50-ohm terminated during RX runs (user).

    from rx_tx_side import tx_normal_state
    info = tx_normal_state(board, tables, fr3_hz, lo_hz)    # call after the LO is tuned
"""
from __future__ import annotations

from conversion_gain_small_case import must
from lo_cal_tables import CalTables
from rx_nf_campaign import optimal_rx_filter


def tx_normal_state(board, tables: CalTables, fr3_hz: float, lo_hz: float, temp_c: float | None = None) -> dict:
    """Apply the TX-side normal state for an RX point at (FR3, LO); the LO must already be tuned. Returns what was set."""
    if temp_c is None:
        temp_c = board.get_lmx_temperature_c()
    iv, qv = tables.bias(lo_hz, temp_c)
    high_side = lo_hz > fr3_hz
    tx_bits = optimal_rx_filter({"fr3_hz": fr3_hz, "lo_hz": lo_hz})
    must(board.set_i_v(iv), "SET I_V")
    must(board.set_q_v(qv), "SET Q_V")
    must(board.set_iq_swap(high_side), "SET IQ")
    must(board.set_tx_filter(tx_bits), f"SET TXFILTER 0x{tx_bits:02X}")
    return {"tx_i_v": f"{iv:.5f}", "tx_q_v": f"{qv:.5f}", "tx_iq": "SWAP" if high_side else "THRU",
            "tx_filter_bits": f"0x{tx_bits:02X}"}
