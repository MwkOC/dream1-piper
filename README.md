# Dream-1 Piper

Proyecto para separar una aplicación FastAPI de los experimentos de captura y
la adaptación read-only para brazos AgileX Piper.

## Estructura

- [`app/`](app/): aplicación FastAPI y contratos de validación.
- [`experiments/`](experiments/): captura ROS 2/MCAP, driver Piper read-only y
  configuración experimental.
- [`docs/`](docs/): documentación de instalación, estado y arquitectura.
- [`.references/`](.references/): material externo; solo se versiona la
  propuesta de configuraciones.

## Instalación

Cada subproyecto tiene sus propias dependencias y lockfile:

```bash
cd app
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
uvicorn dream1_piper_app.main:app --reload
```

```bash
cd experiments
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m pip install -e '.[dream]'
```

Las dependencias Dream se descargan desde PyPI; el repositorio no contiene una
copia ejecutable de la librería Dream Labs.

## Pruebas

```bash
PYTHONPATH="$PWD/app/src:$PWD/experiments" python3 -m pytest app/tests experiments/tests
```

## Seguridad

El driver Piper es exclusivamente read-only. No se ejecutan motores, inferencia
remota ni control autónomo; las calibraciones físicas y el control activo siguen
pendientes de validación.
