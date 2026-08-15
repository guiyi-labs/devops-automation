# Contributing to EasyOps

Thank you for your interest in contributing to EasyOps! This document outlines
the process for contributing to the project.

## Prerequisites

- Python 3.12+ for backend development
- Node.js 18+ and npm 9+ for frontend development
- Docker and Docker Compose for local development and integration testing
- Git and `gh` CLI for PR workflow

## Getting Started

1. Fork the repository and clone your fork
2. Create a new branch for your changes:
   ```bash
   git checkout -b feat/your-feature-name
   ```
3. Make your changes, following the existing code style and conventions
4. Run the test suite:
   ```bash
   cd easyops_api
   pip install -r requirements-dev.txt
   python -m pytest -p no:cacheprovider
   cd ../easyops_web
   npm ci && npm run build
   ```
5. Ensure CI gates pass locally:
   ```bash
   # Lint
   ruff check easyops_api
   # Compose validation
   docker compose config --quiet
   # Dependency audit
   pip-audit
   ```
6. Commit and push your changes
7. Open a pull request against the `main` branch

## Code Conventions

- **Backend (Python/FastAPI)**: Follow PEP 8 conventions. Run `ruff check`
  before committing. No unused imports, no redefined names.
- **Frontend (Vue/TypeScript)**: Follow ESLint rules. Run `npm run build`
  before committing.
- **API Routes**: New endpoints belong in `easyops_api/api/v1/` and must
  include write-audit logging for mutation endpoints.
- **Authorization**: All write endpoints require the `require_write`
  dependency; the project role model is defined in `database/models.py`.
- **Testing**: New features should include unit tests (use pytest fixtures,
  no real databases in unit tests). Changes to behavior should update
  existing tests. The full suite must remain green.
- **Alembic Migrations**: Use the dual-path migration pattern when adding
  columns: SQLite uses `op.batch_alter_table`; MySQL uses native
  `op.add_column`/`op.alter_column`. Always provide both upgrade and
  downgrade paths. Run `alembic upgrade head` before committing migration
  changes.
- **Security-sensitive code**: SSH interactions, credential handling, and
  batch execution logic live in `services/ssh_service.py`,
  `common/crypto.py`, and `services/operations.py` respectively. Changes to
  these modules require coverage ≥ 80%.

## Pull Request Workflow

1. **Before submitting**: Ensure all local checks pass (`pytest`, `ruff`,
   `docker compose config`, `pip-audit`, `npm run build`).
2. **PR description**: Clearly describe the what, why, and how of your changes.
   Reference relevant change records in `docs/changes/` if applicable.
3. **CI gates**: Your PR must pass all CI checks before review:
   - Backend: `pytest` (full suite), `ruff check`, `pip-audit`
   - Frontend: `npm ci && npm run build`
   - Deploy: `docker compose config --quiet`, `kubeconform`
4. **Review**: After CI passes, the PR will be reviewed. Address feedback
   promptly.
5. **Merge**: PRs are squash-merged into `main` by the maintainer.

## Commit and Identity Conventions

- Commits use the project's noreply identity:
  `Guiyi Labs <277616126+guiyi-labs@users.noreply.github.com>`.
- Commit messages follow Conventional Commits style:
  `feat(scope): ...`, `fix(scope): ...`, `docs(scope): ...`, `chore(scope): ...`
- Scope is typically the module affected: `e5`, `e4`, `e3`, `e2`, `e1`,
  `meta`, `ci`.

## Reporting Issues

When filing an issue, please include:

- Clear description of the problem
- Steps to reproduce
- Expected behavior vs actual behavior
- Screenshots or error logs if applicable
- Environment details (OS, Python version, Node version, Docker version)

## Security Disclosure

For security vulnerabilities, please follow the process outlined in
[SECURITY.md](SECURITY.md). Do not file public issues for security
vulnerabilities.

## Change Records

Every user-visible change must be documented:

1. Add a bullet to the `[Unreleased]` section in `CHANGELOG.md`
2. For acceptance or architectural changes, add a report in
   `docs/changes/YYYY-MM-DD-<short-description>.md`

This ensures release notes can be generated from the change log without
digging through commits.
