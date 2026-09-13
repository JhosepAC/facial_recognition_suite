# Guía del Desarrollador — BioVision Suite

Cómo extender el proyecto sin romper su arquitectura. Antes de leer
esta guía deberías haber leído `manual_tecnico.md` (arquitectura y modelo de datos).

---

## 1. Configuración del Entorno de Desarrollo

```bash
python -m venv .venv
source .venv/bin/activate   # o .venv\Scripts\activate en Windows
pip install -r requirements.txt
pytest tests/ -v             # confirma que todo pasa antes de empezar
```

## 2. Convenciones del Proyecto

- **Idioma**: nombres de tablas/columnas/variables en español
  (`Person.nombre`, `apellidos`), identificadores técnicos en inglés donde
  es estándar (`session`, `repository`, `service`). Mensajes de cara al usuario y
  docstrings, siempre en español.
- **Tipado**: se usa `from __future__ import annotations` y anotaciones de tipo en
  firmas públicas (`def get(self, uuid: str) -> Person | None`).
- **Nunca** importes PySide6 dentro de `app/core`, `app/database`, `app/vision`,
  `app/recognition` o `app/services`. Esas capas deben ser testeables sin
  GUI.
- **Nunca** ejecutes SQL ni llames a `FaceEngine`/`RecognitionService` directamente desde
  un widget en `app/gui/widgets/`; siempre pasa por un `*Service`.
- Todo método de servicio que modifique datos sensibles debe registrar una línea de auditoría:
  `audit_logger.info("Accion | field={} | by={}", ...)`.
- Las excepciones de dominio heredan de `BioVisionError` (`app/core/exceptions.py`);
  evita lanzar `Exception` genérico desde los servicios.

## 3. Cómo Añadir un Nuevo Módulo (Ejemplo Guiado)

Supón que quieres añadir un módulo **"Grupos"** (etiquetas de forma libre para personas).
Pasos:

### 3.1. Modelo de Datos
Añade la tabla en `app/database/models.py`:

```python
class Group(Base):
    __tablename__ = "groups"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    nombre: Mapped[str] = mapped_column(String(100), unique=True)
```

No necesitas escribir migraciones a mano: `init_db()` llama a
`Base.metadata.create_all()`, que crea las tablas faltantes. (Para cambios en
tablas ya existentes en una base de datos con datos reales, se necesitaría una migración
explícita — el proyecto aún no incluye Alembic; ver Roadmap.)

### 3.2. Repositorio
Crea `app/database/repositories/group_repository.py` siguiendo el patrón
de `person_repository.py`: una clase con `session` inyectada vía constructor y
métodos `add`, `get`, `list_all`, `delete`.

### 3.3. Servicio
Crea `app/services/group_service.py`. Si necesita combinarse con lógica existente
(por ejemplo, asociar grupos con personas), también inyecta
`PersonRepository` o reutiliza `PersonService`.

### 3.4. Permiso
Añade la constante en `app/core/permissions.py`:

```python
PERM_GRUPOS = "grupos.usar"
ALL_PERMISSIONS.append(PERM_GRUPOS)
PERMISSION_LABELS[PERM_GRUPOS] = "Gestionar grupos"
```
Decide a qué roles por defecto se añade en `DEFAULT_ROLES` (los roles ya
sembrados en instalaciones existentes no se actualizan automáticamente; habría que
añadirlo manualmente desde *Administración → Roles*, o escribir una migración de datos).

### 3.5. Widget de Interfaz
Crea `app/gui/widgets/groups_widget.py` siguiendo el patrón de
`person_search.py`: construye su propia sesión con `with get_session() as session:`
y llama a `GroupService`.

### 3.6. Registrar en Navegación
En `app/gui/widgets/sidebar.py`, añade la entrada a `NAV_ITEMS`. En
`app/gui/main_window.py`, añade `"grupos": PERM_GRUPOS` a `NAV_PERMISSIONS` y
`"grupos": GroupsWidget()` a `self.pages`.

