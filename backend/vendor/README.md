# Vendored Python wheels

## pyaes 1.6.1

Telethon requires `pyaes==1.6.1`, but PyPI publishes only a source archive.
Moonwalker vendors a reviewed, reproducible pure-Python wheel so automated
installs do not execute the package's `setup.py`.

- Source: `https://files.pythonhosted.org/packages/44/66/2c17bae31c906613795711fc78045c285048168919ace2220daa372c7d72/pyaes-1.6.1.tar.gz`
- Source SHA-256: `02c1b1405c38d3c370b085fb952dd8bea3fadcee6411ad99f312cc129c536d8f`
- Wheel SHA-256: `97e69519924dde9254b26b20fe37eebb4a6b811d6bda4945a53fba04a4188a83`
- PyPI upload timestamp used for reproducibility: `2017-09-20T21:17:54Z`

The archive contains four package modules, tests, metadata, a license, and a
`setup.py` that only calls `distutils.core.setup()`. Rebuild from the verified
source with:

```bash
SOURCE_DATE_EPOCH=1505942274 python -m build \
  --wheel \
  --no-isolation \
  --outdir backend/vendor \
  /path/to/pyaes-1.6.1
```

Build twice and compare SHA-256 hashes before replacing the committed wheel.
Update the expected hash in `scripts/install_python_dependencies.sh` and
`scripts/check_dependency_locks.py` in the same changeset.
