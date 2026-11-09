# Methodology: income from crops by state, January–June 2013

This note explains how `mospi_kit.nss70` and the
[project page](https://somdeepkundu.github.io/farm-income/) arrive at their figures. It shows
what each number means and what it does not mean, so a reader can judge how far to rely on it.

## 1. Source

| | |
|---|---|
| Survey | Situation Assessment Survey of Agricultural Households, NSS 70th round, Schedule 33 |
| Agency | National Statistical Office (formerly NSSO), Ministry of Statistics and Programme Implementation |
| Release used | Visit 2, Stata files, `DDI-IND-MOSPI-NSSO-70Rnd-Sch33-visit2-Jan-Dec2013` on microdata.gov.in |
| Fieldwork | Visit 2, August–December 2013 |
| Reference period | Crops produced **January–June 2013** (mainly the rabi season) |
| Coverage | Rural India; agricultural households only |
| Sample | 34,907 households in 4,529 villages (central sample) |

Several file names in the Visit 2 release say "July to December". The Visit 2 schedule (Block 5b
heading) and NSSO's report both give January–June 2013. The file names were carried over from
Visit 1.

**Agricultural household**, as NSSO defines it for this survey: a rural household that received
more than ₹3,000 worth of produce from agricultural activities in the last 365 days (crops,
horticulture, fodder, plantation, animal husbandry, poultry, fishery, piggery, bee-keeping,
sericulture and similar), with at least one member self-employed in agriculture in principal or
subsidiary status. Households of landless agricultural labourers who do not farm on their own
account are not included.

## 2. Measures

All money values are in rupees at 2013 prices, for the six months, per household.

| Measure | Definition | Households counted |
|---|---|---|
| Producing crops (%) | Share with at least one crop in Block 5a | all agricultural households |
| Value of output | Block 5a, column 18 (value of product and by-product), "all crops" row (serial 9); the sum of crop rows where that row is blank | cultivating |
| Paid-out expenses | Block 6, column 8, "total" row (serial 19); the sum of input rows where that row is blank | cultivating |
| Net receipt | Value of output − paid-out expenses | all, and cultivating |
| Median net receipt | Weighted median of net receipt | cultivating |
| Made a loss (%) | Share whose paid-out expenses exceeded output | cultivating |

**Paid-out expenses only.** NSSO recorded only what households actually paid for inputs. Seed
from the household's own harvest, family labour, and the rent of land the household owns were
entered at zero. So net receipt is *not* profit in the economist's sense, and it overstates
what farming earns once own labour and land are valued. NSSO's report makes the same point.

**Per agricultural household and per cultivating household.** About three in ten agricultural
households grew no crop in January–June 2013 (they kept livestock, or farmed only in kharif).
Counting them as zero gives *net receipt per agricultural household*, which matches NSSO's own
denominator. Leaving them out gives *net receipt per cultivating household*, which answers "what
did a household that farmed this season earn from it?". Both are published, and the page labels
which one it is showing.

A household that paid for inputs but had no crop output in the period is not a cultivating
household. Its net receipt is negative, and it counts in the per-agricultural-household figure.

## 3. Estimation

**Weights.** Each household carries `Weight_SC`, NSSO's final weight for estimates that combine
its two sub-samples. The weighted mean of `y` over a domain `D` is

    R = Σ wᵢ yᵢ / Σ wᵢ      (i in D)

**Design.** NSS samples villages (first-stage units, FSU) within strata, then households within
villages. The kit uses:

- strata = state × district × stratum × sub-stratum (`State`, `District_id`, `Stratum`,
  `SubStratumNo`);
- clusters = FSU (`Vill_Blk_Slno`).

**Standard error** by Taylor linearisation (with-replacement approximation at the first stage),
the method used by Stata's `svy: mean` and R's `survey::svymean`:

    zᵢ   = wᵢ (yᵢ − R) / Σ_D w    for i in D, 0 otherwise
    z_hj = Σ zᵢ over households in village j of stratum h
    V(R) = Σ_h  n_h / (n_h − 1) · Σ_j (z_hj − z̄_h)²

A stratum with a single village is centred on the overall mean of village totals ("adjust", the
conservative choice). Domains (a state, cultivating households) keep the whole design, with z set
to zero outside the domain. This is correct when a domain's sample size is itself random.

**Confidence interval.** R ± t · SE, where t is from Student's t distribution with degrees of
freedom = villages − strata within the domain. This widens intervals for small states: with 3
degrees of freedom, t is 3.18 instead of 1.96.

**Relative standard error** (RSE) = 100 · SE / |R|, the measure NSSO uses to flag weak cells.

**Cross-check.** NSSO draws two independent sub-samples. The kit also estimates from each with
`Weight_SS` and reports |θ₁ − θ₂| / 2. It rests on two replicates only, so it is a check, not
the published margin.

**Median.** Stata's `_pctile` rule with weights: the first value whose cumulative weight share
reaches 50% (averaged with the next value on an exact tie). No interval is given for the median.

**Shares** (percent producing crops, percent making a loss) are weighted means of a 0/100
indicator, with the same standard error.

## 4. Reliability rules

| Rule | Effect |
|---|---|
| Fewer than 30 cultivating sample households | The state is not published ("suppressed"); its households still count in All India |
| RSE above 25% for net receipt per cultivating household | Shown, marked "use with caution" |

In the 2013 sample, Chandigarh, Delhi and Daman & Diu fall under the first rule. Dadra & Nagar
Haveli and Daman & Diu, which became one Union Territory in 2020, are also estimated as one pooled
area so the map can show the present-day boundary.

## 5. Validation against NSSO's report

Every run compares All-India figures with *Key Indicators of Situation of Agricultural Households
in India*, NSS KI(70/33), December 2014:

| Check | NSSO figure | Source | Tolerance |
|---|---|---|---|
| Households surveyed in Visit 2 | 34,907 | section 2.4 | exact |
| Agricultural households | 90.2 million | section 3.2 | ±3% |
| Share producing crops, Jan–Jun 2013 | 71.1% | Statement 16B | ±1.5 points |
| Value of crop production per producing household | ₹36,696 | Statement 16B | ±5% |

`pass` = within tolerance, `warn` = within twice the tolerance, `fail` = further off. A run with
any failure is labelled *unvalidated*, and the page shows a warning instead of presenting it as
final. The tolerances allow for rounding in the report and for NSSO's exact treatment of
pre-harvest sales, which the report includes in output value.

## 6. Boundaries and names

State codes are those of 2013. The release already codes Telangana's districts as 36, and Andhra
Pradesh (28) excludes them. Jammu & Kashmir (01) includes present-day Ladakh, so the map shows the
2013 estimate on both, with a note. Names are today's (Uttarakhand, not Uttaranchal). Map
boundaries come from [geoKosh](https://github.com/somdeepkundu/geoKosh). Areas under dispute between
states and areas with no survey data are shown in grey.

## 7. Limitations

- **Sampling error only.** The intervals cover the uncertainty of drawing a sample. They do not
  cover non-response, recall error, or valuation error (households valued their own output).
- **One season.** January–June is mostly rabi. States whose main crop is kharif (much of the east
  and north-east) look poorer here than over a full year. Annual figures need Visit 1 as well.
- **Nominal 2013 rupees.** The figures are not adjusted for inflation. To restate them in today's
  prices, use a consumer price index for rural or agricultural labourers, and say so.
- **Crops only.** Wages, livestock, non-farm business and transfers are not included, so these
  are not household incomes.
- **Means are pulled up by large farms.** The median is often half the mean; quote both.
- **Old boundaries, old data.** The survey is from 2013. The 77th round (2019) repeated it, and
  the same recipe pattern applies to it.

## 8. Reproduce

```text
pip install "mospi-microdata-kit @ git+https://github.com/somdeepkundu/mospi-microdata-kit@v1.0.0"
mospi-kit farm-income --download --data data/nss70 --out results/
```

`data/nss70/MANIFEST.json` records the SHA-256 of the downloaded zip, and the results JSON
records the kit version, so a figure can be traced to an exact file and code version.
