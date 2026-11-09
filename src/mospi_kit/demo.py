"""Synthetic NSS 70th round Visit 2 files for tests and the no-key demo.

The files copy the real release's names, columns, codes and sampling design (strata, sub-strata,
two sub-samples of villages, eight households per village, combined and sub-sample weights), but
every value is random. Nothing here comes from real households. Results computed from these files
are labelled ``"demo"`` and must never be published.
"""

from __future__ import annotations

import os
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

from .nss70 import VISIT2_STATA_ZIP

FOLDER = "STATA_SASAH_70th_Round_2013_Visit 2"
FILES = {
    "households": "Visit 2_Block 1&2_identification of sample household and particulars of "
    "field operations.dta",
    "output": "Visit 2_Block 5a_value of output for the crops produced during July to December.dta",
    "inputs": "Visit 2_Block 6_ particulars of inputs and their expenses for crop production "
    "during July.dta",
}
# code: (districts, typical net receipt in ₹ for six months). Arbitrary values that only give the
# demo a spread across every state and UT; they are not survey results.
_STATES = {
    "01": (3, 9000),
    "02": (3, 11000),
    "03": (6, 90000),
    "04": (1, 60000),
    "05": (2, 10000),
    "06": (5, 70000),
    "07": (1, 20000),
    "08": (8, 40000),
    "09": (10, 30000),
    "10": (8, 20000),
    "11": (1, 8000),
    "12": (2, 25000),
    "13": (2, 7000),
    "14": (2, 8000),
    "15": (2, 18000),
    "16": (2, 22000),
    "17": (2, 35000),
    "18": (5, 30000),
    "19": (8, 12000),
    "20": (4, 9000),
    "21": (5, 9000),
    "22": (4, 20000),
    "23": (7, 32000),
    "24": (6, 30000),
    "25": (1, 6000),
    "26": (1, 5000),
    "27": (8, 25000),
    "28": (5, 38000),
    "29": (6, 45000),
    "30": (1, 14000),
    "31": (1, 4000),
    "32": (4, 28000),
    "33": (6, 22000),
    "34": (1, 20000),
    "35": (1, 12000),
    "36": (4, 33000),
}
_ID_COLS = [
    "HHID",
    "Vill_Blk_Slno",
    "Sector",
    "State",
    "District_id",
    "Stratum",
    "SubStratumNo",
    "SubSample",
    "Visit_no",
]
_LABELS = {
    "HHID": "Primary key - unique identifier for a household",
    "Vill_Blk_Slno": "FSU Serial No.",
    "State": "State",
    "District_id": "District",
    "Stratum": "Stratum",
    "SubStratumNo": "Sub-Stratum-no",
    "SubSample": "Sub-Sample",
    "Weight_SC": "Final weight for sub-sample combined estimates",
    "Weight_SS": "Final weight for sub-sample wise estimates",
    "b5a_q1": "Srl No.",
    "b5a_q18": "Total value (Rs.)",
    "b6_q1": "Serial no.",
    "b6_q8": "Inputs-Expenses-(Rs.)",
}


def make_visit2_demo(
    folder: str | os.PathLike[str], *, seed: int = 2013, households_per_village: int = 8
) -> Path:
    """Write ``STATA_SASAH_70th_Round_2013_Visit 2.zip`` with synthetic data into ``folder``."""
    rng = np.random.default_rng(seed)
    hh_rows, out_rows, inp_rows = [], [], []
    fsu = 10000
    for state, (districts, scale) in _STATES.items():
        for district in range(1, districts + 1):
            for sub in range(1, 4):
                villages = 1 if (state in {"26", "31"} and sub == 3) else 2
                for village in range(villages):
                    fsu += 1
                    subsample = str(village + 1)
                    weight_ss = float(rng.integers(300, 4000))
                    weight_sc = weight_ss / villages
                    for h in range(1, households_per_village + 1):
                        hhid = f"{fsu}{h:02d}"
                        ids = {
                            "HHID": hhid,
                            "Vill_Blk_Slno": str(fsu),
                            "Sector": "1",
                            "State": state,
                            "District_id": f"{district:02d}",
                            "Stratum": "01",
                            "SubStratumNo": f"{sub:02d}",
                            "SubSample": subsample,
                            "Visit_no": "2",
                        }
                        hh_rows.append({**ids, "Weight_SC": weight_sc, "Weight_SS": weight_ss})
                        grows = rng.random() < 0.72
                        if grows:
                            crops = rng.integers(1, 4)
                            values = rng.lognormal(np.log(scale * 1.6 / crops), 0.9, crops)
                            values = np.round(values, -1)
                            for i, v in enumerate(values, start=1):
                                out_rows.append({**ids, "b5a_q1": str(i), "b5a_q18": float(v)})
                            total = float(values.sum()) if rng.random() > 0.005 else np.nan
                            out_rows.append({**ids, "b5a_q1": "9", "b5a_q18": total})
                            spend = float(values.sum()) * rng.uniform(0.15, 0.75)
                            if rng.random() < 0.06:
                                spend = float(values.sum()) * rng.uniform(1.05, 1.8)
                        elif rng.random() < 0.05:
                            spend = float(rng.integers(200, 3000))
                        else:
                            continue
                        items = rng.choice(np.arange(1, 19), size=4, replace=False)
                        shares = rng.dirichlet(np.ones(4)) * spend
                        for item, amount in zip(sorted(items), shares, strict=True):
                            inp_rows.append(
                                {**ids, "b6_q1": f"{item:02d}", "b6_q8": float(round(amount))}
                            )
                        inp_rows.append({**ids, "b6_q1": "19", "b6_q8": float(round(spend))})

    target = Path(folder)
    inner = target / FOLDER
    inner.mkdir(parents=True, exist_ok=True)
    frames = {
        "households": pd.DataFrame(hh_rows),
        "output": pd.DataFrame(out_rows, columns=[*_ID_COLS, "b5a_q1", "b5a_q18"]),
        "inputs": pd.DataFrame(inp_rows, columns=[*_ID_COLS, "b6_q1", "b6_q8"]),
    }
    for key, frame in frames.items():
        labels = {c: _LABELS[c] for c in frame.columns if c in _LABELS}
        frame.to_stata(inner / FILES[key], write_index=False, version=118, variable_labels=labels)
    archive = target / VISIT2_STATA_ZIP
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name in FILES.values():
            zf.write(inner / name, f"{FOLDER}/{name}")
    for name in FILES.values():
        (inner / name).unlink()
    inner.rmdir()
    return archive
