"""Survey-weighted estimates with design-based error margins.

NSS and PLFS samples are stratified and clustered: villages (first-stage units, "FSUs") are drawn
within strata, then households within villages. Households in one village resemble each other,
so treating them as independent understates uncertainty. The functions here estimate a weighted
mean (a ratio estimator) and its standard error by Taylor linearisation, with first-stage units
as clusters within strata (with-replacement approximation), the method of Stata's ``svy`` and
R's ``survey`` package. :func:`subsample_se` gives NSSO's own check from its two independent
sub-samples.

Domains (a state, cultivating households) are handled by setting the linearised value to zero
outside the domain while keeping the full design, which is the correct variance for a domain
whose sample size is itself random.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from statistics import NormalDist
from typing import Any, Literal

import numpy as np
import numpy.typing as npt
import pandas as pd

LonelyPSU = Literal["adjust", "remove", "fail"]
ArrayLike = Any


@dataclass(frozen=True)
class Estimate:
    """A weighted mean with its error margin.

    ``rse`` is the relative standard error in percent (``100 * se / |estimate|``), the measure
    NSSO uses to flag unreliable cells. ``df`` is the design degrees of freedom used for the
    confidence interval: first-stage units minus strata, counted within the domain.
    """

    estimate: float
    se: float
    ci_low: float
    ci_high: float
    rse: float
    n: int
    n_psu: int
    n_strata: int
    df: int
    weight_sum: float
    level: float = 0.95

    def as_dict(self, prefix: str = "") -> dict[str, Any]:
        return {f"{prefix}{k}": v for k, v in asdict(self).items()}


def t_quantile(p: float, df: float) -> float:
    """Quantile of Student's t distribution (e.g. ``t_quantile(0.975, 10) = 2.228``).

    Uses SciPy when it is installed. Otherwise Hill's (1970) algorithm 396, refined for whole
    degrees of freedom with Newton steps on the exact distribution function, which agrees with
    SciPy to better than 1e-6.
    """
    if not 0 < p < 1:
        raise ValueError("p must be between 0 and 1")
    if df <= 0 or math.isnan(df):
        return math.nan
    try:
        from scipy.stats import t as student_t
    except ImportError:
        pass
    else:
        return float(student_t.ppf(p, df))
    if math.isinf(df) or df > 1e7:
        return NormalDist().inv_cdf(p)
    sign = 1.0 if p >= 0.5 else -1.0
    two_tailed = 2 * min(p, 1 - p)
    t = _hill_t(two_tailed, float(df))
    if float(df).is_integer() and df <= 400:
        # two Newton steps on the exact CDF for whole degrees of freedom (survey designs)
        nu = int(df)
        log_c = math.lgamma((nu + 1) / 2) - math.lgamma(nu / 2) - 0.5 * math.log(nu * math.pi)
        for _ in range(2):
            density = math.exp(log_c - (nu + 1) / 2 * math.log1p(t * t / nu))
            t -= (_t_central(t, nu) - (1 - two_tailed)) / (2 * density)
    return sign * t


def _t_central(t: float, nu: int) -> float:
    """P(|T| <= t) for whole ``nu`` (Abramowitz & Stegun 26.7.3 and 26.7.4)."""
    theta = math.atan(t / math.sqrt(nu))
    s, c2 = math.sin(theta), math.cos(theta) ** 2
    if nu % 2 == 0:
        term, total = 1.0, 1.0
        for k in range(2, nu, 2):
            term *= c2 * (k - 1) / k
            total += term
        return s * total
    if nu == 1:
        return 2 * theta / math.pi
    term = math.cos(theta)
    total = term
    for k in range(3, nu, 2):
        term *= c2 * (k - 1) / k
        total += term
    return 2 / math.pi * (theta + s * total)


def _hill_t(p: float, n: float) -> float:
    """Hill (1970), CACM algorithm 396: t such that P(|T| > t) = p."""
    if n == 1:
        return math.cos(p * math.pi / 2) / math.sin(p * math.pi / 2)
    if n == 2:
        return math.sqrt(2 / (p * (2 - p)) - 2)
    a = 1 / (n - 0.5)
    b = 48 / (a * a)
    c = ((20700 * a / b - 98) * a - 16) * a + 96.36
    d = ((94.5 / (b + c) - 3) / b + 1) * math.sqrt(a * math.pi / 2) * n
    x = d * p
    y = x ** (2 / n)
    if y > 0.05 + a:
        x = NormalDist().inv_cdf(1 - p / 2)
        y = x * x
        if n < 5:
            c += 0.3 * (n - 4.5) * (x + 0.6)
        c = (((0.05 * d * x - 5) * x - 7) * x - 2) * x + b + c
        y = (((((0.4 * y + 6.3) * y + 36) * y + 94.5) / c - y - 3) / b + 1) * x
        y = a * y * y
        y = math.expm1(y)
    else:
        y = (
            (1 / (((n + 6) / (n * y) - 0.089 * d - 0.822) * (n + 2) * 3) + 0.5 / (n + 4)) * y - 1
        ) * (n + 1) / (n + 2) + 1 / y
    return math.sqrt(n * y)


def _as_float(values: ArrayLike, name: str) -> npt.NDArray[np.float64]:
    arr = np.asarray(pd.to_numeric(pd.Series(np.asarray(values)), errors="coerce"), dtype=float)
    if arr.ndim != 1:
        raise ValueError(f"{name} must be one-dimensional")
    return arr


def _labels(values: ArrayLike | None, size: int, fill: str) -> npt.NDArray[Any]:
    if values is None:
        return np.array([fill] * size, dtype=object) if fill == "one" else np.arange(size)
    arr = np.asarray(values)
    if arr.shape != (size,):
        raise ValueError("strata and psu must have one value per row")
    return arr


def ratio_mean(
    y: ArrayLike,
    weight: ArrayLike,
    *,
    strata: ArrayLike | None = None,
    psu: ArrayLike | None = None,
    domain: ArrayLike | None = None,
    level: float = 0.95,
    lonely_psu: LonelyPSU = "adjust",
) -> Estimate:
    """Weighted mean of ``y`` over ``domain`` with a Taylor-linearised standard error.

    Rows where ``y`` is missing are left out of the domain. Weights must be present and
    non-negative for every row. With no ``psu`` each row is its own cluster; with no ``strata``
    the design has one stratum.

    ``lonely_psu`` says what to do with a stratum that has a single first-stage unit:
    ``"adjust"`` (default, conservative) centres it on the overall mean, as R's survey package
    does with ``options(survey.lonely.psu = "adjust")``; ``"remove"`` lets it add no variance;
    ``"fail"`` raises an error.
    """
    yv = _as_float(y, "y")
    wv = _as_float(weight, "weight")
    size = yv.size
    if wv.size != size:
        raise ValueError("y and weight must have the same length")
    if np.isnan(wv).any() or (wv < 0).any():
        raise ValueError("weights must be present and non-negative for every row")
    st = _labels(strata, size, "one")
    cl = _labels(psu, size, "row")
    dom = np.ones(size, dtype=bool) if domain is None else np.asarray(domain, dtype=bool)
    if dom.shape != (size,):
        raise ValueError("domain must have one value per row")
    dom = dom & ~np.isnan(yv)

    n = int(dom.sum())
    weight_sum = float(wv[dom].sum())
    if n == 0 or weight_sum <= 0:
        return Estimate(
            math.nan, math.nan, math.nan, math.nan, math.nan, n, 0, 0, 0, weight_sum, level
        )
    y0 = np.where(dom, yv, 0.0)
    estimate = float((wv * y0).sum() / weight_sum)
    z = np.where(dom, wv * (y0 - estimate) / weight_sum, 0.0)

    frame = pd.DataFrame({"st": st, "cl": cl, "z": z, "d": dom})
    psu_tot = frame.groupby(["st", "cl"], sort=False, dropna=False).agg(
        z=("z", "sum"), d=("d", "any")
    )
    psu_tot = psu_tot.reset_index()
    counts = psu_tot.groupby("st", sort=False)["z"].transform("size").to_numpy()
    means = psu_tot.groupby("st", sort=False)["z"].transform("mean").to_numpy()
    zt = psu_tot["z"].to_numpy()

    lonely = counts == 1
    if lonely.any() and lonely_psu == "fail":
        raise ValueError(f"{int(lonely.sum())} strata have a single first-stage unit")
    contrib = np.zeros_like(zt)
    many = ~lonely
    contrib[many] = counts[many] / (counts[many] - 1) * (zt[many] - means[many]) ** 2
    if lonely_psu == "adjust" and lonely.any():
        grand = zt.mean()
        contrib[lonely] = (zt[lonely] - grand) ** 2
    variance = float(contrib.sum())
    se = math.sqrt(variance) if variance > 0 else 0.0

    in_domain = psu_tot[psu_tot["d"]]
    n_psu = len(in_domain)
    n_strata = int(in_domain["st"].nunique())
    df = max(n_psu - n_strata, 1)
    half = t_quantile(1 - (1 - level) / 2, df) * se
    rse = 100 * se / abs(estimate) if estimate != 0 else math.inf
    return Estimate(
        estimate,
        se,
        estimate - half,
        estimate + half,
        rse,
        n,
        n_psu,
        n_strata,
        df,
        weight_sum,
        level,
    )


def subsample_se(
    y: ArrayLike, weight: ArrayLike, subsample: ArrayLike, *, domain: ArrayLike | None = None
) -> dict[str, float]:
    """NSSO's interpenetrating sub-sample check: estimate from each of the two sub-samples
    (with the sub-sample weight, e.g. ``Weight_SS``) and take ``|θ1 − θ2| / 2`` as the standard
    error of their average.

    It rests on only two replicates, so treat it as a cross-check of :func:`ratio_mean`, not as
    the error margin to publish.
    """
    yv = _as_float(y, "y")
    wv = _as_float(weight, "weight")
    ss = np.asarray(subsample).astype(str)
    dom = np.ones(yv.size, dtype=bool) if domain is None else np.asarray(domain, dtype=bool)
    dom = dom & ~np.isnan(yv)
    values = sorted(set(ss[dom]))
    if len(values) != 2:
        return {"theta1": math.nan, "theta2": math.nan, "se": math.nan}
    thetas = []
    for value in values:
        mask = dom & (ss == value)
        total = wv[mask].sum()
        thetas.append(float((wv[mask] * yv[mask]).sum() / total) if total > 0 else math.nan)
    return {"theta1": thetas[0], "theta2": thetas[1], "se": abs(thetas[0] - thetas[1]) / 2}


def weighted_quantile(
    values: ArrayLike, weight: ArrayLike, q: float | Sequence[float]
) -> float | list[float]:
    """Weighted quantile(s) by the rule of Stata's ``_pctile`` with weights.

    The quantile is the first value whose cumulative weight share reaches ``q``; when the share
    equals ``q`` exactly, the value is averaged with the next one (so equal weights give the
    ordinary median). Missing values and zero weights are ignored.
    ``weighted_quantile(x, w, 0.5)`` is the weighted median.
    """
    xv = _as_float(values, "values")
    wv = _as_float(weight, "weight")
    keep = ~np.isnan(xv) & ~np.isnan(wv) & (wv > 0)
    xv, wv = xv[keep], wv[keep]
    qs = [q] if isinstance(q, (int, float)) else list(q)
    if any(not 0 <= v <= 1 for v in qs):
        raise ValueError("quantiles must be between 0 and 1")
    if xv.size == 0:
        out = [math.nan] * len(qs)
    else:
        order = np.argsort(xv, kind="mergesort")
        xs, ws = xv[order], wv[order]
        share = np.cumsum(ws) / ws.sum()
        out = []
        for v in qs:
            i = min(int(np.searchsorted(share, v - 1e-12, side="left")), xs.size - 1)
            if abs(share[i] - v) <= 1e-12 and i + 1 < xs.size and 0 < v < 1:
                out.append(float((xs[i] + xs[i + 1]) / 2))
            else:
                out.append(float(xs[i]))
    return out[0] if isinstance(q, (int, float)) else out


def estimate_by(
    data: pd.DataFrame,
    y: str,
    by: str,
    *,
    weight: str,
    strata: str | None = None,
    psu: str | None = None,
    domain: str | pd.Series | None = None,
    level: float = 0.95,
    lonely_psu: LonelyPSU = "adjust",
    total_label: str | None = "All",
) -> pd.DataFrame:
    """:func:`ratio_mean` of column ``y`` for each value of ``by`` (plus an overall row).

    >>> estimate_by(hh, "net_receipt_rs", "state", weight="Weight_SC",
    ...             strata="stratum_id", psu="fsu", domain="cultivated")
    """
    base = np.ones(len(data), dtype=bool)
    if isinstance(domain, str):
        base = data[domain].fillna(False).astype(bool).to_numpy()
    elif domain is not None:
        base = np.asarray(domain, dtype=bool)
    args: dict[str, Any] = {
        "weight": data[weight].to_numpy(),
        "strata": data[strata].to_numpy() if strata else None,
        "psu": data[psu].to_numpy() if psu else None,
        "level": level,
        "lonely_psu": lonely_psu,
    }
    yv = data[y].to_numpy()
    groups = data[by]
    rows = []
    for value in sorted(groups.dropna().unique(), key=str):
        est = ratio_mean(yv, domain=base & (groups == value).to_numpy(), **args)
        rows.append({by: value, **est.as_dict()})
    if total_label is not None:
        rows.append({by: total_label, **ratio_mean(yv, domain=base, **args).as_dict()})
    return pd.DataFrame(rows)
