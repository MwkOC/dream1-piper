# Dream-1 Piper

Conexión de dos brazos AgileX Piper con Dream Labs mediante
[`scripts/dreamlabs.py`](scripts/dreamlabs.py). El script captura las tres cámaras,
lee el estado real, calcula FK con el URDF y convierte las respuestas EEF en
objetivos articulares usando `scripts/kinematics.py`. Los límites de
`scripts/constants.py` se comprueban en IK y en el driver CAN.

## Instalación

Desde la raíz del repositorio, con Python 3.11–3.13:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dream-test.txt
```

La cámara `top` requiere además ZED SDK y su paquete `pyzed` en ese mismo
entorno. La ZED Mini se abre con el SDK, no mediante OpenCV.

Configura la clave una vez en la terminal (también se admite la configuración
oficial en `~/.dreamlabs/credentials`):

```bash
export DREAM_API_KEY='tu_clave_dreamlabs'
```

El script no carga `.env` automáticamente. Los dispositivos y puertos se leen de
`configs/cameras.yaml` y `configs/bipiper.yaml`. Antes de probar, prepara CAN,
las cámaras y la calibración de ambas pinzas siguiendo las instrucciones de abajo.

## Probar Dream Labs con un comando

Desde la raíz, con los brazos y cámaras conectados:

```bash
.venv/bin/python -m scripts.dreamlabs --prompt "put the cup on the plate"
```

Este comando hace una llamada real de inferencia, sujeta al consumo de tu cuenta,
y valida las acciones de ambos brazos mediante IK fila por fila, sin habilitar
motores ni mandar posiciones. Imprime el horizonte recibido y su latencia.
Necesita feedback CAN y la calibración de ambas pinzas, también en este modo.

Para habilitar motores y ejecutar un chunk completo:

```bash
.venv/bin/python -m scripts.dreamlabs --prompt "put the cup on the plate" --execute
```

Para ejecutar con varias solicitudes y horizontes solapados:

```bash
.venv/bin/python -m scripts.dreamlabs --prompt "put the cup on the plate" --execute --chunks 5
```

### Ver el estado y reducir la velocidad

La consola muestra cada etapa con hora y nivel: apertura de cámaras y CAN,
configuración de la política, prompt incluido en la solicitud, estado enviado,
espera de respuesta, errores y reintentos, respuesta EEF (formas y primeras/últimas
filas), validación IK y avance de las órdenes enviadas a Piper. Un mensaje de
política configurada no confirma todavía la inferencia: el script indica cuándo
llega una respuesta del servidor. La API no da un acuse independiente del prompt.

El registro también se guarda en `outputs/dreamlabs/dreamlabs.log` (se añaden las
nuevas ejecuciones). Para ver todas las filas numéricas recibidas y cada objetivo
articular enviado, usa `--verbose`; las imágenes base64 y la clave API no se
imprimen. `--log-file RUTA` cambia el archivo. Ejemplo:

```bash
.venv/bin/python -m scripts.dreamlabs --prompt "put the cup on the plate" --verbose
```

Las ejecuciones con `--execute` usan por defecto **media velocidad**
(`--speed-scale 0.5`), un máximo de **30 °/s** por articulación, aceleración máxima
**120 °/s²** y velocidad SDK de como máximo **20 %**. Se conservan límites menores
si ya están configurados. Estos ajustes afectan solo a este script.
Se alargan los intervalos si el cambio articular necesita más tiempo según el
límite de velocidad. Un horizonte nuevo sustituye las filas pendientes del
anterior; se omiten las filas del nuevo que ya caducaron durante la solicitud.
Al terminar se solicita mantener la posición medida. La pinza también
recibe los objetivos con esta cadencia más lenta, pero no tiene un límite de
velocidad físico independiente en este script.

Para una prueba todavía más lenta:

```bash
.venv/bin/python -m scripts.dreamlabs --prompt "put the cup on the plate" --execute --speed-scale 0.25 --max-joint-speed 15 --max-joint-acceleration 60
```

Por defecto se usa `dreamlabs/dream-1-beta`, a 20 filas de acción por segundo en
el modelo; con escala 0.5 se ejecutan como máximo 10 filas por segundo.
`--checkpoint`, `--urdf`, `--config`, `--cameras`, `--action-hz` y
`--retry-timeout` permiten cambiar esos valores; consulta `--help`.
El bucle solicita el siguiente horizonte mientras reproduce el actual, cada
8 filas ejecutadas (`--replan-rows`). `--chunks` limita el número de solicitudes,
no el número de horizontes completos reproducidos. Resuelve la IK de ambos brazos
antes de enviar cada fila, sin calcular primero las 48. No espera a alcanzar el
último objetivo ni reinicia la posición medida entre horizontes. Las cámaras se
capturan en un hilo separado a 5 Hz; cada solicitud actualiza además el feedback
articular sin duplicar imágenes. En ejecución lleva los brazos a la postura
inicial una sola vez, antes de las solicitudes.
Ctrl+C interrumpe la prueba y solicita detener el movimiento antes de desconectar.

### Datos y unidades

Se usa la API pública `DreamClient.policy()`, `set_observation()` y `get_action()`,
con `robot="other_embodiment"` e IK propia, según el contrato del SDK Dream
instalado y la [documentación de Dream Labs](https://platform.dreamlabs.ai/docs/).

- Feedback Piper: miligrados → radianes; pinza en µm → apertura calibrada `[0,1]`.
- FK: `left_base_link → left_tcp` y `right_base_link → right_tcp` del
  URDF actualizado `assets/piper/piper.urdf`. El offset TCP se obtiene del URDF.
- Observación: `prompt`, `state.<side>_eef_xyz` en metros,
  `state.<side>_eef_rot6` con las primeras dos columnas de la matriz de rotación
  y apertura de pinza, siempre en la base de cada brazo. Los slots articulares
  del modelo base YAM se envían a cero; el estado Piper se usa localmente para FK/IK.
  Esto reproduce `dream.client_ik.ClientIK.observe()` del SDK instalado: para
  un checkpoint entrenado en YAM ejecutado en otro robot, calcula FK con los
  ángulos medidos y sustituye después los slots articulares por ceros al enviar.
  No representan telemetría Piper ni permiten verificar sus articulaciones con
  `dream.check`. Usar un checkpoint entrenado en Piper requiere revisar su
  contrato de observación; tener un URDF Piper no cambia el del modelo base.
- Vídeo: JPEG base64 con `top → video.overhead`, `left → video.wrist_l` y
  `right → video.wrist_r`; nueve imágenes reales espaciadas a 5 Hz.
  Las muñecas se rectifican con su calibración y conservan el recorte central
  existente del 80 %; ZED entrega su imagen izquierda rectificada por el SDK.
  Después, las tres se recortan al centro a 16:9 y se redimensionan a
  **320 × 176** antes de codificar el JPEG (calidad 85), según Dream-1.
  No se añade padding ni se duplica el recorte del 2,5 % que aplica el modelo.
  Al grabar datos para fine-tuning debe usarse el mismo encuadre que en inferencia.
- Respuesta: únicamente `per_key["action.<side>_eef_xyz"]`,
  `action.<side>_eef_rot6` y `action.<side>_grip`. Se rechazan formas incorrectas,
  NaN/Inf, pinzas fuera de `[0,1]` y poses que el solver no alcance dentro de sus
  tolerancias (2 cm y 10 grados). La IK es numérica y puede rechazar una pose
  alcanzable si no converge desde su semilla.
- Se resuelven todas las filas de ambos brazos antes del primer comando.
  `BiPiper.send_action()` recibe solo articulaciones en radianes y pinzas `[0,1]`;
  el driver convierte a miligrados/µm y limita velocidad y aceleración.

La inferencia utiliza el comportamiento de grabación predeterminado del SDK Dream.
La validación de IK y límites no comprueba colisiones ni obstáculos.

## Preparar cámaras e interfaces CAN

Realiza estas comprobaciones antes de calibrar o utilizar el robot.

### Identificar las cámaras

Conecta las cámaras y lista sus dispositivos y rutas USB:

```bash
v4l2-ctl --list-devices
```

`v4l2-ctl` muestra los dispositivos asociados a cada cámara y `by-path` los
relaciona con su puerto USB. Una cámara puede aparecer como varios dispositivos
`video`; identifica el nodo de captura, normalmente `video-index0`. Si dos
cámaras tienen el mismo nombre, desconecta y vuelve a conectar una para
identificar cuál ruta aparece. Comprueba que `index_or_path` en
[`configs/cameras.yaml`](configs/cameras.yaml) corresponde a las cámaras
físicas `left` y `right`. La ZED Mini (`top`) se abre mediante el SDK; si hay
varias cámaras ZED, selecciona su número de serie en la configuración. Los
números `/dev/videoN` pueden cambiar al reconectar las cámaras.


### Configurar las interfaces CAN

Enciende y conecta ambos brazos y sus adaptadores CAN. Identifica qué interfaz
corresponde a cada brazo y comprueba su estado:

```bash
ip -details -statistics link show can0
ip -details -statistics link show can1
readlink -f /sys/class/net/can0/device
readlink -f /sys/class/net/can1/device
```

La configuración actual asigna `can0` al brazo izquierdo y `can1` al derecho.
Verifica esta correspondencia física después de reconectar los adaptadores y,
si cambia, actualiza `robot.left_port` y `robot.right_port` en
[`configs/bipiper.yaml`](configs/bipiper.yaml). Cada interfaz debe estar `UP`,
con bitrate `1000000` y sin `BUS-OFF`. Si una interfaz está `DOWN`, actívala
con los comandos correspondientes:

```bash
sudo ip link set can0 type can bitrate 1000000
sudo ip link set can0 up
sudo ip link set can1 type can bitrate 1000000
sudo ip link set can1 up
```

Omite los comandos de las interfaces que ya estén activas a 1 Mbps. Estar
`UP` no garantiza que el brazo esté enviando telemetría. Consulta
[Estado y asignación CAN](COMANDOS_BIPIPER.md#2-estado-y-asignación-can)
para más detalles.

## Calibración

Ejecuta los siguientes comandos desde la raíz del repositorio.

### Cámaras

Con las cámaras conectadas, un escritorio gráfico y el tablero ChArUco disponible,
calibra las cámaras OpenCV izquierda y derecha de `configs/cameras.yaml`:

```bash
.venv-calibration/bin/python scripts/calibrate_spatial.py
```

Para las cámaras OpenCV, mueve el tablero por el centro y los bordes de la
imagen, variando la distancia y la inclinación. La captura es automática;
pulsa Q o Esc para interrumpirla. Las imágenes se procesan en memoria y los parámetros se guardan en
`outputs/calibration/spatial.yaml`. Para la ZED se usa la calibración
rectificada del SDK, no las capturas del tablero.

Consulta las dimensiones del tablero, las dependencias y las opciones del
modelo en [Calibración de cámaras](docs/calibracion_camaras.md).
Esta calibración usa un entorno independiente con OpenCV gráfico; la guía
explica cómo crearlo.

### Grippers

Con ambos brazos conectados y sus interfaces CAN configuradas en
`configs/bipiper.yaml`, ejecuta:

```bash
.venv/bin/python tests/test_gripper_calibration.py
```

El programa lee la telemetría sin enviar órdenes de movimiento. Sigue el
procedimiento manual seguro de tu equipo para colocar cada pinza totalmente
cerrada y luego abierta, pulsando Enter en cada posición. Repite el proceso
para ambos lados. Los valores medidos se guardan en
`outputs/calibration/bipiper-gripper-calibration.yaml`, la ruta configurada en
`configs/bipiper.yaml`.

Para usar 25 muestras por posición:

```bash
.venv/bin/python tests/test_gripper_calibration.py --samples 25
```

Se requiere `piper_sdk` y telemetría disponible en ambas interfaces CAN. Si
utilizas `--output` para guardar en otra ruta, actualiza también
`robot.gripper_calibration_path` en `configs/bipiper.yaml`.

## Pruebas sin hardware

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/test_dream_api.py -q
```

Estas pruebas comprueban el contrato de observación/acciones EEF, el recorrido
FK→IK, la conversión de unidades y el rechazo de objetivos fuera de límites.
No llaman a la API ni habilitan motores.