### 3.7. Pruebas
Añade `tests/test_group_service.py` con una sesión SQLite en memoria (ver cualquier
archivo existente `tests/test_*.py` como plantilla para el fixture `session`).

## 4. Cómo Añadir un Nuevo Formato de Exportación

Edita `app/services/export_service.py`:
- Para un nuevo formato tabular (ej. XML), añade la rama correspondiente en
  `_write_dataframe()` y el nombre a `SUPPORTED_TABULAR_FORMATS`.
- Para un informe no tabular, sigue el patrón de `export_statistics_pdf()`
  (usa `reportlab.platypus`).

## 5. Cómo Añadir un Nuevo Gráfico de Estadísticas

En `app/services/statistics_service.py`:
1. Añade un método `xxx_df()` que devuelva un `pandas.DataFrame` con la
   consulta agregada (usa `func` de SQLAlchemy para agregaciones en el motor de BD,
   no traigas todo a Python y agregues en memoria salvo que el volumen sea pequeño).
2. Añade un método `chart_xxx()` que construya la figura con `_style_axes()` para
   mantener el tema visual oscuro consistente.
3. En `app/gui/widgets/statistics_widget.py`, añade otra `ChartCard` al
   grid y llama a `stats.chart_xxx()` en `refresh()`.

## 6. Modelos de IA: Cambiar o Añadir un Backend de Detección

`app/vision/face_engine.py` encapsula toda la dependencia de InsightFace. Para soportar
otro backend (por ejemplo, un detector puro de MediaPipe):

1. Crea una clase con la misma interfaz pública que `FaceEngine`
   (`analyze(image) -> list[FaceResult]`, `largest_face(image)`).
2. Selecciona el backend según `settings.vision.detector_backend` en lugar
   de instanciar `FaceEngine` directamente donde se usa.
3. **No** cambies `FaceResult` (dataclass compartido) sin revisar todos los
   lugares que lo consumen (`RecognitionService`, `VideoService`,
   `face_quality.py`).

## 7. Ejecutar y Escribir Pruebas

```bash
pytest tests/ -v                      # suite completa
pytest tests/test_video_service.py -v # un solo archivo
pytest tests/ -k "lockout"            # por nombre de test
```

Patrón usado en todas las pruebas: un fixture `session` que crea un engine SQLite en
un archivo temporal (`tmp_path`) y ejecuta `Base.metadata.create_all()`, sin
depender de PySide6 ni de modelos reales de IA (reemplazados por dobles de prueba vía
`monkeypatch` cuando la prueba ejercita `RecognitionService`, como en
`test_video_service.py`).

Antes de abrir un cambio: `python -m py_compile $(find app tests -name "*.py")`
y `pytest tests/` deben pasar sin errores.

## 8. Estructura Sugerida de Commits/Cambios

Al modificar una capa, revisa el impacto en cascada siguiendo el diagrama de arquitectura:
un cambio en `app/database/models.py` puede afectar repositorios,
servicios, pruebas y — si cambia campos usados en la UI — también widgets. Un
cambio en `app/gui/` normalmente no debería requerir tocar capas inferiores.

## 9. Cosas que el Proyecto Deliberadamente NO Hace (y Por Qué)

- **No** usa ORM asíncrono ni async/await: PySide6 corre en un solo hilo de eventos por defecto,
  y las operaciones de BD son rápidas (SQLite local); la complejidad asíncrona no se justifica aquí.
- **No** incluye Alembic (migraciones versionadas): al ser una app de escritorio mono-usuario/
  mono-instalación, `create_all()` es suficiente para desarrollo. Para distribución con actualizaciones sobre bases de datos ya pobladas,
  valdría la pena incorporarlo.
- **No** permite que la GUI llame a `FaceEngine` directamente "por conveniencia":
  incluso a costa de una capa extra, mantener esa barrera es lo que permite
  testear toda la lógica de reconocimiento sin PySide6 y sin descargar modelos de IA en CI.
