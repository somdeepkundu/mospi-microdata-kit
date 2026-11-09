"""Recipe: what agricultural households earned from crops, January–June 2013, by state.

Source: NSS 70th round, Schedule 33 (Situation Assessment Survey of Agricultural Households),
Visit 2, on microdata.gov.in. Visit 2 asked about crops produced from January to June 2013 (the
rabi season). Some file names in the release say "July to December"; the Visit 2 schedule and
NSSO's report both give January–June 2013.

Definitions follow NSSO's report KI(70/33):

* **Value of output**: Block 5a, total value of the crop and its by-products (column 18), from
  the household's "all crops" row (serial 9), or the sum of its crop rows when that row is blank.
* **Paid-out expenses**: Block 6, column 8, the "total" row (serial 19), or the sum of the input
  rows. NSSO recorded only what was paid; seed saved from the household's own farm, family
  labour and owned land are recorded at zero.
* **Net receipt** = value of output − paid-out expenses, for the six months.
* **Cultivating household**: an agricultural household with at least one crop in Block 5a.

Estimates use the combined sub-sample weight ``Weight_SC``, strata = state × district × stratum
× sub-stratum and first-stage units (villages) as clusters. See ``docs/METHODOLOGY.md``.
"""

from __future__ import annotations

import json
import logging
import math
import os
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from . import __version__
from .files import extract, find_table, read_table
from .survey import ratio_mean, subsample_se, weighted_quantile

log = logging.getLogger("mospi_kit")

VISIT2_IDNO = "DDI-IND-MOSPI-NSSO-70Rnd-Sch33-visit2-Jan-Dec2013"
VISIT2_TITLE = "Situation Assessment Survey of Agricultural Households, NSS 70th Round, Visit 2"
VISIT2_STATA_ZIP = "STATA_SASAH_70th_Round_2013_Visit 2.zip"
VISIT2_REPORT_PDF = "KI_70_33_19dec14.pdf"
PERIOD = {"start": "2013-01", "end": "2013-06", "label": "January–June 2013", "season": "rabi"}

#: Below this many cultivating sample households a state's estimates are not published.
MIN_SAMPLE = 30
#: Above this relative standard error (%) an estimate is flagged "use with caution".
CAUTION_RSE = 25.0

#: NSS 70th round state codes, with today's names (NSS used "Uttaranchal" for 05).
STATES: dict[str, str] = {
    "01": "Jammu & Kashmir",
    "02": "Himachal Pradesh",
    "03": "Punjab",
    "04": "Chandigarh",
    "05": "Uttarakhand",
    "06": "Haryana",
    "07": "Delhi",
    "08": "Rajasthan",
    "09": "Uttar Pradesh",
    "10": "Bihar",
    "11": "Sikkim",
    "12": "Arunachal Pradesh",
    "13": "Nagaland",
    "14": "Manipur",
    "15": "Mizoram",
    "16": "Tripura",
    "17": "Meghalaya",
    "18": "Assam",
    "19": "West Bengal",
    "20": "Jharkhand",
    "21": "Odisha",
    "22": "Chhattisgarh",
    "23": "Madhya Pradesh",
    "24": "Gujarat",
    "25": "Daman & Diu",
    "26": "Dadra & Nagar Haveli",
    "27": "Maharashtra",
    "28": "Andhra Pradesh",
    "29": "Karnataka",
    "30": "Goa",
    "31": "Lakshadweep",
    "32": "Kerala",
    "33": "Tamil Nadu",
    "34": "Puducherry",
    "35": "Andaman & Nicobar Islands",
    "36": "Telangana",
}
#: Extra rows for areas whose boundaries changed after 2013.
POOLED: dict[str, tuple[str, tuple[str, ...]]] = {
    "25+26": ("Dadra & Nagar Haveli and Daman & Diu", ("25", "26")),
}
ALL_INDIA = "IN"

TABLES = {
    "households": ("block 1&2",),
    "output": ("block 5a",),
    "inputs": ("block 6",),
}
HH_COLUMNS = [
    "HHID",
    "State",
    "District_id",
    "Stratum",
    "SubStratumNo",
    "Vill_Blk_Slno",
    "SubSample",
    "Weight_SC",
    "Weight_SS",
]
OUTPUT_COLUMNS = ["HHID", "b5a_q1", "b5a_q18"]
INPUT_COLUMNS = ["HHID", "b6_q1", "b6_q8"]
OUTPUT_TOTAL_ROW = 9
INPUT_TOTAL_ROW = 19

