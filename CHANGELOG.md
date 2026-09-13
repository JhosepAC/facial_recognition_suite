# Changelog

All notable changes to this project are documented in this file.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
The version is managed in `app/__init__.py` (`__version__`).

## [1.1.0] - 2026-09-13

### Added
- Bilingual documentation: `docs/en/` and `docs/es/` with mirrored guides, `README-es.md`, and renamed diagrams (`docs/en/diagrams/architecture.png`, `docs/es/diagramas/arquitectura.png`).
- English-only codebase: all `app/` comments and docstrings translated to English (PEP 8 / PEP 257 Google style), `TODO(Phase 2)` normalized.

### Changed
- Extended English translation to `tests/`, `config/settings.yaml`, `pyproject.toml`, and `packaging/` scripts (comments/docstrings).
- Error messages and exception strings unified to English; tests updated to match English patterns.
- Version bumped to `1.1.0` (single source `app/__init__.py:__version__`).

## [1.0.0] - 2026-08-11

### Added
- First stable production release.
- Reproducible packaging with `pyproject.toml` (entry point `biovision`).
- Security documentation (`SECURITY.md`) and contribution guide (`CONTRIBUTING.md`).
- Architecture and UML diagrams generated in `docs/diagrams/`.

### Fixed
- Centralized versioning in `app/__init__.py` as single source of truth; the version
  propagates to `settings.yaml`, the main window, and the sidebar footer.
- Dead dependency `seaborn` removed from `requirements.txt`.

### Notes
- AI models (`buffalo_l`) are downloaded automatically on first
  launch; see `docs/en/installation_guide.md` / `docs/es/guia_instalacion.md` for air-gapped environments.

[1.1.0]: https://github.com/JhosepAC/facial_recognition_suite/releases/tag/v1.1.0
[1.0.0]: https://github.com/JhosepAC/facial_recognition_suite/releases/tag/v1.0.0
