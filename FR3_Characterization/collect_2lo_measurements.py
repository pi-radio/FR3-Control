"""Collect every 2*LO power reading taken on unit 5 (2026-10-05 .. 10-07) into one table with its configuration.

    python collect_2lo_measurements.py

Output: results/unit_005/two_lo_all_measurements.csv, one row per reading. Columns: when, experiment, file, port,
mechanics (case / absorber state), lo_ghz, lo_source, lmx_power, tx_filter, rx_filter, bias (what the I/Q bias was),
i_v, q_v, input_dbm (TX IF tone, "off" = none), lo_dbm, two_lo_dbm, lmx_temp_c. Powers are at the board connector
(cable-corrected) as each script saved them.
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path

U = Path(__file__).parent / "results" / "unit_005"
OUT = U / "two_lo_all_measurements.csv"

# Mechanical state per run, as described by the user at the time (sessions of 2026-10-05..07)
MECH = {
    "131539": "full case, closed",
    "134318": "out of case",
    "134753": "out of case",
    "140424": "full case + MCS squares on PCB",
    "142433": "full case + MCS squares on PCB",
    "145600": "full case + MCS squares on PCB + 3M pads",
    "151358": "top half only, loose",
    "151640": "bottom half only, loose",
    "152140": "bottom half only, loose",
    "152804": "bottom half only, loose",
    "153411": "full case, loose, no screws (+ MCS squares on PCB)",
    "102941": "full case, loose, no screws + MCS squares on PCB + MCS on TX chips",
}
rows: list[dict] = []


def add(**kw):
    base = dict.fromkeys(["when", "experiment", "file", "port", "mechanics", "lo_ghz", "lo_source", "lmx_power",
                          "tx_filter", "rx_filter", "bias", "i_v", "q_v", "input_dbm", "lo_dbm", "two_lo_dbm",
                          "lmx_temp_c"], "")
    base.update(kw)
    rows.append(base)


def stamp_of(name: str) -> str:
    m = re.search(r"(\d{8})_(\d{6})", name)
    return f"{m.group(1)[:4]}-{m.group(1)[4:6]}-{m.group(1)[6:]} {m.group(2)[:2]}:{m.group(2)[2:4]}" if m else ""


# 1. RX-side LO leakage vs LMX power (10-05): 2LO at the RX FR3 RF input connector
f = U / "spurs_20261005" / "lmx_power_lo9.csv"
for r in csv.DictReader(open(f)):
    add(when="2026-10-05 22:36", experiment="RX LO leakage vs LMX power", file=f.name, port="RX-side FR3 RF In",
        mechanics="full case, closed", lo_ghz=9.0, lo_source="internal", lmx_power=r["lmx_power"], tx_filter=r["tx_filter"],
        rx_filter=r["rx_filter"], bias="fixed", i_v=r["i_v"], q_v=r["q_v"], input_dbm="off", lo_dbm=r["lo_dbm"],
        two_lo_dbm=r["2lo_dbm"], lmx_temp_c=r["lmx_temp_c"])

# 2. RX-side LO leakage with external LO (OctoLO, 10 GHz)
f = U / "spurs_20261005" / "rx_lo_ext_lo.csv"
for r in csv.DictReader(open(f)):
    add(when=r["time"][:16].replace("T", " "), experiment="RX LO leakage, external LO", file=f.name, port="RX-side FR3 RF In",
        mechanics="full case, closed", lo_ghz=round(float(r["lo_hz"]) / 1e9, 3), lo_source="external (OctoLO)",
        tx_filter=r["tx_filter_bits"], rx_filter=f"{r['rx_filter']} {r['rx_filter_bits']}", bias="fixed", i_v=r["i_v"],
        q_v=r["q_v"], input_dbm="off", lo_dbm=r["lo_dbm"], two_lo_dbm=r["2lo_dbm"], lmx_temp_c=r["lmx_temp_c"])

# 3. TX LO products vs IF input (tx_lo_products campaigns)
for d in sorted(U.glob("tx_lo_products_*")):
    if not (d / "readings.csv").exists():
        continue
    camp = json.load(open(d / "campaign.json"))
    for r in csv.DictReader(open(d / "readings.csv")):
        add(when=stamp_of(d.name), experiment="TX LO products vs IF input", file=f"{d.name}/readings.csv",
            port="TX-side FR3 RF Out", mechanics="full case, closed", lo_ghz=9.0, lo_source="internal",
            lmx_power=camp["lmx_power"], tx_filter=r["tx_filter"], bias=f"case {r['case']} ({r['bias']})", i_v=r["i_v"],
            q_v=r["q_v"], input_dbm=r["input_dbm"], lo_dbm=r["LO_dbm"], two_lo_dbm=r["2LO_dbm"], lmx_temp_c=r["lmx_temp_c"])

# 4. TX 2LO vs LMX power (filter bypassed)
f = U / "tx_2lo_lmx_power_20261006_010729.csv"
for r in csv.DictReader(open(f)):
    add(when=stamp_of(f.name), experiment="TX 2LO vs LMX power", file=f.name, port="TX-side FR3 RF Out",
        mechanics="full case, closed", lo_ghz=9.0, lo_source="internal", lmx_power=r["lmx_power"], tx_filter="0x00",
        bias="case 1A (null bias held)" if r["case"] == "1A" else "case 2A (0 V)", i_v=r["i_v"], q_v=r["q_v"],
        input_dbm="off", lo_dbm=r["LO_dbm"], two_lo_dbm=r["2LO_dbm"], lmx_temp_c=r["lmx_temp_c"])

# 5. TX 2LO vs filter state (each state nulled)
f = U / "tx_2lo_vs_filter_state_20261006_022433.csv"
for r in csv.DictReader(open(f)):
    add(when=stamp_of(f.name), experiment="TX 2LO vs filter state", file=f.name, port="TX-side FR3 RF Out",
        mechanics="full case, closed", lo_ghz=9.0, lo_source="internal", lmx_power=0, tx_filter=r["tx_filter"],
        bias="nulled with this filter state", i_v=r["i_v"], q_v=r["q_v"], input_dbm="off", lo_dbm=r["lo_dbm"],
        two_lo_dbm=r["two_lo_dbm"], lmx_temp_c=r["lmx_temp_c"])

# 6. TX 2LO vs bias (null, then one axis stepped)
for f in sorted(U.glob("tx_2lo_vs_bias_*.csv")):
    st = re.search(r"_(\d{6})(?:_|\.)", f.name).group(1)
    for r in csv.DictReader(open(f)):
        b = {"null": "null", "zero": "I_V = Q_V = 0 V", "null_end": "null (end of run)"}.get(
            r["axis"], f"null {'+' if float(r['di_mv'] or 0) + float(r['dq_mv'] or 0) > 0 else ''}"
                       f"{r['di_mv'] if r['axis'] == 'I' else r['dq_mv']} mV on {r['axis']}")
        add(when=stamp_of(f.name), experiment="TX 2LO vs bias", file=f.name, port="TX-side FR3 RF Out", mechanics=MECH[st],
            lo_ghz=9.0, lo_source="internal", lmx_power=0, tx_filter="0x39", bias=b, i_v=r["i_v"], q_v=r["q_v"],
            input_dbm="off", lo_dbm=r["lo_dbm"], two_lo_dbm=r["two_lo_dbm"], lmx_temp_c=r.get("lmx_temp_c", ""))

# 7. TX 2LO vs LO level (one bias axis moved to hit LO targets)
for f in sorted(U.glob("tx_2lo_vs_lo_level_*.csv")):
    st = re.search(r"_(\d{6})_", f.name).group(1)
    for r in csv.DictReader(open(f)):
        b = "null" if r["axis"] == "null" else f"{r['axis']} moved to LO target {r['target_dbm']} dBm"
        add(when=stamp_of(f.name), experiment=f"TX 2LO vs LO level ({r['case']})", file=f.name, port="TX-side FR3 RF Out",
            mechanics=MECH[st], lo_ghz=9.0, lo_source="internal", lmx_power=0, tx_filter="0x39", bias=b, i_v=r["i_v"],
            q_v=r["q_v"], input_dbm="off", lo_dbm=r["lo_dbm"], two_lo_dbm=r["two_lo_dbm"],
            lmx_temp_c=r.get("lmx_temp_c", ""))

with open(OUT, "w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)
print(f"{len(rows)} readings -> {OUT}")
