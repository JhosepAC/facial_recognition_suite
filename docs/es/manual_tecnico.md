# Manual Técnico — BioVision Suite

Documento de referencia técnica: arquitectura, patrones de diseño, modelo de datos, algoritmos
clave y configuración. Dirigido a quienes necesitan entender *cómo* funciona internamente el
sistema (soporte avanzado, auditoría técnica, evaluación de seguridad), no necesariamente a quienes
modificarán el código — para eso ver la *Guía del Desarrollador*.

---

## 1. Visión General

BioVision Suite es una aplicación de escritorio (PySide6) para registro facial,
búsqueda, comparación y reconocimiento, con **todo el procesamiento local**: no
depende de servidores externos, APIs de pago o servicios en la nube. La IA se ejecuta en ONNX
Runtime (CPU o GPU CUDA), y la persistencia usa SQLite embebido.

## 2. Arquitectura por Capas

El proyecto sigue una arquitectura por capas con separación estricta entre UI,
lógica de negocio, IA y acceso a datos:

![Diagrama de arquitectura](diagramas/arquitectura.png)

| Capa | Carpeta | Responsabilidad |
|---|---|---|
| Interfaz | `app/gui/` | PySide6: ventanas, widgets, navegación, presentación. No contiene lógica de negocio ni acceso directo a BD. |
| Servicios | `app/services/` | Lógica de negocio y orquestación. La única capa que la GUI debe invocar. |
| Reconocimiento | `app/recognition/` | Comparación 1:1, búsqueda 1:N, reconocimiento multi-rostro. |
| Visión | `app/vision/` | Envoltorio sobre InsightFace/ONNX Runtime; detección, embeddings, calidad de imagen, muestreo de video. |
| Base de Datos | `app/database/` | Modelos ORM, sesiones, repositorios (Repository Pattern). |
| Núcleo Transversal | `app/core/` | Configuración, logging, excepciones, seguridad (cifrado), catálogo de permisos. Usado por todas las capas. |

**Regla de dependencia:** cada capa solo conoce las capas inferiores en la tabla.
La GUI nunca importa `app/database` o `app/vision` directamente; siempre pasa
a través de `app/services`.

## 3. Patrones de Diseño Aplicados

- **Repository Pattern** (`app/database/repositories/`): aísla
  las consultas SQLAlchemy del resto de la aplicación. Cada repositorio expone
  operaciones CRUD simples sobre un agregado (ej. `PersonRepository`,
  `VideoJobRepository`).
- **Service Layer**: cada `*Service` en `app/services/` orquesta uno o
  más repositorios y, cuando aplica, el motor de visión/reconocimiento. Es
  el único punto de entrada para la GUI.
- **Inyección de dependencias por constructor**: los servicios reciben la `Session` de SQLAlchemy
  en el constructor (`PersonService(session)`), nunca la crean ellos mismos. Facilita las pruebas con sesiones en memoria.
- **Singleton perezoso**: `FaceEngine` (app/vision/face_engine.py) carga los modelos IA
  solo una vez, en el primer uso real, no al importar el módulo — evita bloquear
  el inicio de la GUI.
- **Unit of Work simplificado**: `get_session()` (app/database/session.py) es un
  gestor de contexto que abre una sesión, hace commit al salir limpio y rollback
  en caso de excepción.
- **Separación GUI / lógica**: los widgets en `app/gui/widgets/` construyen su propia
  sesión vía `with get_session() as session:` y llaman a un servicio; nunca
  ejecutan consultas SQLAlchemy directamente ni llaman a InsightFace directamente.

## 4. Modelo de Datos

![Diagrama de clases UML](diagramas/uml_clases.png)

Puntos relevantes del modelo (`app/database/models.py`):

- **Person** es el agregado raíz del registro biométrico. `uuid` (no un
  id autoincremental) es su clave primaria, por lo que permanece estable si se sincroniza
  entre instalaciones en el futuro.
- **Photo** y **FaceEmbedding** están separados intencionalmente: una foto puede
  tener más de un embedding (por ejemplo, si se recalcula con otro
  modelo), y un embedding siempre sabe de qué foto proviene.
- **FaceEmbedding.vector** almacena el vector de 512 dimensiones como `bytes` crudos
  (`float32`), no como JSON, por eficiencia de espacio y velocidad de lectura (ver
  `app/utils/vector_utils.py`).
- **RecognitionEvent** unifica el historial de reconocimiento sin importar el origen
  (`webcam`, `video`, `image`), permitiendo que Dashboard y Estadísticas consulten una
  sola tabla.
- **VideoDetection** es más granular que `RecognitionEvent`: almacena
  `frame_number`, `timestamp_seg` y el `bbox` exacto, necesario para la
  navegación de video. Cada detección de video genera *ambos* registros: un `VideoDetection`
  (detalle) y un `RecognitionEvent` (historial unificado).
- **User** y **Role** son independientes del modelo `Person`: un usuario del sistema
  (quien opera la app) no es lo mismo que una persona registrada en la
  base de datos biométrica.
