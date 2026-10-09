# Stripe adapter development

Install the capability checkout before this adapter in the Orbit workspace:

```bash
python -m pip install -e ../orbit-payments
python -m pip install -e '.[dev]'
pytest
ruff check .
mypy
```

Unit tests must use deterministic fakes and synthetic signed payloads. Stripe test-mode checks are
separate integration gates and must never use live keys in automated CI.
