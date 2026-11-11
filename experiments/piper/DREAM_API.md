# Probar la API de Dream Labs con Piper

## 1. Instalar dependencias

Ejecuta estos comandos una vez desde la raíz del repositorio. `install.sh` crea `.venv`, instala las dependencias de `requirements-dream-test.txt` y prepara `.env`. `source` activa ese entorno en la terminal actual; repítelo al abrir una terminal nueva.

```bash
bash install.sh
source .venv/bin/activate
python -m pip install -e 'experiments[dream,dev]'
```

## 2. Conectar y comprobar los brazos

Antes de ejecutar una inferencia, conecta los dos brazos y activa sus interfaces CAN siguiendo [HARDWARE_SETUP.md](HARDWARE_SETUP.md). La prueba `--infer` también necesita leer el estado de los brazos, aunque no envíe comandos de movimiento; comprueba que `can0` y `can1` estén `UP` antes de continuar. Ese documento también explica cómo verificar las cámaras.

## 3. Configurar la clave y el robot

Pega tu API key en `DREAM_API_KEY=` dentro de `.env`, sin comillas ni espacios.
Configura también `DREAM_ARM_FILE` con el JSON generado y confirmado por
`dreamcli tcp`. `.env` no se sube a GitHub; `.env.example` es una plantilla y
debe quedar sin clave real. En [`configs/bipiper.yaml`](../../configs/bipiper.yaml),
comprueba los puertos CAN y la ruta de calibración de las pinzas. Las cámaras se
leen de [`configs/cameras.yaml`](../../configs/cameras.yaml).

```bash
nano .env
nano configs/bipiper.yaml
nano configs/cameras.yaml
```

## 4. Preparar el arm file de Dream

El IK oficial requiere un archivo con URDF, base, flange, TCP, ejes de
aproximación/cierre y postura `rest`. No rellenes esos valores a mano: ejecuta
el editor, confirma el TCP físicamente y conserva el registro de calibración.

```bash
cd experiments
dreamcli --home "$PWD/piper" tcp --host 127.0.0.1
```

En el asistente carga `assets/piper_description.zip` (o la carpeta
`assets/piper_description/`), confirma físicamente el TCP y conserva la ruta
que el wizard imprime dentro de `experiments/piper/arms/`. Indica esa ruta con
`DREAM_ARM_FILE`/`--arm-file`. Sin ese archivo, el probe rechaza la inferencia
antes de conectar cámaras o habilitar motores.

## 5. Comprobar la clave

Lista los checkpoints a los que tiene acceso la cuenta. Este comando consulta la API, pero no abre cámaras ni conecta los Piper.

```bash
cd experiments
dream-piper-models --models
```

## 6. Medir la apertura de las pinzas

Antes de ejecutar `--execute`, mide los extremos físicos de ambas pinzas. El
script conecta los Piper solo para leer la posición; no habilita los motores ni
envía comandos. Mueve cada pinza con el procedimiento seguro de tu hardware y
pulsa Enter cuando esté completamente cerrada y completamente abierta.

```bash
python ../tests/test_gripper_calibration.py
```

Guardará la calibración en
`~/.dreamlabs/bipiper-gripper-calibration.yaml`, que es la ruta configurada en
[`configs/bipiper.yaml`](../../configs/bipiper.yaml). Se toman 15 muestras por extremo y se guarda la
mediana; puedes cambiarlo con `--samples 25`.

## 7. Probar una inferencia

Con los Piper, las cámaras, el arm file y la calibración de pinzas configurados,
el probe captura cada tick de cámara con timestamp monotónico y solicita chunks
articulares oficiales de Dream mediante `ik.head=eef`. Sin `--execute`, solo
valida y muestra la respuesta. Con `--execute`, requiere una comprobación humana
mediante `python -m dream.check`, actualiza observaciones a 30 Hz y deja que el
SDK conserve 9 frames a 5 Hz. Usa `refill_due()`, `commanded`, retries para
errores transitorios y límites del `PiperJointStreamer`. Las solicitudes
repetidas a la API pueden generar cargos. Ejecuta estos comandos desde
`experiments/`.

```bash
dream-piper-models --infer --prompt "pick up the soft object"

# Solo cuando quieras enviar movimiento a los brazos:
dream-piper-models --infer --execute --log data/dream-run.jsonl --prompt "pick up the soft object"
```
