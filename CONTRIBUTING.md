# Contributing to copsearch

Thanks for your interest in contributing! Here's how to get started.

## Dev Environment Setup

```bash
git clone https://github.com/yajatns/copsearch.git
cd copsearch
pip install -e ".[dev]"
```

## Running Tests

```bash
pytest tests/ -v
```

## Linting

```bash
ruff check src/ tests/
```

All code must pass ruff before merging.

## Code Style

- Ruff is enforced in CI — run it locally before pushing.
- Type hints are encouraged for all function signatures.
- Follow PEP 8 conventions.

## Branch Naming

- `feature/description` for new features
- `fix/description` for bug fixes

## PR Process

1. Fork the repo and create your branch from `main`.
2. Make your changes and add tests.
3. Ensure `pytest` and `ruff` pass.
4. Open a PR against `main` with a clear description.
