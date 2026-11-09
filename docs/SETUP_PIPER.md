# Setup Piper y cámaras

Este repositorio mantiene únicamente nuestra integración. El cliente, `dreamcli`,
el editor TCP y la IK se instalan desde PyPI mediante `requirements.txt`.
La [guía de instalación](../TUTORIAL_INSTALACION.md) incluye los comandos completos.

## Archivos de la integración

| Archivo | Función |
| --- | --- |
| [`experiments/piper/robot.py`](../experiments/piper/robot.py) | Robot individual y bimanual activo |
| [`experiments/piper/active_driver.py`](../experiments/piper/active_driver.py) | Conexión CAN, habilitación, streaming y diagnósticos |
| [`experiments/piper/kinematics.py`](../experiments/piper/kinematics.py) | FK/IK sobre el URDF dual |
| [`configs/bipiper.yaml`](../configs/bipiper.yaml) | Puertos, cámaras y límites; los frames vienen del URDF |

El driver activo de `experiments/piper` sí puede habilitar motores y enviar
objetivos. Consultar [DRIVER_STATUS.md](DRIVER_STATUS.md) antes de preparar
control real.

## Configuración confirmada

| Campo | Valor |
| --- | --- |
| Cuerpo Dream | `custom`, dos brazos, seis articulaciones y una pinza por lado |
| CAN izquierdo / derecho | `can0` / `can1`, importados de HandUMI; verificar físicamente |
| Home por brazo | `[0, 0, 0, 0, 0.4363323, 0]` rad, configurada en HandUMI |
| `overhead` | ZED Mini `/dev/video2`, ojo izquierdo 672×376, 30 fps |
| `wrist_l` | OpenCV `/dev/video0`, 640×480, 30 fps |
| `wrist_r` | OpenCV `/dev/video4`, 640×480, 30 fps |
| Bucle Dream | 20 Hz; chunks de 48 filas; historial de 9 frames a 5 Hz |

Los índices de cámaras y modos reales requieren comprobación en el equipo.
El rig local de HandUMI tenía asignaciones de cámara diferentes: la plantilla usa
la corrección del usuario con la ZED como overhead, recogida en
`confirmed_camera_mapping`. No se deben restaurar automáticamente los roles antiguos.

## TCP y modelo de brazo

En la plataforma elegir **Set up your own robot**, con un URDF propio; no usar
YAM o Maker como sustituto de Piper. El editor local independiente se abre con:

```bash
source .venv/bin/activate
dreamcli --home "$PWD/experiments/piper" tcp --host 127.0.0.1
```

Los assets del URDF se encuentran en el workspace HandUMI, fuera de este repo.
Para la cadena izquierda, `left_base_link` es la base y `left_link6` un flange
posible. El archivo pendiente actual utiliza `left_gripper_base`: si cambias el
flange, las medidas del TCP deben expresarse en el marco que hayas elegido.

El URDF de HandUMI corrigió el TCP nominal a z=0.1358 m desde `link6`. Ese valor
no sustituye la confirmación física. Su calibración PICO es mando→herramienta,
distinta del flange→pinza que necesita Dream. No se copia entre ambos marcos.

Las homes ya están importadas, pero hay que comprobar la trayectoria y el estado
de la pinza: HandUMI la deja cerrada y Dream puede abrirla durante home. La
preferencia `posture_q` es parcial y no permite rellenar automáticamente `rest`.
El URDF representa 0.60 m entre bases; medir el montaje antes de usar ese modelo
para verificar colisiones o planificar el área de trabajo.

## Unidades y pinzas

El driver Piper moderno de XHUMAN/HandUMI trabaja en radianes y convierte el
feedback SDK de miligrados mediante `pi / 180000`. El antiguo
`bi_piper_follower` usa posiciones normalizadas [-100,100] y otras conversiones;
no mezclar valores ni duplicar sus inversiones de signo.

El driver activo espera una calibración medida por lado con `closed_microm`
y `open_microm`, en `$XHUMAN_PIPER_GRIPPER_CALIBRATION` o, por defecto,
`${XDG_CACHE_HOME:-~/.cache}/xhuman/piper_grippers.yaml`. En este equipo no se
encontró ese archivo. El formato de HandUMI guarda solo `closed_microm`, por lo
que no basta con apuntar al YAML de HandUMI.

El driver rechaza feedback ausente y valores no finitos. El streamer limita
velocidad y aceleración, propaga errores del hilo de control y requiere el SDK
Piper para leer CAN. El editor TCP y las pruebas offline no lo necesitan.

## ZED y óptica

`ZedLeft` solicita estéreo UVC 1344×376 y publica solo la mitad izquierda BGR.
En la plantilla, 672×376 es el tamaño de salida. Rechaza otros tamaños para no
recortar por error una imagen ya monocular. `PIPER_ZED_DEVICE` permite cambiar
el dispositivo. No aplicar el recorte dos veces ni abrir simultáneamente la misma
cámara desde HandUMI y Dream.

Para cámaras con fisheye, primero comparar la vista cruda con una rectificada
usando intrínsecos medidos. No existe una rectificación automática ni un FOV
obligatorio verificado. Mantener montaje y procesamiento iguales entre grabación
e inferencia; revisar que pinzas y objetos sean visibles en la imagen final.

## Paso posterior

Registrar el embodiment y seleccionar un checkpoint EEF accesible para la cuenta
es posterior al editor. La API requiere credenciales y puede facturar. Antes de
movimiento hacen falta el driver activo, las calibraciones y una validación con
hardware; instalar el SDK no completa esos pasos.
