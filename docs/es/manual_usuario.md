# Manual de Usuario — BioVision Suite

Guía de uso de la plataforma de análisis biométrico facial, módulo por módulo.
Escrita para quienes operarán la aplicación en el día a día (registrar
personas, buscar, analizar video, revisar estadísticas), no para desarrolladores
— ver la *Guía del Desarrollador* para eso.

---

## 1. Inicio de Sesión

Al abrir la aplicación se requiere **usuario y contraseña**. BioVision
Suite no tiene cuentas por defecto: la primera vez que se ejecuta, un asistente guía la
creación de la cuenta de administrador.

- Tras **5 intentos fallidos** (configurable), la cuenta se bloquea temporalmente
  por seguridad.
- Si la aplicación permanece **inactiva** durante un tiempo prolongado, se
  bloquea automáticamente y solicita reingresar la contraseña para continuar (o cerrar
  sesión).
- El botón **"Cerrar sesión"**, en la esquina superior derecha, permite que otra persona
  inicie sesión con su propia cuenta sin cerrar la aplicación.

Los módulos que ves en la barra lateral dependen de tu **rol**:

| Rol | Puede Ver |
|---|---|
| Administrador | Todos los módulos, incluido Administración |
| Operador | Dashboard, Personas, Comparador, Búsqueda, Cámara, Video, Estadísticas |
| Visualizador | Dashboard, Búsqueda, Estadísticas (solo lectura) |

---

## 2. Dashboard

Pantalla de inicio con un resumen general:

- **Personas registradas**, **eventos de reconocimiento** (hoy y total),
  **confianza promedio**.
- **Actividad reciente**: últimos reconocimientos, indicando si hubo
  coincidencia o no, su origen (cámara/video/imagen) y confianza.

---

## 3. Personas — Registro

Este módulo es **exclusivamente para enrolar personas**: el registro de datos y su
conjunto de fotos. No muestra la lista de personas registradas (para buscar o
revisar registros existentes usa el módulo **Búsqueda**).

1. Completa el formulario de la izquierda. **Nombre** y **Apellidos** son
   obligatorios (marcados con `*`); el resto — alias, sexo, edad, empresa,
   departamento, cargo, contacto, observaciones — es opcional. El correo se valida
   automáticamente.
2. Añade las fotos del conjunto de datos. Puedes **arrastrar y soltar** fotos sobre el área de la
   derecha, hacer clic en **"+ Añadir fotos"** para seleccionarlas del disco, o usar
   **"Cámara"** para capturar una foto en el momento (con opción de reintentar).
   La primera foto se marcará como principal.
3. Haz clic en **"Guardar persona"**. En segundo plano se crea la persona y cada
   foto se procesa automáticamente: se detecta el rostro principal y se extrae su
   vector biométrico (*embedding*), mostrando el progreso.
4. Al finalizar, **el formulario y el conjunto de datos se limpian automáticamente** para
   registrar a la siguiente persona. El resumen indica cuántas fotos se
   procesaron; las rechazadas (sin rostro o calidad insuficiente) se listan con
   su motivo. También puedes hacer clic en **"Limpiar"** en cualquier momento para descartar
   datos no guardados.

**Recomendaciones para fotos:** rostro frontal, buena iluminación, sin obstrucciones. Si una
foto tiene calidad insuficiente (borrosa, muy oscura o sin rostro detectable), la
aplicación la rechaza y explica por qué.

---

## 4. Comparador Biométrico

Compara dos fotos (Imagen A vs. Imagen B) y responde: *¿es la misma
persona?*

1. Selecciona la Imagen A y la Imagen B.
2. Haz clic en **"Comparar rostros"**.
3. El resultado muestra: **similitud** (%), **distancia coseno**, el **umbral**
   usado y el veredicto ("Misma persona" / "Personas diferentes").

Útil para verificación puntual (por ejemplo, comparar una foto de documento contra una
foto tomada en el momento) sin necesidad de que la persona esté registrada en la
base de datos.

---

## 5. Búsqueda Inteligente

Dos formas de buscar personas ya registradas:

- **Por texto**: nombre, alias, empresa o correo (búsqueda parcial).
- **Por foto**: sube una imagen y el sistema la compara contra *todas*
  las personas registradas, devolviendo las más similares ordenadas por porcentaje
  de coincidencia. Un icono de verificación junto al porcentaje indica que supera el
  umbral de coincidencia configurado.

---

## 6. Cámara en Vivo

Reconocimiento facial en tiempo real usando la cámara del equipo.

1. Elige la cámara (si hay más de una conectada).
2. Haz clic en **"Iniciar"**. Cada rostro detectado se enmarca: **verde** si coincide
   con alguien registrado (con nombre y % de confianza), **rojo** si no es reconocido.
3. **"Detener"** apaga la cámara.

Todo el procesamiento ocurre en la máquina local; ningún video sale de la aplicación.
Cada reconocimiento se registra en el historial general.

> Antes de usar este módulo con personas identificables, asegúrate de tener una
> base legal adecuada (p. ej., consentimiento informado); ver la nota de datos biométricos
> en `README-es.md`.

