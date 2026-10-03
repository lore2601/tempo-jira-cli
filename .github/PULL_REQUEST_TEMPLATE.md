## Summary

<!-- What does this change and why? Link related issues (Fixes #123). -->

## Checklist

- [ ] Tests added or updated (`uv run pytest`)
- [ ] `uv run ruff format --check src tests && uv run ruff check src tests && uv run mypy` pass
- [ ] User-facing changes documented in `README.md` / `docs/` and `CHANGELOG.md` (Unreleased)
- [ ] New write commands go through `guard_write` (policy, `--dry-run`, `--yes`)
- [ ] New arguments are validated in `validation.py`
