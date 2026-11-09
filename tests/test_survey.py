from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from mospi_kit.survey import (
    _hill_t,
    estimate_by,
    ratio_mean,
    subsample_se,
    t_quantile,
    weighted_quantile,
)


def brute_force_se(y, w, strata, psu, domain, lonely="adjust"):
    """A deliberately plain re-implementation used only to check ratio_mean."""
    d = domain & ~np.isnan(y)
    X = sum(w[i] for i in range(len(y)) if d[i])
    R = sum(w[i] * y[i] for i in range(len(y)) if d[i]) / X
    totals: dict = {}
    for i in range(len(y)):
        key = (strata[i], psu[i])
        totals.setdefault(key, 0.0)
        if d[i]:
            totals[key] += w[i] * (y[i] - R) / X
    by_stratum: dict = {}
    for (h, _), z in totals.items():
        by_stratum.setdefault(h, []).append(z)
    grand = sum(totals.values()) / len(totals)
    var = 0.0
    for zs in by_stratum.values():
        if len(zs) == 1:
            if lonely == "adjust":
                var += (zs[0] - grand) ** 2
            continue
        mean = sum(zs) / len(zs)
        var += len(zs) / (len(zs) - 1) * sum((z - mean) ** 2 for z in zs)
    return R, math.sqrt(var)


def test_simple_random_sample_matches_textbook():
    rng = np.random.default_rng(1)
    y = rng.normal(100, 15, 250)
    est = ratio_mean(y, np.ones_like(y))
    assert est.estimate == pytest.approx(y.mean())
    assert est.se == pytest.approx(y.std(ddof=1) / math.sqrt(len(y)))
    assert est.df == 249
    assert est.ci_low < y.mean() < est.ci_high


@pytest.mark.parametrize("lonely", ["adjust", "remove"])
def test_matches_brute_force_with_domains_and_lonely_strata(lonely):
    rng = np.random.default_rng(7)
    n = 600
    strata = rng.integers(0, 25, n)
    psu = strata * 100 + rng.integers(0, 3, n)
    psu[strata == 3] = 300  # stratum 3 has a single village
    w = rng.uniform(50, 900, n)
    y = rng.lognormal(9, 1, n)
    y[rng.random(n) < 0.03] = np.nan
    domain = rng.random(n) < 0.6
    est = ratio_mean(y, w, strata=strata, psu=psu, domain=domain, lonely_psu=lonely)
    R, se = brute_force_se(y, w, strata, psu, domain, lonely)
    assert est.estimate == pytest.approx(R, rel=1e-12)
    assert est.se == pytest.approx(se, rel=1e-9)
    assert est.n == int((domain & ~np.isnan(y)).sum())


def test_lonely_fail_raises():
    with pytest.raises(ValueError, match="single first-stage unit"):
        ratio_mean([1.0, 2.0, 3.0], [1, 1, 1], strata=[1, 1, 2], psu=[1, 2, 3], lonely_psu="fail")


def test_confidence_interval_coverage_in_a_clustered_design():
    """Draw 400 stratified two-stage samples from one synthetic population and check that about
    95% of the intervals contain the true population mean."""
    rng = np.random.default_rng(2013)
    strata, villages, hh = 20, 40, 30
    village_effect = rng.normal(0, 8000, (strata, villages))
    stratum_level = rng.uniform(10000, 40000, strata)
    pop = (
        stratum_level[:, None, None]
        + village_effect[:, :, None]
        + rng.normal(0, 12000, (strata, villages, hh))
    )
    truth = pop.mean()
    covered = 0
    reps = 400
    for _ in range(reps):
        ys, ws, st, cl = [], [], [], []
        for h in range(strata):
            chosen = rng.choice(villages, 4, replace=False)
            for v in chosen:
                picked = rng.choice(hh, 8, replace=False)
                ys.extend(pop[h, v, picked])
                ws.extend([(villages / 4) * (hh / 8)] * 8)
                st.extend([h] * 8)
                cl.extend([h * 1000 + v] * 8)
        est = ratio_mean(np.array(ys), np.array(ws), strata=np.array(st), psu=np.array(cl))
        covered += est.ci_low <= truth <= est.ci_high
    assert 0.92 <= covered / reps <= 0.985


