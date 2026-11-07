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

Con los Piper, las cámaras y la calibración de pinzas configurados, captura una observación, solicita un bloque de acciones a Dream Labs y calcula objetivos articulares con `scripts/dls.py`. Usa el TCP nominal del URDF: en este archivo está a `0.145 m` de `link6`, mientras que el origen de los dedos está a `0.1358 m`. Es una prueba de API y geometría, no una validación del TCP físico. El script **no envía comandos a los motores**. La solicitud a la API puede generar cargos.

```bash
python tests/test_dream_api.py --infer
```