---

## 7. Análisis de Video

Analiza un archivo de video completo (MP4, AVI, MOV, MKV) buscando rostros conocidos.

1. Arrastra el video o usa **"Seleccionar video"**.
2. Elige el **nivel de muestreo** (Detallado / Estándar / Rápido / Muy rápido): con qué
   frecuencia se analizan los fotogramas.
3. Haz clic en **"Analizar video"**. El procesamiento se ejecuta en segundo plano (no
   bloquea la UI) mostrando barra de progreso; videos largos pueden tardar varios minutos.
4. Al terminar, aparece en la lista **"Videos analizados"** con su
   estado, fecha y número de detecciones.
5. Haz clic en un video completado para ver **detalles** (la vista previa ocupa todo
   el espacio disponible y se adapta al tamaño de ventana):
   - Tabla de detecciones (fotograma, tiempo, persona, confianza y estado),
     **redimensionable** y con **filtro de confianza mínima**.
   - **Reproducción continua** (▶/⏸) del video.
   - Deslizador y botones **inicio/fin** y **detección anterior/siguiente** para saltar
     entre coincidencias, con el rostro resaltado.
   - **Chips clicables por persona**: haz clic para saltar a su primera aparición.
6. **"Exportar"** ofrece **Excel** (hoja resumen con KPIs + hoja de detecciones
   con estilo: cabeceras, autofiltros, resaltado de estado) o **CSV**.

---

## 8. Estadísticas

Vista con indicadores clave y gráficos:

- Personas registradas (acumulado en el tiempo).
- Actividad de reconocimiento (filtrable por 7/30/90/365 días).
- Distribución de confianza de coincidencias.
- Reconocimientos por origen (cámara / video / imagen).
- Distribución de personas por empresa y por departamento.

Desde el mismo módulo puedes **exportar resultados**:

| Botón | Qué Exporta | Formatos |
|---|---|---|
| Exportar personas | Registro completo de cada persona | CSV, Excel, JSON |
| Exportar eventos | Historial completo | CSV, Excel, JSON |
| Exportar informe PDF | KPIs + 5 gráficos principales, listo para compartir | PDF |
| Respaldar base de datos | Copia completa de la base de datos | SQLite (.db) |

---

## 9. Administración

*(Visible solo para el rol Administrador.)*

### 9.1. Usuarios
Crea usuarios, cambia su rol, restablece su contraseña, activa o desactiva
su cuenta, o elimínalos. No puedes desactivar ni eliminar tu propia
cuenta actualmente en sesión.

### 9.2. Roles y Permisos
Cada rol es una lista de permisos (qué módulos se pueden ver/usar). Puedes
crear nuevos roles o editar los permisos de los existentes marcando las
casillas correspondientes. Un rol no puede eliminarse mientras tenga usuarios asignados.

### 9.3. Respaldo / Restauración / Limpieza
- **Respaldo**: genera una copia `.db` completa y consistente.
- **Restaurar**: reemplaza la base de datos actual con el respaldo seleccionado.
  **Acción irreversible** — la aplicación se cierra al completarse para aplicar
  cambios de forma segura; debe reabrirse manualmente.
- **Limpieza**: elimina todas las personas, fotos, eventos y videos analizados
  (se conservan usuarios y roles). Requiere escribir **DELETE** para confirmar.

### 9.4. Configuración Segura
Permite guardar valores sensibles (por ejemplo, credenciales que un futuro
módulo de integración podría usar) **cifrados en la base de datos**; nunca se
almacenan en texto plano. Un botón "Ver valor" permite recuperarlos cuando sea necesario.

### 9.5. Auditoría
Muestra el registro de auditoría de la aplicación (registros, eliminaciones, inicios de sesión, bloqueos,
restauraciones, etc.), con filtro de texto libre.

### 9.6. Calibración Facial
Diagnóstico para el "análisis facial extendido" (gafas, mascarilla, barba, bigote,
sonrisa, ojos abiertos): al deslizar un umbral (0–1) ves al instante, persona por
persona, qué atributos cambian y su confianza cruda (pasa el cursor sobre la celda).
El botón **Aplicar umbrales y guardar** persiste los nuevos resultados en la
base de datos. Si deseas reanalizar fotos principales (por ejemplo, registros antiguos
guardados antes de este módulo), el botón **Reanalizar fotos principales** vuelve a ejecutar
los modelos sobre ellas.

---

## 10. Preguntas Frecuentes

**¿Puedo usar la aplicación sin conexión a Internet?**
Sí, salvo la primera vez que se ejecuta (descarga del paquete de modelos IA). Después
funciona completamente offline.

**¿Dónde se almacenan mis datos?**
Todo queda en la carpeta `data/` del proyecto: la base de datos SQLite, fotos
y evidencia de video. Nada se envía a servidores externos.

**¿Qué pasa si dos personas se parecen mucho?**
El sistema muestra el porcentaje de similitud real; si supera el
umbral configurado (por defecto, distancia coseno ≤ 0.45) se marca como probable
coincidencia, pero el porcentaje exacto siempre permanece visible para que el operador
tome la decisión final.