def test_ignoring_clustering_would_understate_uncertainty():
    rng = np.random.default_rng(3)
    villages = np.repeat(np.arange(40), 10)
    y = rng.normal(0, 1, 40)[villages] * 5 + rng.normal(0, 1, 400)
    w = np.ones(400)
    clustered = ratio_mean(y, w, psu=villages)
    naive = ratio_mean(y, w)
    assert clustered.se > 2 * naive.se
    assert clustered.df == 39


def test_empty_domain_returns_nan_not_error():
    est = ratio_mean([1.0, 2.0], [1.0, 1.0], domain=[False, False])
    assert math.isnan(est.estimate) and est.n == 0


def test_bad_weights_raise():
    with pytest.raises(ValueError):
        ratio_mean([1.0, 2.0], [1.0, -1.0])
    with pytest.raises(ValueError):
        ratio_mean([1.0, 2.0], [1.0, np.nan])


@pytest.mark.parametrize(
    "df,expected",
    [
        (1, 12.7062),
        (2, 4.3027),
        (3, 3.1824),
        (5, 2.5706),
        (10, 2.2281),
        (30, 2.0423),
        (120, 1.9799),
    ],
)
def test_t_quantile_table_values(df, expected):
    assert t_quantile(0.975, df) == pytest.approx(expected, abs=2e-4)
    assert _hill_t(0.05, df) == pytest.approx(expected, abs=1e-3)


def test_fallback_t_quantile_agrees_with_scipy(monkeypatch):
    scipy_t = pytest.importorskip("scipy.stats").t
    import builtins

    real_import = builtins.__import__

    def no_scipy(name, *args, **kwargs):
        if name.startswith("scipy"):
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_scipy)
    for df in [1, 2, 3, 4, 5, 6, 7, 9, 15, 40, 300]:
        for p in (0.8, 0.9, 0.95, 0.975, 0.99, 0.995):
            assert t_quantile(p, df) == pytest.approx(scipy_t.ppf(p, df), abs=1e-6)
    assert t_quantile(0.025, 10) == pytest.approx(-2.228139, abs=1e-6)
    assert t_quantile(0.975, 7.5) == pytest.approx(scipy_t.ppf(0.975, 7.5), abs=1e-3)


def test_weighted_quantile():
    x = np.array([5.0, 1, 3, 2, 4])
    assert weighted_quantile(x, np.ones(5), 0.5) == pytest.approx(3.0)
    assert weighted_quantile([1.0, 2.0, 100.0], [1, 1, 0], 0.5) == pytest.approx(1.5)
    assert weighted_quantile([1.0, 9.0], [9, 1], 0.5) == pytest.approx(1.0)
    assert weighted_quantile([np.nan, 4.0], [1, 1], [0.0, 1.0]) == [4.0, 4.0]
    assert math.isnan(weighted_quantile([], [], 0.5))
    with pytest.raises(ValueError):
        weighted_quantile([1.0], [1.0], 1.5)


def test_subsample_se():
    y = np.array([10.0, 10, 20, 20])
    w = np.ones(4)
    out = subsample_se(y, w, ["1", "1", "2", "2"])
    assert out == {"theta1": 10.0, "theta2": 20.0, "se": 5.0}
    assert math.isnan(subsample_se(y, w, ["1"] * 4)["se"])


def test_estimate_by_includes_total_row():
    frame = pd.DataFrame({"y": [1.0, 2, 3, 4], "g": ["a", "a", "b", "b"], "w": [1.0] * 4})
    out = estimate_by(frame, "y", "g", weight="w", total_label="All")
    assert list(out["g"]) == ["a", "b", "All"]
    assert list(out["estimate"]) == [1.5, 3.5, 2.5]
