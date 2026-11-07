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

Con los Piper, las cámaras y la calibración de pinzas configurados, captura una observación y solicita un bloque de acciones a Dream Labs. Lee los joints y las pinzas mediante `scripts/driver.py`, y muestra las poses EEF que devuelve el checkpoint YAM. Usa los TCP nominales del URDF solo para describir el estado actual. El script **no convierte las acciones a joints ni envía comandos a los motores**. Para mover los Piper hará falta validar los TCP físicos y la conversión IK; el control articular está en `scripts/piper.py` y `scripts/driver.py`. La solicitud a la API puede generar cargos.

```bash
python tests/test_dream_api.py --infer --prompt "pick up the soft object"
```
