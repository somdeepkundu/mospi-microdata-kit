# Changelog

All notable changes to this project are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow
[Semantic Versioning](https://semver.org/).

## [1.0.0] - 2026-11-09

First public release. It grew out of a Colab notebook written in June 2026.

### Added
- `MicrodataClient`: search the catalogue (cached for 24 h), list files, download one file or a
  filtered set. Paced at 10 requests a minute, with exponential backoff that honours
  `Retry-After`; `.part` files renamed only when complete; size check; SHA-256 manifest.
  Verifies TLS first and falls back for this host only if needed, recording that fallback.
- Typed errors with next steps: `AuthenticationError`, `NotFoundError`, `RateLimitError`,
  `DownloadError`.
- `extract` (rejects damaged archives and zip-slip paths), `find_table`, `read_table` (Stata,
  SPSS, CSV, Parquet, keeps codes as recorded, repairs garbled labels), `codebook`.
- `ratio_mean`, `estimate_by`: weighted means with Taylor-linearised standard errors for
  stratified cluster samples, domain estimation, lonely-PSU handling, t-based intervals.
  `subsample_se` for NSSO's two-sub-sample check; `weighted_quantile` (Stata `_pctile` rule).
- `mospi_kit.nss70`: income from crops by state, January–June 2013, validated against NSSO's
  KI(70/33); suppression below 30 households; aggregate-only output guard.
- `mospi_kit.demo`: synthetic files with the real layout, for tests and a no-key demo.
- `mospi-kit` command line: `search`, `files`, `download`, `extract`, `codebook`, `farm-income`.
- Colab notebooks: download any dataset; the farm-income worked example.
- Methodology and data-terms notes; CI on Linux and Windows; a guard that refuses committed
  microdata.

### Fixed (compared with the original notebook)
- `download_file` was called but never defined; `extract_dir` was undefined; cells ran out of order.
- The Visit 2 crop blocks were labelled July–December; they cover January–June 2013.
- State averages were unweighted; they now use `Weight_SC` with error margins.
- Credit line: Indian Institute of Technology Bombay; Centre for Technology Alternatives for
  Rural Areas.

[1.0.0]: https://github.com/somdeepkundu/mospi-microdata-kit/releases/tag/v1.0.0
