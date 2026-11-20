# Experimento: estación y worker Piper

Este directorio reemplaza el flujo recomendado de `scripts/dreamlabs.py` para
probar la arquitectura de dos procesos. El script legado permanece intacto;
este experimento porta el contrato, DLS incremental, cola de chunks y consola
operativa del despliegue de referencia.

La estación es dueña de CAN y las tres cámaras V4L. El worker se conecta por
WebSocket, ejecuta inferencia Dream 1.0.37, resuelve las acciones EEF mediante
IK local y la estación valida cada objetivo antes de actualizar el streamer de
Piper. El worker usa modo de acción por defecto; la estación exige Validar →
Armar → Iniciar y pausa ante errores o desconexión. `RSTACK_DREAM_MODE=observe`
permite inspeccionar sin transmitir objetivos.

## Perfil físico

- Brazo izquierdo: `can0`; derecho: `can1`; ambos a 1 Mbps.
- `left`, `top` y `right` usan rutas persistentes `/dev/v4l/by-path`, no
  números `/dev/videoN`.
- La estación conserva el límite de sincronía de 60 ms del perfil origen y
  espera hasta 100 ms por una nueva combinación de frames antes de rechazar un
  jitter transitorio de UVC.
- La cámara superior recibe 1344×376 YUYV, toma la mitad izquierda y entrega
  640×360; las muñecas entregan el recorte central 16:9 a 640×360.
- Un controlador Piper con fallo requiere recuperación física manual: el driver
  no llama a `ResetPiper`, porque libera torque. Sostén el brazo antes de
  recuperar alimentación, CAN o el controlador.

## Prueba segura

Instala dependencias, crea `.env` desde `.env.example` y valida el rig:

```bash
.venv/bin/python -m pip install -r requirements-dream-test.txt
cp .env.example .env
.venv/bin/python -m experiments.piper_station_worker.preflight --check-devices
```

El perfil incluido usa el mismo contrato de `radians` del despliegue funcional
de origen: feedback y comandos del SDK Piper no se invierten ni desplazan. Por
eso preflight funciona sin crear un archivo adicional. Si una máquina muestra
feedback fuera de los límites, no se debe cambiar a ciegas: crea una calibración
por máquina desde `configs/piper_joint_calibration.yaml.example`, mide su
convención y apunta `joint_calibration_path` a ese archivo.

En una terminal, ejecuta la estación:

```bash
.venv/bin/python -m experiments.piper_station_worker.station
```

Abre la consola de operaciones en <http://127.0.0.1:8080>. El puerto `8765` sigue
siendo exclusivamente WebSocket para el worker; abrirlo en un navegador produce
el mensaje de handshake inválido esperado. Usa `--no-ui` si sólo necesitas el
servidor WebSocket.

En otra, ejecuta el worker:

```bash
.venv/bin/python -m experiments.piper_station_worker.worker
```

El worker inicia en modo `action` sin parámetros adicionales. La consola muestra
las tres vistas, validación, tarea, armado, inicio, pausa, Home, reset de fallo y
telemetría. La estación abre CAN y mantiene la postura al conectarse; el modo
`observe` tampoco significa motores sin torque.

## Ejecución física supervisada

Sólo después de pasar preflight, confirmar la calibración articular, revisar las
tres vistas y ejecutar `python -m dream.check` por una persona, configura el
modo de acción en `.env` (`RSTACK_DREAM_MODE=action`). Para inferir sin enviar
objetivos, usa `RSTACK_DREAM_MODE=observe`.

Inicia la estación sin `--run`; el worker de control se conecta mientras la
estación está lista y espera. En la consola presiona Validar, Armar e Iniciar
cuando el área esté despejada:

```bash
.venv/bin/python -m experiments.piper_station_worker.station
```

En otra, inicia el worker de control (acción es el modo predeterminado):

```bash
.venv/bin/python -m experiments.piper_station_worker.worker
```

La estación asigna una sesión al armarse, emite observaciones a 20 Hz cuando
está en ejecución y sólo
acepta acciones con esa sesión, versión de esquema, secuencia y edad válidas.
Los objetivos pasan por límites 14D y el streamer conserva los límites de
velocidad/aceleración. Si vence el watchdog, se desconecta el worker, falla IK o
se rechaza una acción, la estación mantiene la postura y pasa a pausa.

Un fallo del streamer coloca el supervisor en `FAULT` después de intentar
mantener la posición; requiere corregir el problema y resetear el fallo desde la
consola. `/api/status` incluye conteos de acciones/observaciones/rechazos,
latencias Dream last/mean/p50/p95/max, RTT, tasas de observación/acción,
profundidad máxima de cola, errores, edad de frames y estado del enlace. La
ventana móvil está limitada por `RSTACK_DREAM_METRICS_WINDOW`.

El worker usa el mismo DLS incremental del despliegue origen: cada acción EEF
produce un paso limitado por velocidad/aceleración, con la orientación retenida
en errores grandes. No utiliza el solver global antiguo ni rechaza ejecución por
su tolerancia final de 10°. Latencias de chunk superiores a tres segundos se
descartan. Conserva el registro humano `dream.input_check` que imprime Dream;
no se llama `ResetPiper` automáticamente ante un controlador en fallo.

La futura aplicación de operación reutilizará este mismo supervisor; no tendrá
permiso para enviar CAN directamente.

La guía de la consola actual, su API, estados, métricas y el diseño de la app
web completa está en [`docs/APP_OPERATIONS.md`](../../docs/APP_OPERATIONS.md).
