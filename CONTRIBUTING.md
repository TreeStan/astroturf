# Contributing

The bar for a change here is "does it make a false accusation less likely, or a real
signal clearer". Both directions are welcome.

- **New signals** need a calibration row: run `check` on five repos you believe are organic
  and five you believe are not, and put the numbers in `docs/calibration.md` with the PR.
- **Weights** are opinions. Argue in an issue with data before changing them.
- **Never** add code that lists stargazer identities in reports. Aggregates only.
- Standard library only. Python 3.9 and up.

```bash
python -m unittest discover -s tests -v
python astroturf.py explain
```
