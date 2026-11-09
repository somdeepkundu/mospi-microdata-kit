# Security

## Your API key

- Keep it out of code, notebooks and screenshots. Use Colab Secrets, the `MOSPI_API_KEY`
  environment variable, or the hidden prompt.
- The command line refuses the key as an argument, and the client never prints or logs it
  (`repr(client)` shows only the last four characters).
- If a key leaks, delete it on your microdata.gov.in profile page and create a new one.

## TLS

microdata.gov.in has at times served an incomplete certificate chain. With the default
`verify="auto"`, the client tries a verified connection first. Only if that fails does it
continue without verification, for that host only. It logs a warning, and records
`"tls_verified": false` for each file in `MANIFEST.json`. Every download is size-checked and its
SHA-256 recorded either way. Use `verify=True` (`--strict-tls`) to forbid the fallback, or
`verify="/path/ca.pem"` (`--ca-bundle`) when your network inspects HTTPS.

## Reporting a vulnerability

Email somdeepkundu@gmail.com with "security" in the subject. Please do not open a public issue.
You will get a reply within a week.

## Survey data

Microdata must never be committed. See [docs/DATA_TERMS.md](docs/DATA_TERMS.md).