- **SecureSetting** almacena `value_encrypted` como bytes cifrados (Fernet/AES);
  el valor en texto plano nunca toca el disco.

## 5. Algoritmos Clave y Flujos

### 5.1. Pipeline de Reconocimiento Facial

```
imagen/fotograma (BGR)
   → FaceEngine.analyze()          [InsightFace: SCRFD/RetinaFace + ArcFace]
   → lista de FaceResult (bbox, landmarks, embedding 512-d, det_score)
   → face_quality.evaluate()       [nitidez, iluminación, inclinación]
   → (si enrolamiento) → guardar FaceEmbedding en BD
   → (si búsqueda) → RecognitionService._rank_1n()  [índice ANN FAISS o lineal exacto]
```

### 5.2. Comparación y Umbral de Decisión

La similitud entre dos embeddings se calcula como **similitud/distancia coseno**
(`app/utils/vector_utils.py`):

```
similarity = (a · b) / (‖a‖ · ‖b‖)         ∈ [-1, 1]
distance = 1 - similarity                  ∈ [0, 2]
```

Una comparación se considera **coincidencia** si `distance ≤
recognition.match_threshold` (por defecto `0.40`, configurable en
`config/settings.yaml`). El porcentaje mostrado en la UI es una **transformación logística
calibrada** de la similitud (`matcher.similarity_to_percent`):
centrada en el umbral, devuelve ~50% justo en el umbral, cerca del 100%
muy por encima y cerca del 0% muy por debajo (la línea ingenua `(sim+1)/2` daría ~50%
para rostros no relacionados y sería engañosa).

### 5.3. Búsqueda 1:N

`RecognitionService._load_gallery()` carga **todos** los embeddings de la
base de datos biométrica (con caché por marcador de cambio: solo relee cuando el conjunto
varía). La búsqueda en sí usa un **índice ANN** (`app/recognition/ann_index.py`):

- Se construye un índice **FAISS** en memoria (coseno = producto interno sobre
  vectores unitarios). Por debajo de `recognition.ann_ivf_min_size` usa `IndexFlatIP`
  (exhaustivo, vectorizado en C++: mismo resultado que búsqueda lineal pero mucho más rápido);
  por encima, `IndexIVFFlat` (ANN real) con `nprobe` conservador para mantener
  el recall alto.
- El índice se **cachea por proceso** y se reconstruye solo cuando la galería
  cambia (marcador de (count, max_id)).
- **Fallback automático**: si `faiss-cpu` no está instalado, si
  `recognition.ann_enabled` es `false`, o si la galería es menor que
  `ann_min_size`, se usa búsqueda lineal exacta (`matcher.rank_candidates()`),
  con exactamente el mismo contrato de resultado.

El rechazo de duplicados en el enrolamiento (`_reject_duplicate`) permanece como escaneo lineal
exacto (con galería cacheada), ya que debe detectar cualquier colisión biométrica
sin riesgo de falsos negativos.

El índice puede **persistirse en disco** (`recognition.ann_persist: true` +
`ann_index_dir`) para evitar reconstruir el IVFFlat (entrenamiento k-means) en cada
inicio, y su **recall** puede medirse y calibrarse con el benchmark integrado
(`app/recognition/ann_benchmark.py`, también accesible desde
Administración → Parámetros de Reconocimiento).

### 5.4. Análisis de Video

`VideoService.analyze_video()` (app/services/video_service.py):

1. Abre el video con `VideoReader` (OpenCV) y valida extensión/existencia.
2. Itera el video **muestreando** 1 de cada
   `video.sample_interval_frames` fotogramas (por defecto 15 → ~cada 0.5 s a 30 fps),
   no cada fotograma. El intervalo puede sobreescribirse por llamada (`sample_interval`)
   para el selector de calidad de muestreo de la GUI.
3. Cada fotograma muestreado se **redimensiona** a `video.max_processing_width` antes
   de pasar al detector (rendimiento); el bbox resultante se **reescala**
   de vuelta al tamaño original (`scale_bbox()`) para recortar evidencia nítida del
   fotograma sin redimensionar.
4. Cada rostro reconocido genera un `VideoDetection` + un `RecognitionEvent`,
   y opcionalmente un recorte de evidencia en `data/video_evidence/`.
5. El progreso se reporta vía callback cada 5 muestras (evita inundar la UI
   con actualizaciones).
6. `VideoService.export_detections(job_id, path, fmt)` exporta detecciones a
   **CSV** o **Excel** (`fmt="excel"`); Excel tiene dos hojas — *Resumen*
   (KPIs y personas detectadas) y *Detecciones* (cabeceras coloreadas, bordes,
   filas alternas, resaltado de estado, filas congeladas y filtrado automático de columna).

### 5.5. Autenticación y Bloqueo Automático

`AuthService.authenticate()` (app/services/auth_service.py):

- Las contraseñas se almacenan con **bcrypt** (`hash_password`/`verify_password`),
  nunca en texto plano.
- Tras cada intento fallido se incrementa `User.intentos_fallidos`; cuando
  se alcanza `security.lockout_attempts`, se establece `User.bloqueado_hasta = now +
  security.lockout_minutes`. Mientras esa fecha no haya pasado, el login se
  rechaza **incluso con la contraseña correcta**.
