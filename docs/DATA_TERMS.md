# What you may share

*This is practical guidance, not legal advice. MoSPI's terms at the time you request a dataset
are what bind you; read them on the study's page at microdata.gov.in.*

## The short version

| You may share | You may not share |
|---|---|
| Code, notebooks with outputs cleared, this toolkit | The downloaded files (`.dta`, `.sav`, `.csv`, `.zip`) |
| Tables of estimates for states, districts or groups | Household or person records, or extracts of them |
| Codebooks (variable names and labels) | Tables small enough to point to a household |
| Charts and maps of aggregates | Copies of the data on Drive, GitHub or email |

## Why

Most NSS, PLFS and HCES unit-level data on microdata.gov.in are released under *registered
access*. You get them after agreeing to use them for statistical purposes, to keep them
confidential, not to try to identify anyone, and not to give them to others. Anyone else who
wants the data can request it themselves. The notebooks in this repository show them how.

## How this repository protects you

- `.gitignore` keeps `data/`, `input/`, `*.dta`, `*.sav` and data zips out of git.
- `tools/check_no_microdata.py` runs in CI and as a pre-commit hook. It fails if any survey data
  file is committed, whatever its name or location.
- `mospi_kit.nss70.assert_aggregate_only` refuses to write results that contain household or
  village identifiers, or a published cell built from fewer than 30 households.
- The notebooks end with a check that only `.csv`, `.json` and `.png` aggregates are bundled.

## Publishing results

- Publish estimates for groups of at least 30 sample households, and say how many.
- Show the error margin, or at least flag estimates with a relative standard error above 25%.
- Cite the survey and say which files and weights you used.
- Before sharing a notebook, use **Edit → Clear all outputs**: a printed `df.head()` is
  unit-level data.
