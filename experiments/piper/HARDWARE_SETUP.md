# Preparar el computador del robot

Ejecuta los comandos desde la raíz del repositorio.

## 1. Conectar los brazos

Conecta el adaptador CAN del brazo izquierdo como `can1` y el del derecho como `can0`. Esta asignación coincide con `robot.left_port` y `robot.right_port` en [`bipiper.yaml`](../../configs/bipiper.yaml).

## 2. Identificar los adaptadores CAN

```bash
sudo ethtool -i can0 | grep bus-info
sudo ethtool -i can1 | grep bus-info
```

Los identificadores previstos son los que devuelva `bus-info`; no reutilices
valores de otro computador. Usa **los valores detectados** en el paso siguiente.

## 3. Activar CAN a 1 Mbps

El instalador del proyecto deja `can_activate.sh` dentro del paquete `piper_sdk` de `.venv`. Ejecuta estos comandos por separado desde la raíz del proyecto; la primera línea obtiene la ruta real del script desde el entorno virtual.

```bash
PIPER_SDK_SCRIPT=$(.venv/bin/python -c 'import pathlib, piper_sdk; print(pathlib.Path(piper_sdk.__file__).with_name("can_activate.sh"))')
sudo bash "$PIPER_SDK_SCRIPT" can0 1000000 1-3.1.2:1.0
sudo bash "$PIPER_SDK_SCRIPT" can1 1000000 1-3.1.1:1.0
```

Sustituye `1-5:1.0` y `1-6:1.0` si los identificadores obtenidos en el paso 2 son diferentes.

## 4. Verificar CAN

```bash
ip link show can0 | grep state
ip link show can1 | grep state
```

Ambas interfaces deben indicar `state UP` antes de iniciar `robot_server.py` o la prueba de inferencia.

## 5. Identificar las cámaras

```bash
v4l2-ctl --list-devices
```

Compara los dispositivos detectados con las rutas `index_or_path` de [`cameras.yaml`](../../configs/cameras.yaml). Ajusta esas rutas si los puertos V4L2 de este computador son diferentes. Los puertos CAN y la calibración de las pinzas se configuran aparte en [`bipiper.yaml`](../../configs/bipiper.yaml).
