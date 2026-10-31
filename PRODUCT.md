# Product

<!-- impeccable:product-schema 1 -->

## Platform
Windows-first native desktop (Python/PySide6), with Linux support.

## Product Purpose
BioVision Suite / FaceScan provides local facial enrollment, comparison, search,
webcam recognition, forensic video analysis, statistics, and account administration.

## Capabilities and Constraints
Preserve existing workflows, permission checks, authentication, session locking,
bilingual catalogs, local inference, and SQLite persistence. Never use real biometric
data in previews. The repository documents the existing features and tests.

## Brand Commitments
The user requests a complete modern dark redesign inspired by Supabase, retaining
functionality, on branch feature/new. Favor intuitive workflows and restrained UI.

## Open Decisions
The user prioritizes webcam recognition and video analysis. Every module remains in
scope; no new biometric inference capability is required.
