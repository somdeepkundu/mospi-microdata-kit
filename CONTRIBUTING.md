# Contributing

Thank you for helping. Issues and pull requests are welcome, especially:

- recipes for other surveys (PLFS, HCES, the 77th round SAS), following `mospi_kit/nss70.py`;
- reports of portal behaviour the client does not handle yet;
- corrections to the methodology note.

## Set up

```text
git clone https://github.com/somdeepkundu/mospi-microdata-kit
cd mospi-microdata-kit
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -e ".[dev,progress]"
pre-commit install                                      # optional, runs the checks on commit
```

## Before you open a pull request

```text
ruff check . && ruff format --check .
mypy
pytest
python tools/check_no_microdata.py
```

- Tests must not use the network. Mock HTTP with `responses`, and use `mospi_kit.demo` for data.
  Live tests are marked `@pytest.mark.live` and skipped by default.
- **Never add real survey data**, not even a few rows, in tests, notebooks, issues or screenshots.
- A recipe must validate against a published figure before its results are called final.
- Write messages and docs in plain words: say what happened and what to do next.
- Add a line to `CHANGELOG.md` under *Unreleased*.
