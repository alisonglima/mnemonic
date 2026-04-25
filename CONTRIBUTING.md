# Contributing to Mnemonic

Thank you for your interest in contributing to Mnemonic.

## Development workflow

1. **Fork** the repository and clone your fork.
2. **Create a focused branch** — use a descriptive name like `feat/my-feature` or `fix/my-bug`. Avoid working on `main` directly.
3. **Run tests** — confirm the existing suite passes before making changes:
   ```bash
   make test
   ```
4. **Open a pull request** — include:
   - A clear summary of what changed and why.
   - Verification that `make test` passes.
   - Any docs updates if command surfaces or behavior changed.
   - Note risks or breaking changes if applicable.

## Scope rules

- Keep changes small and reviewable. Large refactors should be separated from feature or bug-fix PRs.
- Do not mix repository-surface changes (docs, CI, tooling) with behavioral changes without explicit justification in the PR description.
- Update documentation when command surfaces, environment variables, or architecture change.
- New features should include basic unit tests where feasible.

## Getting help

If you encounter issues following this guide, open a discussion in the repository.
