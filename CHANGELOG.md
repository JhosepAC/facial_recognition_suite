# Changelog

All notable changes to this project are documented in this file.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
The version is managed in `app/__init__.py` (`__version__`).

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
  launch; see `docs/guia_instalacion.md` for air-gapped environments.

[1.0.0]: https://example.com/tag/v1.0.0
