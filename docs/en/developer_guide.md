# Developer Guide — BioVision Suite

How to extend the project without breaking its architecture. Before reading
this guide you should have read `technical_manual.md` (architecture and data
model).

---

## 1. Setting Up the Development Environment

```bash
python -m venv .venv
source .venv/bin/activate   # or .venv\Scripts\activate on Windows
pip install -r requirements.txt
pytest tests/ -v             # confirm everything passes before starting
```

## 2. Project Conventions

- **Language**: domain table/column/variable names in Spanish
  (`Person.nombre`, `apellidos`), technical identifiers in English where
  standard (`session`, `repository`, `service`). User-facing messages and
  docstrings, always in Spanish.
- **Typing**: `from __future__ import annotations` and type annotations on
  public signatures (`def get(self, uuid: str) -> Person | None`) are used.
- **Never** import PySide6 inside `app/core`, `app/database`, `app/vision`,
  `app/recognition`, or `app/services`. Those layers must be testable without a
  GUI.
- **Never** execute SQL or call `FaceEngine`/`RecognitionService` directly from
  a widget in `app/gui/widgets/`; always go through a `*Service`.
- Every service method that modifies sensitive data must log an audit line:
  `audit_logger.info("Action | field={} | by={}", ...)`.
- Domain exceptions inherit from `BioVisionError` (`app/core/exceptions.py`);
  avoid raising generic `Exception` from services.

## 3. How to Add a New Module (Guided Example)

Suppose you want to add a **"Groups"** module (free-form labels for people).
Steps:

### 3.1. Data Model
Add the table in `app/database/models.py`:

```python
class Group(Base):
    __tablename__ = "groups"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    nombre: Mapped[str] = mapped_column(String(100), unique=True)
```

No need to write migrations by hand: `init_db()` calls
`Base.metadata.create_all()`, which creates missing tables. (For changes to
already-existing tables in a database with real data, an explicit migration
would be needed — the project does not yet include Alembic; see Roadmap.)

### 3.2. Repository
Create `app/database/repositories/group_repository.py` following the pattern
of `person_repository.py`: a class with `session` injected via constructor and
methods `add`, `get`, `list_all`, `delete`.

### 3.3. Service
Create `app/services/group_service.py`. If it needs to combine with existing
logic (for example, associating groups with people), also inject
`PersonRepository` or reuse `PersonService`.

### 3.4. Permission
Add the constant in `app/core/permissions.py`:

```python
PERM_GRUPOS = "grupos.usar"
ALL_PERMISSIONS.append(PERM_GRUPOS)
PERMISSION_LABELS[PERM_GRUPOS] = "Gestionar grupos"
```
Decide which default roles it is added to in `DEFAULT_ROLES` (roles already
seeded in existing installations are not updated automatically; you would need
to add it manually from *Administration → Roles*, or write a data migration).

### 3.5. Interface Widget
Create `app/gui/widgets/groups_widget.py` following the pattern of
`person_search.py`: build its own session with `with get_session() as session:`
and call `GroupService`.

### 3.6. Register in Navigation
In `app/gui/widgets/sidebar.py`, add the entry to `NAV_ITEMS`. In
`app/gui/main_window.py`, add `"grupos": PERM_GRUPOS` to `NAV_PERMISSIONS` and
`"grupos": GroupsWidget()` to `self.pages`.

### 3.7. Tests
Add `tests/test_group_service.py` with an in-memory SQLite session (see any
existing `tests/test_*.py` file as a template for the `session` fixture).

## 4. How to Add a New Export Format

Edit `app/services/export_service.py`:
- For a new tabular format (e.g., XML), add the corresponding branch in
  `_write_dataframe()` and the name to `SUPPORTED_TABULAR_FORMATS`.
- For a non-tabular report, follow the pattern of `export_statistics_pdf()`
  (uses `reportlab.platypus`).

## 5. How to Add a New Statistics Chart

In `app/services/statistics_service.py`:
1. Add an `xxx_df()` method that returns a `pandas.DataFrame` with the
   aggregated query (use SQLAlchemy `func` for aggregations in the DB engine,
   do not fetch everything to Python and aggregate in memory unless volume is
   small).
2. Add a `chart_xxx()` method that builds the figure with `_style_axes()` to
   keep the consistent dark visual theme.
3. In `app/gui/widgets/statistics_widget.py`, add another `ChartCard` to the
   grid and call `stats.chart_xxx()` in `refresh()`.

## 6. AI Models: Changing or Adding a Detection Backend

`app/vision/face_engine.py` encapsulates all InsightFace dependency. To support
another backend (for example, a pure MediaPipe detector):

1. Create a class with the same public interface as `FaceEngine`
   (`analyze(image) -> list[FaceResult]`, `largest_face(image)`).
2. Select the backend according to `settings.vision.detector_backend` instead
   of instantiating `FaceEngine` directly where it is used.
3. **Do not** change `FaceResult` (shared dataclass) without reviewing all
   places that consume it (`RecognitionService`, `VideoService`,
   `face_quality.py`).

## 7. Running and Writing Tests

```bash
pytest tests/ -v                      # full suite
pytest tests/test_video_service.py -v # single file
pytest tests/ -k "lockout"            # by test name
```

Pattern used in all tests: a `session` fixture that creates a SQLite engine in
a temporary file (`tmp_path`) and runs `Base.metadata.create_all()`, without
depending on PySide6 or real AI models (replaced by test doubles via
`monkeypatch` when the test exercises `RecognitionService`, as in
`test_video_service.py`).

Before opening a change: `python -m py_compile $(find app tests -name "*.py")`
and `pytest tests/` must pass without errors.

## 8. Suggested Commit/Change Structure

When modifying a layer, review cascading impact following the architecture
diagram: a change in `app/database/models.py` may affect repositories,
services, tests and — if it changes fields used in the UI — also widgets. A
change in `app/gui/` normally should not require touching lower layers.

## 9. Things the Project Deliberately Does NOT Do (and Why)

- **Does not** use an async ORM or async/await: PySide6 runs on a single event
  thread by default, and DB operations are fast (local SQLite); async
  complexity is not justified here.
- **Does not** include Alembic (versioned migrations): being a single-user/
  single-installation desktop app, `create_all()` is sufficient for
  development. For distribution with updates over already-populated databases,
  it would be worth incorporating.
- **Does not** allow the GUI to call `FaceEngine` directly "for convenience":
  even at the cost of an extra layer, maintaining that barrier is what allows
  testing all recognition logic without PySide6 and without downloading AI
  models in CI.
