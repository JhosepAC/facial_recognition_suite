# Guía de Instalación — BioVision Suite

Esta guía cubre la instalación en **Windows** (plataforma principal)
y notas para Linux/macOS. Todo el procesamiento es local: no se requieren cuentas, licencias
ni conexión a Internet salvo para la descarga inicial de dependencias y del paquete de modelos de IA.

---

## 1. Requisitos Previos

| Componente | Versión Recomendada | Notas |
|---|---|---|
| Python | 3.11 o 3.12 | 64-bit. Verificar con `python --version` |
| Sistema Operativo | Windows 10/11 | También compatible con Linux y macOS |
| Espacio en Disco | ~2 GB | Incluye dependencias + paquete de modelos IA (~300 MB) |
| Cámara Web | Opcional | Solo necesaria para el módulo de reconocimiento en vivo |
| GPU NVIDIA + CUDA | Opcional | Acelera la inferencia; sin GPU funciona en CPU |

No se requiere base de datos de servidor (se usa SQLite embebido), ni cuentas en la nube,
claves API o licencias comerciales.

---

## 2. Instalación en Windows

### 2.1. Instalar Python

Descarga Python 3.12 desde [python.org](https://www.python.org/downloads/)
y, durante la instalación, marca **"Add python.exe to PATH"**.

Verifica en una terminal (PowerShell o CMD):

```powershell
python --version
```

### 2.2. Obtener el Proyecto

Descomprime el archivo `.zip` del proyecto en una carpeta, por ejemplo
`C:\BioVisionSuite\`.

### 2.3. Crear un Entorno Virtual

```powershell
cd C:\BioVisionSuite
python -m venv .venv
.venv\Scripts\activate
```

La terminal debe mostrar el prefijo `(.venv)` una vez activado.

### 2.4. Instalar Dependencias

```powershell
pip install --upgrade pip
pip install -r requirements.txt
```

Esto instala, entre otros: PySide6 (UI), InsightFace + ONNX Runtime
(IA), OpenCV, SQLAlchemy, Matplotlib, ReportLab, openpyxl, bcrypt y
cryptography. La instalación toma unos minutos la primera vez.

> **Aceleración por GPU (opcional):** si tienes una GPU NVIDIA con CUDA
> instalada, reemplaza `onnxruntime` por `onnxruntime-gpu`:
> ```powershell
> pip uninstall onnxruntime
> pip install onnxruntime-gpu
> ```
> y luego edita `config/settings.yaml`, sección `vision`, y cambia `ctx_id: -1`
> a `ctx_id: 0`.

### 2.5. Primer Inicio

```powershell
python -m app.main
```

En el primer inicio ocurren dos cosas automáticamente:

1. **Descarga del paquete de modelos IA** (`buffalo_l`, ~300 MB) a
   `%USERPROFILE%\.insightface\models\`. Se requiere conexión a Internet
   *solo esta vez*; en los siguientes inicios la app funciona 100% offline.
2. **Creación de la base de datos SQLite** en `data\biovision.db`.

La aplicación mostrará entonces un asistente para **crear la cuenta de
administrador** (usuario + contraseña). A partir de entonces, cada vez que se abra
la app solicitará inicio de sesión.

---

## 3. Instalación en Linux / macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
python -m app.main
```

En Linux, si `opencv-python` tiene problemas para abrir la cámara, instala las
dependencias de video del sistema (por ejemplo `sudo apt install
libgl1 v4l-utils` en distribuciones basadas en Debian/Ubuntu).

---

## 4. Verificar que Todo Funciona

Al iniciar sesión por primera vez deberías ver el **Dashboard** con
contadores en cero. Para una comprobación rápida de cada módulo:

1. **Personas** → registra una persona con una foto de rostro.
2. **Comparador** → compara esa misma foto contra sí misma; debe mostrar
   similitud del 100%.
3. **Cámara Web** (si tienes cámara) → pulsa "Iniciar"; deberías verte
   con un recuadro y tu nombre si la cámara enfoca tu rostro.

---

## 5. Solución de Problemas

| Síntoma | Causa Probable | Solución |
|---|---|---|
| `ModuleNotFoundError` al ejecutar `python -m app.main` | Entorno virtual no activado o dependencias no instaladas | Verifica el prefijo `(.venv)` en la terminal y repite `pip install -r requirements.txt` |
| Fallo de carga del modelo IA / `ModelLoadError` | Sin conexión a Internet en el primer inicio o descarga interrumpida | Verifica la conexión e intenta de nuevo; revisa `%USERPROFILE%\.insightface\models\` |
| "Could not open camera index 0" | La cámara está en uso por otra app o el índice es incorrecto | Cierra otras apps que usen la cámara; prueba cambiar el índice en el selector del módulo Cámara |
| La app se vuelve muy lenta al analizar video | CPU limitada procesando muchos fotogramas | Aumenta `video.sample_interval_frames` en `config/settings.yaml` (procesar menos fotogramas) |
| Olvido de contraseña de administrador | — | Otro administrador puede restablecerla desde *Administración → Usuarios*. Si no hay administrador disponible, ver la nota de recuperación abajo |
| "Cuenta bloqueada temporalmente" | Se superó el número configurado de intentos fallidos | Espera el tiempo indicado o pide a un administrador que reactive la cuenta desde *Administración → Usuarios* |

### Recuperación si se Pierde el Acceso de Administrador

BioVision Suite no tiene cuenta de administrador oculta ni contraseña maestra
(por diseño, para no debilitar la seguridad). Si se pierde el acceso a todas las cuentas
de administrador, el único camino de recuperación es:

1. Cierra la aplicación.
2. Haz una copia de seguridad de `data/biovision.db` por si acaso.
3. Elimina la tabla de usuarios manualmente con un cliente SQLite
   (`DELETE FROM users;`), o borra `data/biovision.db` por completo si
   es aceptable perder los datos biométricos.
4. Reabre la app: al no detectar usuarios, mostrará de nuevo el asistente de
   configuración inicial.

---

## 6. Actualización de la Aplicación

Al reemplazar los archivos del proyecto por una versión más nueva, conserva la carpeta `data/`
(contiene la base de datos y fotos) y `config/.secret.key` (clave local de cifrado)
para no perder información.
