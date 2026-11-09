# Probar la API de Dream Labs con Piper

## 1. Instalar dependencias

Ejecuta estos comandos una vez desde una terminal. `install.sh` crea `.venv`, instala las dependencias de `requirements-dream-test.txt` y prepara `.env`. `source` activa ese entorno en la terminal actual; repítelo al abrir una terminal nueva.

```bash
cd /home/aniela/NONHUMAN/dream1-piper
bash install.sh
source .venv/bin/activate
```

## 2. Configurar la clave y el robot

Pega tu API key en `DREAM_API_KEY=` dentro de `.env`, sin comillas ni espacios. `.env` no se sube a GitHub; `.env.example` es una plantilla y debe quedar sin clave real. En `.env`, revisa también el checkpoint y la ruta del URDF. La prueba lee los enlaces nominales `left_tcp` y `right_tcp` directamente del URDF; no pide medidas TCP aparte. En `configs/bipiper.yaml`, comprueba los puertos CAN y la ruta de calibración de las pinzas. Las cámaras se leen de `configs/cameras.yaml`.

```bash
nano .env
nano configs/bipiper.yaml
nano configs/cameras.yaml
```

## 3. Comprobar la clave

Lista los checkpoints a los que tiene acceso la cuenta. Este comando consulta la API, pero no abre cámaras ni conecta los Piper.

```bash
python tests/test_dream_api.py --models
```

## 4. Probar una inferencia

Con los Piper, las cámaras y la calibración de pinzas configurados, la prueba captura la observación y solicita un bloque de acciones a Dream Labs. Sin `--execute`, solo muestra ese bloque. Con `--execute`, mantiene un ciclo continuo hasta Ctrl-C: actualiza observaciones y cámaras a 5 Hz mientras ejecuta cada bloque y usa `client.refill_due()` del SDK para pedir el siguiente bloque por adelantado. En modo asíncrono, la siguiente acción toma el control en el horizonte configurado por Dream; en modo síncrono, termina el bloque actual y mantiene la última posición durante la inferencia. La IK del bloque recibido se prepara en paralelo con la ejecución activa. Envía las juntas al `PiperJointStreamer` de `scripts/driver.py` y aplica los límites de `scripts/constants.py`, la calibración local de pinzas, 20 grados por segundo de velocidad articular, 60 grados por segundo cuadrado de aceleración y 3 unidades normalizadas por segundo para la pinza. Valida el bloque entero antes de ejecutarlo; si alguna pose no es alcanzable dentro de 2 cm y 10 grados, aborta ese ciclo. Por cada inferencia imprime una línea JSON con la latencia total observada (`latency_wall_ms`), el RTT HTTP del SDK, la latencia reportada por el modelo y el gateway, y el modo de pacing. Antes de usarlo en el robot real, confirma que los TCP nominales y la convención de rotación del URDF coincidan con el Piper físico. Las solicitudes repetidas a la API pueden generar cargos.

```bash
python tests/test_dream_api.py --infer --prompt "pick up the soft object"

# Solo cuando quieras enviar movimiento a los brazos:
python tests/test_dream_api.py --infer --execute --prompt "pick up the soft object"
```