#: name -> (column, domain, unit, description)
MEASURES: dict[str, tuple[str, str, str, str]] = {
    "pct_cultivating": (
        "is_cultivating_pct",
        "all",
        "%",
        "Agricultural households that produced crops",
    ),
    "net_per_hh": (
        "net_receipt_rs",
        "all",
        "₹",
        "Net receipt from crops per agricultural household",
    ),
    "net_per_cultivator": (
        "net_receipt_rs",
        "cultivating",
        "₹",
        "Net receipt from crops per cultivating household",
    ),
    "output_per_cultivator": (
        "output_rs",
        "cultivating",
        "₹",
        "Value of crop output per cultivating household",
    ),
    "expenses_per_cultivator": (
        "expenses_rs",
        "cultivating",
        "₹",
        "Paid-out expenses per cultivating household",
    ),
    "pct_loss": (
        "is_loss_pct",
        "cultivating",
        "%",
        "Cultivating households whose paid-out expenses exceeded output",
    ),
}


@dataclass(frozen=True)
class Benchmark:
    key: str
    label: str
    expected: float
    source: str
    abs_tol: float = 0.0
    rel_tol: float = 0.0

    def tolerance(self) -> float:
        return max(self.abs_tol, abs(self.expected) * self.rel_tol)


@dataclass(frozen=True)
class Check:
    key: str
    label: str
    expected: float
    observed: float
    tolerance: float
    status: str  # "pass", "warn" or "fail"
    source: str


#: Published by NSSO in "Key Indicators of Situation of Agricultural Households in India",
#: NSS KI(70/33), December 2014.
BENCHMARKS: tuple[Benchmark, ...] = (
    Benchmark(
        "sample_households", "Households surveyed in Visit 2", 34907, "KI(70/33), section 2.4"
    ),
    Benchmark(
        "estimated_households_million",
        "Agricultural households in India (million)",
        90.2,
        "KI(70/33), section 3.2",
        rel_tol=0.03,
    ),
    Benchmark(
        "pct_cultivating",
        "Share producing crops, Jan–Jun 2013 (%)",
        71.1,
        "KI(70/33), Statement 16B",
        abs_tol=1.5,
    ),
    Benchmark(
        "output_per_cultivator",
        "Value of crop production per producing household, Jan–Jun 2013 (₹)",
        36696,
        "KI(70/33), Statement 16B",
        rel_tol=0.05,
    ),
)


@dataclass
class Visit2Tables:
    households: pd.DataFrame
    output: pd.DataFrame
    inputs: pd.DataFrame
    files: dict[str, str] = field(default_factory=dict)


@dataclass
class Results:
    households: pd.DataFrame
    table: pd.DataFrame
    checks: list[Check]
    diagnostics: dict[str, Any]
    files: dict[str, Path] = field(default_factory=dict)

    @property
    def validated(self) -> bool:
        return all(c.status != "fail" for c in self.checks)


# ------------------------------------------------------------------- loading


def load_visit2(folder: str | os.PathLike[str]) -> Visit2Tables:
    """Read the three Visit 2 Stata tables the recipe needs from an extracted folder.

    If ``folder`` holds ``STATA_SASAH_70th_Round_2013_Visit 2.zip`` but no .dta files, the zip
    is extracted first.
    """
    folder = Path(folder)
    if not any(folder.rglob("*.dta")):
        archive = next(folder.rglob(VISIT2_STATA_ZIP), None)
        if archive is None:
            raise FileNotFoundError(f"No .dta files and no {VISIT2_STATA_ZIP} under {folder}.")
        extract(archive)
    paths = {name: find_table(folder, *phrases) for name, phrases in TABLES.items()}
    frames = {
        "households": read_table(paths["households"], columns=HH_COLUMNS),
        "output": read_table(paths["output"], columns=OUTPUT_COLUMNS),
        "inputs": read_table(paths["inputs"], columns=INPUT_COLUMNS),
    }
    return Visit2Tables(**frames, files={k: str(v) for k, v in paths.items()})


def _code(series: pd.Series, width: int = 0) -> pd.Series:
    """Survey codes as clean strings: ``1``, ``1.0`` and ``"01"`` all become ``"01"``."""
    numeric = pd.to_numeric(series, errors="coerce")
    as_int = numeric.dropna()
    if len(as_int) == series.notna().sum() and (as_int == as_int.round()).all():
        text = numeric.astype("Int64").astype("string")
    else:
        text = series.astype("string").str.strip()
    text = text.str.zfill(width) if width else text
    result: pd.Series = text.astype(object).where(text.notna(), np.nan)
    return result


