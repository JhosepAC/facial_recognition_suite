# Contribution Guide

Thank you for your interest in contributing to BioVision Suite. These are the
project conventions; please read them before submitting changes.

## Environment

- Python **3.11 or 3.12**.
- Create the virtual environment and install dependencies:

  ```powershell
  python -m venv .venv
  .venv\Scripts\Activate.ps1     # Windows
  # source .venv/bin/activate    # Linux/macOS
  pip install -r requirements.txt
  ```

## Code Conventions

- Follow the layered architecture: the GUI **must not** call `FaceEngine`,
  `VideoReader`, or the database directly; go through the services
  (`app/services/`). See `docs/guia_desarrolladores.md`.
- Use the repositories in `app/database/repositories/` for all DB queries.
- All user-visible text must go in the i18n catalog
  (`app/strings/es.json` and `app/strings/en.json`) and be used via `tr(...)`;
  hardcoded Spanish strings are not accepted.
- Do not duplicate the version: edit it only in `app/__init__.py`.
- Do not add trivial comments; document the *why*, not the *what*.
- Keep tests isolated (without touching `data/biovision.db`); use `tmp_path` and
  in-memory or temporary SQLite databases.

## Tests

```powershell
.venv\Scripts\python.exe -m pytest
```

- All new functionality must include tests.
- Run the full suite before opening a PR (goal: 100% green).

## Process

1. Create a descriptively named branch: `fix/webcam-rollback`,
   `feat/export-pdf`, etc.
2. Make small commits with clear messages consistent with existing history.
3. Add the corresponding entry in `CHANGELOG.md`.
4. Run `python -m py_compile` on modified files and tests.
5. Submit the PR describing what changes and why.

## How to Report Bugs

Describe: steps to reproduce, expected vs. actual behavior, version
(from `app/__init__.py`), operating system, and `logs/app.log` snapshot if
applicable. Do not include real biometric data in the report.
