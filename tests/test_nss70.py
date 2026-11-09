from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd
import pytest

from mospi_kit import nss70
from mospi_kit.nss70 import Visit2Tables, household_table


def tiny_tables() -> Visit2Tables:
    ids = ["101", "102", "103", "104"]
    households = pd.DataFrame(
        {
            "HHID": ids,
            "State": ["19", "19", "03", "3"],
            "District_id": ["01"] * 4,
            "Stratum": ["01"] * 4,
            "SubStratumNo": ["01"] * 4,
            "Vill_Blk_Slno": ["11", "11", "22", "22"],
            "SubSample": ["1", "1", "2", "2"],
            "Weight_SC": [100.0, 100.0, 50.0, 50.0],
            "Weight_SS": [200.0, 200.0, 100.0, 100.0],
        }
    )
    output = pd.DataFrame(
        {
            # 101: total row present; 102: total row blank, items summed; 103: no crops
            "HHID": ["101", "101", "101", "102", "102", "104"],
            "b5a_q1": ["1", "2", "9", "1", "9", "9"],
            "b5a_q18": [600.0, 400.0, 1000.0, 300.0, np.nan, 50.0],
        }
    )
    inputs = pd.DataFrame(
        {
            # 103 paid for inputs but harvested nothing in the season; 104 made a loss
            "HHID": ["101", "101", "103", "104"],
            "b6_q1": ["01", "19", "19", "19"],
            "b6_q8": [250.0, 250.0, 80.0, 70.0],
        }
    )
    return Visit2Tables(households, output, inputs)


def test_household_table_definitions():
    hh, diag = household_table(tiny_tables())
    hh = hh.set_index("hhid")
    assert hh.loc["101", "net_receipt_rs"] == 750
    assert hh.loc["102", "output_rs"] == 300 and hh.loc["102", "output_source"] == "sum of items"
    assert not hh.loc["103", "is_cultivating"] and hh.loc["103", "net_receipt_rs"] == -80
    assert hh.loc["104", "is_loss_pct"] == 100 and hh.loc["101", "is_loss_pct"] == 0
    assert hh.loc["104", "state"] == "03"  # "3" and "03" are the same state
    assert diag["households_with_expenses_but_no_output"] == 1
    assert diag["block_5a"]["item_sum_used"] == 1


def test_duplicate_households_are_refused():
    tables = tiny_tables()
    tables.households.loc[1, "HHID"] = "101"
    with pytest.raises(ValueError, match="duplicate"):
        household_table(tables)


def test_run_on_demo_data_writes_aggregates_only(demo_folder, tmp_path):
    results = nss70.run(demo_folder, tmp_path / "results", status="demo")
    table = results.table
    assert {"IN", "25+26"} <= set(table["code"])
    assert "hhid" not in table.columns

    suppressed = table[table["reliability"] == "suppressed"]
    assert (suppressed["n_cultivating"] < nss70.MIN_SAMPLE).all()
    assert suppressed["net_per_cultivator"].isna().all()
    shown = table[table["reliability"] != "suppressed"]
    assert (shown["net_per_cultivator_ci_low"] < shown["net_per_cultivator"]).all()
    assert (shown["net_per_cultivator"] < shown["net_per_cultivator_ci_high"]).all()
    assert ((shown["pct_cultivating"] >= 0) & (shown["pct_cultivating"] <= 100)).all()
    for share in ("pct_cultivating", "pct_loss"):
        assert (shown[f"{share}_ci_low"] >= 0).all() and (shown[f"{share}_ci_high"] <= 100).all()

    payload = json.loads(results.files["json"].read_text(encoding="utf-8"))
    assert payload["status"] == "demo" and payload["schema"] == 1
    assert payload["period"]["label"] == "January–June 2013"
    assert {c["key"] for c in payload["validation"]} == {b.key for b in nss70.BENCHMARKS}
    row = next(r for r in payload["rows"] if r["code"] == "IN")
    assert set(row["net_per_cultivator"]) == {"v", "lo", "hi", "se", "rse"}
    assert "NaN" not in results.files["json"].read_text()
    csv = pd.read_csv(results.files["csv"], dtype={"code": str})
    assert len(csv) == len(table)


def test_demo_data_fails_the_official_checks(demo_folder, tmp_path):
    results = nss70.run(demo_folder, tmp_path / "r")
    statuses = {c.key: c.status for c in results.checks}
    assert statuses["sample_households"] == "fail"
    assert not results.validated
    payload = json.loads(results.files["json"].read_text(encoding="utf-8"))
    assert payload["status"] == "unvalidated"


def test_validation_statuses():
    hh = pd.DataFrame({"weight": [90.2e6 / 34907] * 34907})
    table = pd.DataFrame(
        [{"code": "IN", "pct_cultivating": 73.5, "output_per_cultivator": 36696 * 1.2}]
    )
    checks = {c.key: c.status for c in nss70.validate(hh, table)}
    assert checks == {
        "sample_households": "pass",
        "estimated_households_million": "pass",
        "pct_cultivating": "warn",
        "output_per_cultivator": "fail",
    }


def test_assert_aggregate_only():
    good = pd.DataFrame({"reliability": ["ok"], "n_cultivating": [50]})
    nss70.assert_aggregate_only(good)
    with pytest.raises(ValueError, match="identifiers"):
        nss70.assert_aggregate_only(good.assign(hhid="1"))
    with pytest.raises(ValueError, match="too few"):
        nss70.assert_aggregate_only(pd.DataFrame({"reliability": ["ok"], "n_cultivating": [3]}))


def test_web_payload_has_no_nan():
    assert nss70._clean(float("nan")) is None
    assert nss70._clean(np.float64(2.5)) == 2.5
    assert nss70._clean(math.inf) is None
