# Manual de usuario — FaceScan

Guía de uso de la plataforma de análisis biométrico facial, módulo por
módulo. Está escrita para personas que van a operar la aplicación día a
día (registrar personas, buscar, analizar video, revisar estadísticas),
no para desarrolladores — para eso existe la *Guía para desarrolladores*.

---

## 1. Inicio de sesión

Al abrir la aplicación se solicita **usuario y contraseña**. FaceScan
no tiene cuentas por defecto: la primera vez que se ejecuta, un
asistente guía la creación de la cuenta de administrador.

- Tras **5 intentos fallidos** (configurable), la cuenta se bloquea
  temporalmente por seguridad.
- Si la aplicación queda **inactiva** un tiempo prolongado, se bloquea
  automáticamente y pide reingresar la contraseña para continuar (o cerrar
  sesión).
- El botón **"Cerrar sesión"**, en la esquina superior derecha, permite que
  otra persona inicie sesión con su propia cuenta sin cerrar la aplicación.

Qué módulos ves en la barra lateral depende de tu **rol**:

| Rol | Puede ver |
|---|---|
| Administrador | Todos los módulos, incluida Administración |
| Operador | Dashboard, Personas, Comparador, Búsqueda, Webcam, Video, Estadísticas |
| Visualizador | Dashboard, Búsqueda, Estadísticas (solo consulta) |

---

## 2. Dashboard

Pantalla de inicio con un resumen general:

- **Personas registradas**, **eventos de reconocimiento** (hoy y total),
  **confianza promedio**.
- **Actividad reciente**: últimos reconocimientos, indicando si hubo
  coincidencia o no, su origen (webcam/video/imagen) y la confianza.

---

## 3. Personas — registro

Este módulo se usa **exclusivamente para dar de alta personas**: la ficha
de datos y su dataset de fotografías. No muestra la lista de personas
registradas (para buscar o revisar registros existentes usa el módulo
**Búsqueda**).

1. Completa el formulario de la izquierda. **Nombre** y **Apellidos** son
   obligatorios (marcados con `*`); el resto — alias, sexo, edad, empresa,
   departamento, cargo, contacto, observaciones — es opcional. El correo se
   valida automáticamente.
2. Agrega las fotografías del dataset. Puedes **arrastrar y soltar** fotos
   en el recuadro de la derecha, pulsar **"+ Añadir fotos"** para
   seleccionarlas desde el disco, o usar **"Webcam"** para capturar una foto
   al momento (con posibilidad de reintentar). La primera foto quedará
   marcada como principal.
3. Pulsa **"Guardar persona"**. En segundo plano se crea la persona y cada
   foto se procesa automáticamente: se detecta el rostro principal y se
   extrae su vector biométrico (*embedding*), mostrando el progreso.
4. Al terminar, **el formulario y el dataset se limpian automáticamente**
   para registrar a la siguiente persona. El resumen indica cuántas fotos se
   procesaron; las rechazadas (sin rostro o con calidad insuficiente) se
   listan con su motivo. También puedes pulsar **"Limpiar"** en cualquier
   momento para descartar los datos sin guardar.

**Recomendaciones para las fotos:** rostro frontal, buena iluminación, sin
obstrucciones. Si una foto tiene calidad insuficiente (borrosa, muy oscura,
o sin rostro detectable), la aplicación la rechaza y explica el motivo.

---

## 4. Comparador biométrico

Compara dos fotografías (Imagen A vs. Imagen B) y responde: *¿es la misma
persona?*

