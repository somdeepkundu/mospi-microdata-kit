# mospi-microdata-kit

[![CI](https://github.com/somdeepkundu/mospi-microdata-kit/actions/workflows/ci.yml/badge.svg)](https://github.com/somdeepkundu/mospi-microdata-kit/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](pyproject.toml)
[![Licence: MIT](https://img.shields.io/badge/licence-MIT-green)](LICENSE)
[![Open in Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/somdeepkundu/mospi-microdata-kit/blob/main/notebooks/01_download_any_dataset.ipynb)

Get unit-level survey data from India's [microdata.gov.in](https://microdata.gov.in) (MoSPI) and
turn it into estimates you can defend in a policy note: survey-weighted, with error margins,
checked against the published report.

- **Download any study** (NSS, PLFS, HCES, ASI, Time Use…) by searching its title. The kit keeps
  within the portal's rate limit, retries when the portal is busy, and checks each file's size.
  It also records each file's SHA-256 so you can show where your numbers came from.
- **Read** Stata, SPSS and CSV tables with their variable labels, and write a codebook.
- **Estimate** weighted means, shares and medians by state or any group, with 95% confidence
  intervals that account for the clustered, stratified sample.
- **Worked example:** what agricultural households earned from crops in January–June 2013, by
  state, from the NSS 70th round. The results are on the
  [project page](https://somdeepkundu.github.io/farm-income/), in English, हिन्दी and বাংলা.

## Start in Colab (no installation)

| Step | What to do | Time |
|---|---|---|
| 1 | Make a free account on [microdata.gov.in](https://microdata.gov.in) and confirm your email. | 5 min |
| 2 | Sign in, open your profile, and create an **API key**. Copy it. | 1 min |
| 3 | Open the notebook: [**Download any dataset**](https://colab.research.google.com/github/somdeepkundu/mospi-microdata-kit/blob/main/notebooks/01_download_any_dataset.ipynb). Sign in to Google if asked. | 1 min |
| 4 | Click the **key icon** on Colab's left bar → *Add new secret* → name `MOSPI_API_KEY`, paste the key, switch on *Notebook access*. | 1 min |
| 5 | Press ▶ on each step, top to bottom. Change the boxes on the right to search for your survey. | 5–15 min |

The worked example has its own notebook:
[**Income from crops by state**](https://colab.research.google.com/github/somdeepkundu/mospi-microdata-kit/blob/main/notebooks/02_nss70_farm_income_by_state.ipynb).
Tick `use_demo_data` to try it in 10 seconds without a key.

## Install on your computer

| Step | What to do | Time |
|---|---|---|
| 1 | Install Python 3.10 or newer from [python.org](https://www.python.org/downloads/) (on Windows, tick *Add python.exe to PATH*). | 5 min |
| 2 | Open a terminal (Windows: *Command Prompt*; Mac: *Terminal*). | 1 min |
| 3 | Run `pip install "mospi-microdata-kit[progress] @ git+https://github.com/somdeepkundu/mospi-microdata-kit@v1.0.0"` | 1 min |
| 4 | Save your key for this session. Mac/Linux: `export MOSPI_API_KEY=your-key`; Windows: `set MOSPI_API_KEY=your-key`. | 1 min |
| 5 | Check it works: `mospi-kit search periodic labour` | 1–2 min the first time |

### From Python

```python
from mospi_kit import MicrodataClient, extract, find_table, read_table, estimate_by

client = MicrodataClient()                        # reads MOSPI_API_KEY
for study in client.search("periodic labour force 2023"):
    print(study.idno, study.title)

idno = "DDI-IND-MOSPI-NSSO-70Rnd-Sch33-visit2-Jan-Dec2013"
print([f.name for f in client.list_files(idno)])
zip_path = client.download(idno, "STATA_SASAH_70th_Round_2013_Visit 2.zip", "data/")
folder = extract(zip_path)

households = read_table(find_table(folder, "block 1&2"))
households.attrs["variable_labels"]["Weight_SC"]  # 'Final weight for sub-sample combined estimates'
```

Weighted estimates with design-based error margins:

```python
table = estimate_by(df, "net_receipt_rs", by="state", weight="Weight_SC",
                    strata="stratum_id", psu="fsu")
# columns: estimate, se, ci_low, ci_high, rse (%), n, n_psu, df, weight_sum
```

### From the command line

```text
mospi-kit search situation assessment 2013
mospi-kit files DDI-IND-MOSPI-NSSO-70Rnd-Sch33-visit2-Jan-Dec2013
mospi-kit download DDI-IND-MOSPI-NSSO-70Rnd-Sch33-visit2-Jan-Dec2013 -i "STATA*" --extract -o data/
mospi-kit codebook data/ -o codebook.csv
mospi-kit farm-income --download --data data/nss70 --out results/
```

The API key is never accepted as a command-line argument (those end up in shell history): it is
read from `MOSPI_API_KEY` or typed at a hidden prompt.

## How the kit deals with the portal

| What the portal does | What the kit does |
|---|---|
| Allows about 10 requests a minute; answers bursts with 401, 429 or 5xx | Spaces requests 6 s apart. Retries with exponential backoff (2, 4, 8… s), honouring `Retry-After`. A 401 counts as a wrong key only after the retries fail. |
| Sometimes serves an incomplete certificate chain | `verify="auto"` verifies first and, only if that fails, continues unverified for this host. It says so in the log and records it per file in `MANIFEST.json`. Use `verify=True` to forbid this, or `verify="ca.pem"` for a corporate proxy. |
| Cannot resume a download | Writes to `name.part`, renames it only when complete, and rejects files much smaller than the size the portal lists. |
| Sends an error message with status 200 instead of a file | Detects it and raises a clear error instead of saving the message as your data. |
| Lists studies 15 at a time | Reads the whole catalogue once and caches it for 24 hours. |

Errors say what to do next: a wrong key, a missing study, a busy portal and a broken download each
raise their own exception (`AuthenticationError`, `NotFoundError`, `RateLimitError`,
`DownloadError`).

## The worked example and its checks

`mospi_kit.nss70` estimates income from crop production for January–June 2013 (rabi season)
from NSS 70th round Schedule 33, Visit 2. Before it writes anything, it compares its All-India
figures with NSSO's report KI(70/33):

| Check | NSSO figure | Tolerance |
|---|---|---|
| Households surveyed in Visit 2 | 34,907 | exact |
| Agricultural households in India | 90.2 million | ±3% |
| Share that produced crops, Jan–Jun 2013 | 71.1% | ±1.5 points |
| Value of crop production per producing household | ₹36,696 | ±5% |

A run that fails a check is marked *unvalidated*. States with fewer than 30 cultivating sample
households are suppressed. Estimates with a relative standard error above 25% are flagged. Full
definitions, the variance method and limitations are in [docs/METHODOLOGY.md](docs/METHODOLOGY.md).

## What you may share

Unit-level NSS, PLFS and HCES data are released under MoSPI's terms. You accept those terms when
you request the data, and they do not let you pass the records on. This repository therefore
contains **no survey data**. CI fails if a `.dta`, `.sav` or data zip is ever committed. Share
tables, estimates and code. See [docs/DATA_TERMS.md](docs/DATA_TERMS.md).

## Other tools

Two open-source clients for the same API came first, and this kit learned from both:

- [mospi-unitdata](https://pypi.org/project/mospi-unitdata/) (Python): list and download.
- [mospiR](https://github.com/saketkc/mospiR) (R, on CRAN): list and download, with
  throttling and resumable downloads.

Use them if all you need is the files. This kit adds:
- a Colab notebook that needs no coding
- handling for the portal's certificate problem
- file checks and a manifest
- reading tables with their labels, plus codebooks
- survey-weighted error margins
- a validated worked example

## Cite

If this kit helps your work, please cite it. GitHub's *Cite this repository* button uses
[CITATION.cff](CITATION.cff). Also cite the survey itself, for example: National Statistical
Office (2014). *Situation Assessment Survey of Agricultural Households, NSS 70th Round, January–
December 2013.* Ministry of Statistics and Programme Implementation, Government of India.

## Development

```text
pip install -e ".[dev,progress]"
pytest                      # 60+ tests, including a confidence-interval coverage simulation
ruff check . && ruff format --check . && mypy
python tools/check_no_microdata.py
```

See [CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md) and [CHANGELOG.md](CHANGELOG.md).

## Author

Somdeep Kundu, RuDRA Lab, C-TARA, IIT Bombay ·
[somdeepkundu.in](https://www.somdeepkundu.in/) ·
[Geospatial portfolio](https://somdeepkundu.github.io/) ·
[LinkedIn](https://linkedin.com/in/somdeep-kundu) · Instagram
[@somdeeplearning](https://www.instagram.com/somdeeplearning/) ·
somdeepkundu@gmail.com

Code under the [MIT licence](LICENSE). Survey data © Ministry of Statistics and Programme
Implementation, Government of India, under its own terms.
