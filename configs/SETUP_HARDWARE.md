# Preparar el computador del robot

Ejecuta los comandos desde la raíz del proyecto: `/home/aniela/NONHUMAN/dream1-piper`.

## 1. Conectar los brazos

Conecta el adaptador CAN del brazo izquierdo como `can0` y el del derecho como `can1`. Esta asignación coincide con `robot.left_port` y `robot.right_port` en [bipiper.yaml](bipiper.yaml).

## 2. Identificar los adaptadores CAN

```bash
sudo ethtool -i can0 | grep bus-info
sudo ethtool -i can1 | grep bus-info
```

Los identificadores previstos en esta configuración son `1-5:1.0` para el brazo izquierdo y `1-6:1.0` para el derecho. Si tu computador muestra otros valores, usa **los valores que devuelve `bus-info`** en el paso siguiente.

## 3. Activar CAN a 1 Mbps

El instalador del proyecto deja `can_activate.sh` en `.venv/lib/python3.12/site-packages/piper_sdk/`.

```bash
sudo bash .venv/lib/python3.12/site-packages/piper_sdk/can_activate.sh \
  can0 1000000 1-5:1.0
sudo bash .venv/lib/python3.12/site-packages/piper_sdk/can_activate.sh \
  can1 1000000 1-6:1.0
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

Compara los dispositivos detectados con las rutas `index_or_path` de [cameras.yaml](cameras.yaml). Ajusta esas rutas si los puertos V4L2 de este computador son diferentes. Los puertos CAN y la calibración de las pinzas se configuran aparte en [bipiper.yaml](bipiper.yaml).
