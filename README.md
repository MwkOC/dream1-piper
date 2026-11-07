# Dream-1 para AgileX Piper

Integración de dos brazos Piper con Dream API y el workspace NONHUMAN/HandUMI.
La cámara general es una ZED Mini monocular; ambas cámaras de muñeca son OpenCV.

**Estado:** driver de solo lectura, configuración pendiente de TCP/embodiment y
seis pruebas offline. No hay un driver activo validado para mover los brazos.

## Instalación

```bash
uv venv .venv --python 3.12
uv pip install --python .venv/bin/python -r requirements.txt
source .venv/bin/activate
dreamcli --version
```

Si `.venv` ya existe, omite su creación. Dream Labs 1.0.18 y su cliente 1.0.9 se
instalan desde PyPI; este repositorio no mantiene una copia del monorepo del proveedor.

Para abrir únicamente el editor TCP local:

```bash
dreamcli --home "$PWD/integrations/piper" tcp --host 127.0.0.1
```

Abre la dirección completa que imprima la terminal. Ctrl+C detiene el editor.

## Documentación

- [Tutorial de instalación y editor TCP](TUTORIAL_INSTALACION.md).
- [Configuración Piper y cámaras](docs/SETUP_PIPER.md).
- [Estado del driver y pendientes](docs/DRIVER_STATUS.md).
- [Pipeline de adaptación a XHUMAN](docs/PIPELINE_XHUMAN.md).
- [Notas de arquitectura aportadas por el usuario](docs/notas-arquitectura-usuario.md).

## Estructura

```text
integrations/piper/     driver, cámara ZED y configuraciones
tests/                 pruebas sin cámaras, CAN ni API
docs/                  setup, pendientes, pipeline y notas
requirements.txt       SDK oficial y cliente con versiones fijadas
requirements-dev.txt   dependencias anteriores y pytest
```

Las configuraciones importadas de HandUMI tienen su procedencia en
`integrations/piper/handumi_reference.yaml`. Los URDF y calibraciones físicos
dependen del workspace local; no se inventan ni se incluyen credenciales.

## Pruebas

```bash
uv pip install --python .venv/bin/python -r requirements-dev.txt
.venv/bin/python -m pytest -q tests
```

Las comprobaciones de referencias HandUMI/XHUMAN se omiten si esos workspaces no
están presentes. Las demás pruebas usan dispositivos simulados.

El MCP de Vivaldi se mantiene por separado en
`/home/mwkoc/GITHUB/Mini_Proyectos/tools/vivaldi-mcp`; no es necesario para usar
Dream Labs o abrir el editor TCP.

## Procedencia

SDK oficial: [dreamlabs-co/dreamlabs](https://github.com/dreamlabs-co/dreamlabs),
revisión de referencia `2d2f5239eb737c9271e15054637fe952758d5823`.
El código heredado retirado se conserva en el historial Git; no se reescribe ese
historial. Se mantiene la [licencia Apache-2.0](LICENSE).