def _household_totals(
    frame: pd.DataFrame, serial: str, value: str, total_row: int
) -> tuple[pd.DataFrame, dict[str, int]]:
    serial_no = pd.to_numeric(frame[serial], errors="coerce")
    amount = pd.to_numeric(frame[value], errors="coerce")
    hhid = frame["HHID"].astype(str).str.strip()
    is_total = serial_no == total_row
    total_rows = pd.DataFrame({"HHID": hhid[is_total], "v": amount[is_total]})
    duplicate_totals = int(total_rows.duplicated("HHID").sum())
    totals = total_rows.groupby("HHID")["v"].sum(min_count=1)
    item_rows = pd.DataFrame({"HHID": hhid[~is_total], "v": amount[~is_total]})
    items = item_rows.groupby("HHID")["v"].sum(min_count=1)
    out = pd.DataFrame({"total_row": totals, "item_sum": items})
    out["value"] = out["total_row"].fillna(out["item_sum"])
    out["source"] = np.where(
        out["total_row"].notna(),
        "total row",
        np.where(out["item_sum"].notna(), "sum of items", "missing"),
    )
    stats = {
        "households": len(out),
        "total_row_used": int((out["source"] == "total row").sum()),
        "item_sum_used": int((out["source"] == "sum of items").sum()),
        "missing": int((out["source"] == "missing").sum()),
        "total_differs_from_items": int(
            (
                out["total_row"].notna()
                & out["item_sum"].notna()
                & ((out["total_row"] - out["item_sum"]).abs() > 1)
            ).sum()
        ),
        "duplicate_total_rows": duplicate_totals,
    }
    return out[["value", "source"]], stats


def household_table(tables: Visit2Tables) -> tuple[pd.DataFrame, dict[str, Any]]:
    """One row per surveyed household with output, expenses, net receipt and design columns."""
    hh = tables.households.copy()
    hh["HHID"] = hh["HHID"].astype(str).str.strip()
    if hh["HHID"].duplicated().any():
        raise ValueError(f"{int(hh['HHID'].duplicated().sum())} duplicate HHIDs in Block 1&2")
    state = _code(hh["State"], 2)
    unknown = sorted(set(state.dropna()) - set(STATES))
    if unknown:
        log.warning("State codes not in the 2013 list: %s", ", ".join(unknown))

    out, out_stats = _household_totals(tables.output, "b5a_q1", "b5a_q18", OUTPUT_TOTAL_ROW)
    inp, inp_stats = _household_totals(tables.inputs, "b6_q1", "b6_q8", INPUT_TOTAL_ROW)

    frame = pd.DataFrame(
        {
            "hhid": hh["HHID"],
            "state": state,
            "state_name": state.map(STATES),
            "stratum_id": (
                state.fillna("")
                + "-"
                + _code(hh["District_id"], 2).fillna("")
                + "-"
                + _code(hh["Stratum"], 2).fillna("")
                + "-"
                + _code(hh["SubStratumNo"], 2).fillna("")
            ),
            "fsu": hh["Vill_Blk_Slno"].astype(str).str.strip(),
            "subsample": _code(hh["SubSample"]),
            "weight": pd.to_numeric(hh["Weight_SC"], errors="coerce"),
            "weight_ss": pd.to_numeric(hh["Weight_SS"], errors="coerce"),
        }
    )
    frame = frame.join(
        out.rename(columns={"value": "output_rs", "source": "output_source"}), on="hhid"
    )
    frame = frame.join(
        inp.rename(columns={"value": "expenses_rs", "source": "expenses_source"}), on="hhid"
    )
    frame["is_cultivating"] = frame["output_source"].notna()
    frame["output_rs"] = frame["output_rs"].where(frame["is_cultivating"], 0.0)
    has_inputs = frame["expenses_source"].notna()
    frame["expenses_rs"] = frame["expenses_rs"].where(has_inputs, 0.0)
    frame["net_receipt_rs"] = frame["output_rs"] - frame["expenses_rs"]
    frame["is_cultivating_pct"] = frame["is_cultivating"].astype(float) * 100
    frame["is_loss_pct"] = np.where(
        frame["net_receipt_rs"].isna(), np.nan, (frame["net_receipt_rs"] < 0).astype(float) * 100
    )

    if frame["weight"].isna().any():
        raise ValueError(f"{int(frame['weight'].isna().sum())} households have no Weight_SC")
    orphans = {
        "output": int((~out.index.isin(frame["hhid"])).sum()),
        "inputs": int((~inp.index.isin(frame["hhid"])).sum()),
    }
    lonely = frame.groupby("stratum_id")["fsu"].nunique()
    diagnostics = {
        "households": len(frame),
        "cultivating_households": int(frame["is_cultivating"].sum()),
        "households_with_expenses_but_no_output": int(
            (has_inputs & ~frame["is_cultivating"]).sum()
        ),
        "households_with_missing_output_value": int(frame["output_rs"].isna().sum()),
        "rows_without_household": orphans,
        "block_5a": out_stats,
        "block_6": inp_stats,
        "strata": int(lonely.size),
        "villages": int(frame["fsu"].nunique()),
        "strata_with_one_village": int((lonely == 1).sum()),
        "unknown_state_codes": unknown,
    }
    return frame, diagnostics


