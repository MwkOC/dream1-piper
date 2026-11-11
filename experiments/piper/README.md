# Setup Piper y cámaras

Este repositorio mantiene únicamente nuestra integración. El cliente, `dreamcli`,
el editor TCP y la IK se instalan desde PyPI mediante `requirements.txt`.
La [guía general del proyecto](../../README.md) describe la instalación de los
subproyectos; esta carpeta contiene la documentación específica de Piper.

## Archivos de la integración

| Archivo | Función |
| --- | --- |
| [`robot.py`](robot.py) | Robot individual y bimanual activo |
| [`active_driver.py`](active_driver.py) | Conexión CAN, habilitación, streaming y diagnósticos |
| [`kinematics.py`](kinematics.py) | FK/IK sobre el URDF dual |
| [`configs/bipiper.yaml`](../../configs/bipiper.yaml) | Puertos, pinzas y límites del robot |
| [`configs/cameras.yaml`](../../configs/cameras.yaml) | Dispositivos y roles de cámara |

El driver activo de `experiments/piper` sí puede habilitar motores y enviar
objetivos. Consultar [DRIVER_STATUS.md](DRIVER_STATUS.md) antes de preparar
control real.

## Configuración confirmada

| Campo | Valor |
| --- | --- |
| Cuerpo Dream | `custom`, dos brazos, seis articulaciones y una pinza por lado |
| CAN izquierdo / derecho | `can1` / `can0`, configuración local; verificar físicamente |
| Home por brazo | `[0, 0, 0, 0, 0.4363323, 0]` rad, configurada en HandUMI |
| `overhead` | ZED Mini UVC, salida izquierda 672×376, 30 fps |
| `wrist_l` / `wrist_r` | OpenCV, 640×480, 30 fps |
| Bucle Dream | 30 Hz; chunks oficiales de 48 filas; historial de 9 frames a 5 Hz |

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

El paquete oficial completo para cargar en el asistente está en
`assets/piper_description/`; incluye el URDF y sus meshes en la jerarquía ROS
requerida. También se dejó `assets/piper_description.zip` junto a la carpeta;
el ZIP es un artefacto local ignorado por Git. Para ambas cadenas, la base es
`left_base_link`/`right_base_link` y el flange debe ser el link físico
confirmado con `dreamcli tcp`. No se deben inventar `tcp`,
`approach`, `jaw` ni `rest` a partir del URDF.

El valor nominal del URDF no sustituye la confirmación física. La calibración
PICO es mando→herramienta, distinta del flange→pinza que necesita Dream. No se
copia entre ambos marcos.

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
y `open_microm` en `~/.dreamlabs/bipiper-gripper-calibration.yaml`. El formato
de HandUMI guarda solo `closed_microm`, por lo que no basta con apuntar a su
YAML.

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

## Flujo Dream

El entrypoint oficial es `dream-piper-models`. Usa el arm file generado con
`dreamcli tcp`, `strict=True`, IK oficial con `head=eef`, timestamps monotónicos,
chunks articulares `q_l_chunk`/`q_r_chunk` y continuidad mediante `commanded`.
Antes de `--execute`, ejecuta `python -m dream.check` y confirma las vistas de
las tres cámaras.

```bash
cd experiments
dream-piper-models --models
dream-piper-models --infer --prompt 'pick up the soft object'
dream-piper-models --infer --execute --prompt 'pick up the soft object'
```

## Paso posterior

Registrar el embodiment y seleccionar un checkpoint EEF accesible para la cuenta
es posterior al editor. La API requiere credenciales y puede facturar. Antes de
movimiento hacen falta el driver activo, las calibraciones y una validación con
hardware; instalar el SDK no completa esos pasos.