1. Selecciona la Imagen A y la Imagen B.
2. Pulsa **"Comparar rostros"**.
3. El resultado muestra: **similitud** (%), **distancia coseno**, el
   **umbral** usado, y el veredicto ("Misma persona" / "Personas
   distintas").

Útil para verificación puntual (por ejemplo, comparar una foto de cédula
contra una foto tomada en el momento) sin necesidad de tener a la persona
registrada en la base de datos.

---

## 5. Búsqueda inteligente

Dos formas de buscar personas ya registradas:

- **Por texto**: nombre, alias, empresa o correo (búsqueda parcial).
- **Por foto**: sube una imagen y el sistema la compara contra *todas* las
  personas registradas, devolviendo las más similares ordenadas por
  porcentaje de coincidencia. Un icono de verificación junto al porcentaje
  indica que supera el umbral configurado de coincidencia.

---

## 6. Webcam en vivo

Reconocimiento facial en tiempo real usando la cámara del equipo.

1. Elige la cámara (si hay más de una conectada).
2. Pulsa **"Iniciar"**. Cada rostro detectado se enmarca: **verde** si
   coincide con alguien registrado (con su nombre y % de confianza),
   **rojo** si no se reconoce.
3. **"Detener"** apaga la cámara.

Todo el procesamiento ocurre en el propio equipo; ningún video sale de la
aplicación. Cada reconocimiento queda registrado en el historial general.

> Antes de usar este módulo sobre personas identificables, asegúrate de
> contar con una base legal adecuada (p. ej. consentimiento informado);
> ver la nota sobre datos biométricos en el `README.md`.

---

## 7. Análisis de video

Analiza un archivo de video completo (MP4, AVI, MOV, MKV) en busca de
rostros conocidos.

1. Arrastra el video, o usa **"Seleccionar video"**.
2. Elige el **nivel de muestreo** (Detallada / Estándar / Rápida / Muy
   rápida): con cuánta frecuencia se analizan los frames.
3. Pulsa **"Analizar video"**. El procesamiento corre en segundo plano (no
   bloquea la interfaz) mostrando una barra de progreso; videos largos
   pueden tardar varios minutos.
4. Al terminar, aparece en la lista **"Videos analizados"** con su estado,
   fecha y número de detecciones.
5. Haz clic en un video completado para ver el **detalle** (la vista previa
   ocupa todo el espacio disponible y se adapta al tamaño de la ventana):
   - Tabla de detecciones (frame, tiempo, persona, confianza y estado),
     **redimensionable** y con **filtro por confianza mínima**.
   - **Reproducción continua** (▶/⏸) del video.
   - Control deslizante y botones de **inicio/fin** y **detección
     anterior/siguiente** para saltar entre coincidencias, con el rostro
     resaltado.
   - **Chips clicables por persona**: haz clic para saltar a su primera
     aparición.
6. **"Exportar"** ofrece **Excel** (hoja de resumen con KPIs + hoja de
   detecciones con diseño: encabezados, filtros automáticos, resaltado por
   estado) o **CSV**.

---

## 8. Estadísticas

Vista con indicadores clave y gráficos:

- Personas registradas (acumulado en el tiempo).
- Actividad de reconocimiento (filtrable por 7/30/90/365 días).
- Distribución de confianza de las coincidencias.
- Reconocimientos por origen (webcam / video / imagen).
- Distribución de personas por empresa y por departamento.

Desde el mismo módulo se pueden **exportar resultados**:

| Botón | Qué exporta | Formatos |
|---|---|---|
| Exportar personas | Ficha completa de cada persona | CSV, Excel, JSON |
| Exportar eventos de reconocimiento | Historial completo | CSV, Excel, JSON |
| Exportar reporte PDF | KPIs + los 5 gráficos principales, listo para compartir | PDF |
| Respaldar base de datos | Copia completa de la base de datos | SQLite (.db) |

---

## 9. Administración

*(Visible solo para el rol Administrador.)*

### 9.1. Usuarios
Crear usuarios, cambiarles el rol, restablecer su contraseña, activar o
desactivar su cuenta, o eliminarlos. No es posible desactivar ni eliminar
la propia cuenta con la que se tiene la sesión iniciada.

### 9.2. Roles y permisos
Cada rol es una lista de permisos (qué módulos puede ver/usar). Se pueden
crear roles nuevos o editar los permisos de los existentes marcando las
casillas correspondientes. Un rol no puede eliminarse mientras tenga
usuarios asignados.

### 9.3. Respaldo / Restauración / Limpieza
- **Respaldo**: genera una copia `.db` completa y consistente.
- **Restauración**: reemplaza la base de datos actual por un respaldo
  seleccionado. **Acción irreversible** — la aplicación se cierra al
  terminar para aplicar los cambios de forma segura; se debe volver a
  abrir manualmente.
- **Limpieza**: borra todas las personas, fotos, eventos y videos
  analizados (los usuarios y roles se conservan). Requiere escribir
  **ELIMINAR** para confirmar.

### 9.4. Configuración segura
Permite guardar valores sensibles (por ejemplo, credenciales que en el
futuro use algún módulo de integración) **cifrados en la base de datos**;
nunca se almacenan en texto plano. Un botón "Ver valor" permite
recuperarlos cuando se necesiten.

### 9.5. Auditoría
Muestra el registro de auditoría de la aplicación (altas, bajas, inicios
de sesión, bloqueos, restauraciones, etc.), con un filtro de texto libre.

### 9.6. Calibración facial
Diagnóstico del "análisis facial extendido" (gafas, mascarilla, barba,
bigote, sonrisa, ojos abiertos): deslizando un umbral (0–1) se ve al
instante, persona por persona, qué atributos cambian y su confianza cruda
(pasando el cursor sobre la celda). El botón **Aplicar umbrales y guardar**
persiste los nuevos resultados en la base de datos. Si se quiere volver a
analizar las fotos principales (por ejemplo, registros antiguos guardados
antes de este módulo), el botón **Reanalizar fotos principales** vuelve a
ejecutar los modelos sobre ellas.

---

## 10. Preguntas frecuentes

**¿Puedo usar la aplicación sin conexión a Internet?**
Sí. Si instalaste la versión **completa** (con modelos faciales), funciona
100 % offline desde el primer arranque. En la instalación **compacta**, la
primera vez que se usa el reconocimiento facial se descarga el paquete de
modelos de IA (requiere Internet una sola vez).

**¿Dónde se guardan mis datos?**
En la versión instalada, todo queda en la carpeta `%LOCALAPPDATA%\FaceScan`
de tu equipo: la base de datos SQLite, las fotografías, la evidencia de
video y los registros de auditoría. Nada se envía a servidores externos.

**¿Qué pasa si dos personas se parecen mucho?**
El sistema muestra el porcentaje de similitud real; si supera el umbral
configurado (por defecto, distancia coseno ≤ 0.45) se marca como
coincidencia probable, pero el porcentaje exacto siempre queda visible
para que la persona que opera el sistema tome la decisión final.