# ---------------------------------------------------------------- estimation


def _domains(hh: pd.DataFrame) -> list[tuple[str, str, str, np.ndarray]]:
    domains = []
    for code in sorted(hh["state"].dropna().unique()):
        domains.append(
            (code, STATES.get(code, f"State {code}"), "state", (hh["state"] == code).to_numpy())
        )
    for code, (name, members) in POOLED.items():
        mask = hh["state"].isin(members).to_numpy()
        if mask.any():
            domains.append((code, name, "pooled", mask))
    domains.append((ALL_INDIA, "All India", "country", np.ones(len(hh), dtype=bool)))
    return domains


def state_table(
    hh: pd.DataFrame,
    *,
    level: float = 0.95,
    min_sample: int = MIN_SAMPLE,
    caution_rse: float = CAUTION_RSE,
) -> pd.DataFrame:
    """Every measure in :data:`MEASURES` for each state, the pooled areas and All India."""
    weight = hh["weight"].to_numpy()
    strata, psu = hh["stratum_id"].to_numpy(), hh["fsu"].to_numpy()
    cultivating = hh["is_cultivating"].to_numpy()
    rows = []
    for code, name, kind, mask in _domains(hh):
        cult_mask = mask & cultivating & hh["net_receipt_rs"].notna().to_numpy()
        row: dict[str, Any] = {
            "code": code,
            "name": name,
            "kind": kind,
            "n_households": int(mask.sum()),
            "n_cultivating": int(cult_mask.sum()),
            "n_villages": int(hh.loc[mask, "fsu"].nunique()),
            "est_households": float(weight[mask].sum()),
            "est_cultivating_households": float(weight[mask & cultivating].sum()),
        }
        for measure, (column, scope, unit, _) in MEASURES.items():
            dom = mask if scope == "all" else mask & cultivating
            est = ratio_mean(
                hh[column].to_numpy(), weight, strata=strata, psu=psu, domain=dom, level=level
            )
            low, high = est.ci_low, est.ci_high
            if unit == "%":  # a share stays within 0-100 %, whatever a symmetric interval says
                low, high = max(0.0, low), min(100.0, high)
            row[measure] = est.estimate
            row[f"{measure}_se"] = est.se
            row[f"{measure}_ci_low"] = low
            row[f"{measure}_ci_high"] = high
            row[f"{measure}_rse"] = est.rse
            if measure == "net_per_cultivator":
                row["design_df"] = est.df
        row["median_net_per_cultivator"] = weighted_quantile(
            hh.loc[cult_mask, "net_receipt_rs"], weight[cult_mask], 0.5
        )
        row["unweighted_net_per_cultivator"] = float(hh.loc[cult_mask, "net_receipt_rs"].mean())
        row["subsample_se_net_per_cultivator"] = subsample_se(
            hh["net_receipt_rs"], hh["weight_ss"], hh["subsample"], domain=cult_mask
        )["se"]

        if row["n_cultivating"] < min_sample:
            row["reliability"] = "suppressed"
        elif row["net_per_cultivator_rse"] > caution_rse:
            row["reliability"] = "caution"
        else:
            row["reliability"] = "ok"
        rows.append(row)

    table = pd.DataFrame(rows)
    suppressed = table["reliability"] == "suppressed"
    estimate_cols = [
        c
        for c in table.columns
        if c
        not in {
            "code",
            "name",
            "kind",
            "n_households",
            "n_cultivating",
            "n_villages",
            "reliability",
        }
    ]
    table.loc[suppressed, estimate_cols] = np.nan
    return table


def validate(
    hh: pd.DataFrame, table: pd.DataFrame, benchmarks: Sequence[Benchmark] = BENCHMARKS
) -> list[Check]:
    """Compare All-India figures with NSSO's published ones. ``warn`` means within twice the
    tolerance; ``fail`` means further off than that and the results should not be published."""
    india = table.loc[table["code"] == ALL_INDIA].iloc[0]
    observed = {
        "sample_households": float(len(hh)),
        "estimated_households_million": float(hh["weight"].sum()) / 1e6,
        "pct_cultivating": float(india["pct_cultivating"]),
        "output_per_cultivator": float(india["output_per_cultivator"]),
    }
    checks = []
    for bench in benchmarks:
        value = observed.get(bench.key, math.nan)
        gap = abs(value - bench.expected)
        tol = bench.tolerance()
        if math.isnan(value):
            status = "fail"
        elif gap <= tol:
            status = "pass"
        elif gap <= 2 * tol and tol > 0:
            status = "warn"
        else:
            status = "fail"
        checks.append(
            Check(bench.key, bench.label, bench.expected, value, tol, status, bench.source)
        )
    return checks


