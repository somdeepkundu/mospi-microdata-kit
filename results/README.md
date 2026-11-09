# results/

The worked example writes its outputs here. They are git-ignored, so nothing is published by
accident. Only state-level aggregates are ever written.

| File | Contents |
|---|---|
| `farm_income_by_state.csv` | One row per state, pooled area and All India, every measure with `_se`, `_ci_low`, `_ci_high`, `_rse` |
| `farm_income_by_state.json` | The same, compact, with validation results and source checksums, read by the project page |
| `net_receipt_by_state.png` | Quick dot plot with 95% intervals, for checking |

## Columns of the CSV

| Column | Meaning |
|---|---|
| `code`, `name`, `kind` | NSS 2013 state code (`IN` = All India, `25+26` = pooled), name, `state` / `pooled` / `country` |
| `n_households`, `n_cultivating`, `n_villages` | Sample sizes |
| `reliability` | `ok`, `caution` (RSE > 25%) or `suppressed` (< 30 cultivating sample households) |
| `est_households`, `est_cultivating_households` | Weighted number of agricultural households |
| `pct_cultivating` | % of agricultural households that produced crops, Jan–Jun 2013 |
| `net_per_hh` | Net receipt from crops per agricultural household (₹, six months) |
| `net_per_cultivator` | Net receipt per cultivating household |
| `output_per_cultivator`, `expenses_per_cultivator` | Its two parts |
| `pct_loss` | % of cultivating households whose paid-out expenses exceeded output |
| `median_net_per_cultivator` | Weighted median |
| `unweighted_net_per_cultivator` | Plain average of sample households, for comparison only |
| `subsample_se_net_per_cultivator` | NSSO's two-sub-sample check of the standard error |
| `design_df` | Degrees of freedom behind the interval |

Definitions and method: [docs/METHODOLOGY.md](../docs/METHODOLOGY.md).
