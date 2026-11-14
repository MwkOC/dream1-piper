# Calibración de intrínsecos

Desde la raíz del proyecto, crea una vez un entorno independiente con OpenCV
gráfico (el entorno principal usa OpenCV headless para Dream Labs):

```bash
python3 -m venv .venv-calibration
.venv-calibration/bin/python -m pip install opencv-python numpy scipy PyYAML
```

Para usar la ZED Mini, instala primero el [SDK de ZED para Linux](https://docs.stereolabs.com/docs/development/zed-sdk/linux) y CUDA compatible. El SDK nativo y su GPU son requisitos de `pyzed`; no basta con añadirlo a `requirements.txt`. Instala su [API de Python](https://docs.stereolabs.com/docs/development/api-languages/python) en el entorno de calibración:

```bash
cp /usr/local/zed/get_python_api.py /tmp/get_zed_python_api.py
.venv-calibration/bin/python /tmp/get_zed_python_api.py
.venv-calibration/bin/python -c 'import pyzed.sl; print("ZED Python API OK")'
```

Para otros procesos que usen `ZedMiniCameraDevice`, instala también `pyzed` en su entorno Python. Si hay más de una ZED conectada, configura `serial_number` en `cameras.top`; de lo contrario el SDK elige una cámara disponible.

En esta instalación local, activa el entorno antes de ejecutar los comandos
para cargar las bibliotecas del SDK: `source .venv-calibration/bin/activate`.
Los archivos de calibración de fábrica de la ZED se guardan en
`~/.cache/zed/settings/`, compartidos con el entorno principal. Para otra
cámara, descarga su archivo `SN<serie>.conf` desde
`https://calib.stereolabs.com/?SN=<serie>` en esa carpeta si el SDK no lo
descarga automáticamente.

Con un escritorio gráfico y las cámaras conectadas:

```bash
.venv-calibration/bin/python scripts/calibrate_spatial.py
```

Se calibran las cámaras OpenCV de `configs/cameras.yaml` (izquierda y derecha).
La ZED no se abre durante la calibración: utiliza su archivo de fábrica al
capturar imágenes. Para seleccionar únicamente la cámara izquierda:

```bash
.venv-calibration/bin/python scripts/calibrate_spatial.py --camera left
```

Se necesita un tablero ChArUco de 5 × 7 casillas de 30 mm, marcadores de
15 mm y diccionario `DICT_5X5_100`, con patrón no heredado. Si el tablero es
distinto, añadir `spatial_calibration.board` a `configs/cameras.yaml` con los
campos `squares_x`, `squares_y`, `square_length_m`, `marker_length_m`,
`dictionary` y `legacy_pattern`. Usar las dimensiones físicas reales.

La captura es automática cada dos segundos cuando hay suficientes esquinas y
una vista distinta. Mover el tablero por el centro y los bordes, cambiar su
distancia e inclinarlo en ambos sentidos. Q o Esc interrumpe la cámara actual.
La ZED usa la vista izquierda rectificada `VIEW.LEFT` del SDK a 672 × 376.
Los fotogramas se procesan en memoria sin guardarlos. Las matrices, distorsión,
resolución y errores en `outputs/calibration/spatial.yaml`. Los resultados
existentes de otras cámaras se conservan. No se guarda un resultado incompleto
o con error medio de reproyección superior a 0,8 píxeles.

El modelo predeterminado es `pinhole`; para una lente ojo de pez se puede
seleccionar `--model fisheye`. No instales `opencv-python-headless` en el
entorno de calibración: sus archivos pueden sustituir la versión gráfica.