# ------------------------------------------------------------------ outputs


def assert_aggregate_only(table: pd.DataFrame, min_sample: int = MIN_SAMPLE) -> None:
    """Refuse to write anything that could identify a household."""
    banned = {"hhid", "HHID", "fsu", "Vill_Blk_Slno", "stratum_id"}
    if banned & set(table.columns):
        raise ValueError(f"Unit-level identifiers in output: {sorted(banned & set(table.columns))}")
    shown = table[table["reliability"] != "suppressed"]
    if (shown["n_cultivating"] < min_sample).any():
        raise ValueError("A published row is based on too few households")


def _clean(value: Any) -> Any:
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if isinstance(value, (np.floating,)):
        return _clean(float(value))
    if isinstance(value, (np.integer,)):
        return int(value)
    return value


def web_payload(
    results: Results, *, status: str, source_files: dict[str, Any] | None = None
) -> dict[str, Any]:
    """The compact JSON the policy page reads. ``status`` is ``"final"``, ``"unvalidated"`` or
    ``"demo"``; the page shows a banner for anything but ``"final"``."""
    rows = []
    for record in results.table.to_dict("records"):
        row: dict[str, Any] = {
            k: _clean(record[k])
            for k in (
                "code",
                "name",
                "kind",
                "n_households",
                "n_cultivating",
                "n_villages",
                "reliability",
                "est_households",
                "est_cultivating_households",
                "median_net_per_cultivator",
                "unweighted_net_per_cultivator",
                "design_df",
            )
        }
        for measure in MEASURES:
            row[measure] = {
                "v": _clean(record[measure]),
                "lo": _clean(record[f"{measure}_ci_low"]),
                "hi": _clean(record[f"{measure}_ci_high"]),
                "se": _clean(record[f"{measure}_se"]),
                "rse": _clean(record[f"{measure}_rse"]),
            }
        rows.append(row)
    return {
        "schema": 1,
        "status": status,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tool": f"mospi-microdata-kit {__version__}",
        "source": {
            "idno": VISIT2_IDNO,
            "title": VISIT2_TITLE,
            "agency": "NSO (NSSO), MoSPI",
            "catalog": "https://microdata.gov.in/NADA/index.php/catalog/134",
            "files": source_files or {},
        },
        "period": PERIOD,
        "confidence_level": 0.95,
        "thresholds": {"min_sample": MIN_SAMPLE, "caution_rse": CAUTION_RSE},
        "measures": {k: {"unit": v[2], "label": v[3], "scope": v[1]} for k, v in MEASURES.items()},
        "validation": [asdict(c) for c in results.checks],
        "diagnostics": results.diagnostics,
        "rows": rows,
    }


def run(
    folder: str | os.PathLike[str],
    out_dir: str | os.PathLike[str] = "results",
    *,
    status: str | None = None,
) -> Results:
    """Load, estimate, validate and write ``farm_income_by_state.csv`` and ``.json``.

    ``status`` defaults to ``"final"`` when every check passes and ``"unvalidated"`` otherwise.
    """
    tables = load_visit2(folder)
    hh, diagnostics = household_table(tables)
    table = state_table(hh)
    checks = validate(hh, table)
    results = Results(hh, table, checks, diagnostics)
    assert_aggregate_only(table)

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    manifest_path = next(Path(folder).rglob("MANIFEST.json"), None)
    source_files: dict[str, Any] = {}
    if manifest_path is not None:
        source_files = json.loads(manifest_path.read_text(encoding="utf-8")).get("files", {})
    final_status = status or ("final" if results.validated else "unvalidated")

    csv_path = out / "farm_income_by_state.csv"
    table.round(4).to_csv(csv_path, index=False, encoding="utf-8")
    json_path = out / "farm_income_by_state.json"
    payload = web_payload(results, status=final_status, source_files=source_files)
    json_path.write_text(json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8")
    results.files = {"csv": csv_path, "json": json_path}
    for check in checks:
        log.info(
            "%-4s %s: expected %s, got %.4g",
            check.status.upper(),
            check.label,
            check.expected,
            check.observed,
        )
    return results