- Un login exitoso resetea `intentos_fallidos` y `bloqueado_hasta`.

### 5.6. Permisos Basados en Roles

`Role.permisos_csv` almacena una lista de permisos separada por comas (ver
`app/core/permissions.py`), o `"*"` como comodín para "todos los permisos".
`AuthService.has_permission()` decide si un usuario puede realizar una acción;
`MainWindow` usa el mismo cálculo para decidir qué botones de la barra lateral mostrar
(`NAV_PERMISSIONS` en `app/gui/main_window.py`).

### 5.7. Cifrado de Configuración Sensible

`app/core/security.py` usa **Fernet** (AES-128-CBC + HMAC-SHA256, de la
librería `cryptography`) con una clave simétrica generada localmente en el primer uso
(`config/.secret.key`, fuera de control de versiones). Un valor cifrado con esta
clave no puede descifrarse con ninguna otra (verificado en `tests/test_auth_and_admin.py`).

### 5.8. Bloqueo de Sesión por Inactividad

`MainWindow` instala un `eventFilter` a nivel de aplicación que registra el
timestamp de la última interacción (movimiento de ratón, clic, pulsación de tecla). Un
`QTimer` verifica cada 30 segundos si se ha superado `security.session_timeout_minutes`;
si es así, se muestra de nuevo la pantalla de login en "modo bloqueo"
(usuario fijo, solo pide contraseña).

## 6. Referencia de Configuración (`config/settings.yaml`)

| Sección | Clave | Significado |
|---|---|---|
| `vision` | `detector_model` | Paquete de modelo InsightFace (`buffalo_l` por defecto) |
| `vision` | `ctx_id` | `-1` = CPU, `0` = primera GPU CUDA |
| `vision` | `min_face_confidence` | Confianza mínima de detección para aceptar un rostro |
| `recognition` | `match_threshold` | Distancia coseno máxima para considerar coincidencia |
| `recognition` | `top_k_results` | Cuántos candidatos devolver en búsquedas 1:N |
| `video` | `sample_interval_frames` | Cada cuántos fotogramas se analiza uno |
| `video` | `max_processing_width` | Ancho máximo antes de redimensionar para detección |
| `security` | `lockout_attempts` / `lockout_minutes` | Política de bloqueo de cuenta |
| `security` | `session_timeout_minutes` | Minutos de inactividad antes de bloquear la sesión |
| `storage` | `photos_dir`, `thumbnails_dir`, `evidence_dir` | Rutas de almacenamiento de archivos |

## 7. Logging y Auditoría

`app/core/logger.py` configura **loguru** con tres salidas:

1. Consola (nivel `INFO` por defecto).
2. `logs/app.log` — log general de la aplicación, con rotación.
3. `logs/audit.log` — solo eventos marcados de auditoría (`audit_logger.info(...)`):
   creaciones/eliminaciones de personas y usuarios, logins, bloqueos, exportaciones, restauraciones,
   limpieza de BD. Retención de 365 días. Visible desde *Administración → Auditoría* en la
   propia app.

## 8. Pruebas Automatizadas

El proyecto incluye **101 pruebas** (`pytest tests/`) que cubren las capas de servicio y
datos sin depender de PySide6 ni de modelos reales de IA (reemplazados por dobles de prueba cuando se necesita):

| Archivo | Cubre |
|---|---|
| `test_database_and_matcher.py` | Repositorios, serialización de vectores, matcher |
| `test_video_service.py` | Extracción de fotogramas, orquestación de análisis de video |
| `test_statistics_and_export.py` | Consultas agregadas, gráficos, exportación CSV/Excel/JSON/PDF/SQLite |
| `test_auth_and_admin.py` | Autenticación, bloqueo, permisos, usuarios, roles, cifrado, limpieza, restauración |
| `test_calibration.py` | Calibración de análisis facial, edad/género, reanálisis de fotos |

## 9. Limitaciones Conocidas

- La búsqueda 1:N con índice ANN (FAISS) aplica cuando `faiss-cpu` está instalado,
  `recognition.ann_enabled` es `true`, y la galería supera `ann_min_size`;
  de lo contrario se usa búsqueda lineal exacta (mismo contrato de resultado). El modo `IndexIVFFlat`
  es aproximado: es aconsejable calibrar `ann_nprobe` con el benchmark de recall integrado en bases de datos muy grandes.
- El "análisis facial extendido" usa clasificadores heurísticos geométricos y de textura
  sobre MediaPipe FaceMesh (no clasificadores neuronales entrenados para gafas/barba/mascarilla);
  son aproximaciones razonables en tomas frontales nítidas, no un veredicto biométrico. Los umbrales pueden calibrarse en *Administración → Calibración Facial*.
- La restauración de base de datos requiere reiniciar manualmente la aplicación (no hay hot-swap
  del engine en tiempo de ejecución).
- Los permisos son por módulo completo, no por acción específica dentro de un módulo
  (ver Roadmap en README).
