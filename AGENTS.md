# Repository Guidelines

## Project Structure & Module Organization
BioVision Suite (FaceScan) is a Python desktop application using PySide6, InsightFace, and SQLAlchemy/SQLite. Source lives in `app/`: `gui/` contains widgets and bundled assets, `services/` coordinates application behavior, `vision/` handles facial analysis, `recognition/` implements matching and indexing, and `database/repositories/` owns database queries. Shared configuration and security utilities live in `core/`.

Keep GUI operations behind services; widgets must not call vision engines, video readers, or the database directly. Tests live in `tests/`, settings in `config/settings.yaml`, translations in `app/strings/`, bilingual documentation in `docs/en/` and `docs/es/`, and Windows distribution scripts in `packaging/`.

## Build, Test, and Development Commands
Use Python 3.11 or 3.12. Run commands from the repository root:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"  # Dependencies, test tools, editable package
python -m app.main               # Start the desktop application
python -m pytest                 # Full test suite
python -m pytest tests/test_video_service.py -v
python -m pytest --cov=app tests/ # Coverage report
python -m py_compile app/services/person_service.py
```

For Windows distributions, run `powershell -ExecutionPolicy Bypass -File packaging\build.ps1`; it requires the `.venv` environment, PyInstaller, and Inno Setup 6, and runs tests before packaging.

## Coding Style & Naming Conventions
Follow PEP 8 with four-space indentation, `snake_case` functions/modules, `PascalCase` classes, and `UPPER_SNAKE_CASE` constants. Write new comments and docstrings in English, following PEP 257 and Google-style docstrings where applicable. No formatter or linter is configured. Put user-facing strings in both translation catalogs and access them with `tr(...)`. Maintain the version only in `app/__init__.py`.

## Testing Guidelines
Use pytest with `test_*.py` modules and `test_*` functions. Include tests for new functionality; use mocks, `tmp_path`, and temporary or in-memory SQLite databases instead of production data or downloaded models. Run the full suite and compile modified Python files before submitting. Coverage tooling is available; no numeric coverage threshold is configured.

## Commit & Pull Request Guidelines
Use small commits following existing conventions, such as `refactor(app): clarify service boundaries` or `chore(release): prepare v1.1.0`. Use descriptive branches, explain what changed and why in the PR, report validation results, and update `CHANGELOG.md` for relevant changes.

## Security & Configuration
Keep biometric processing local. Never commit real face images, embeddings, credentials, `data/`, or `config/.secret.key`. Remove sensitive information from logs and bug reports; follow `SECURITY.md` for vulnerability reporting.
