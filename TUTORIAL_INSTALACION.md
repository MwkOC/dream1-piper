# Tutorial: instalar Dream Labs y abrir el editor TCP de Piper

Este tutorial reproduce la instalación de esta integración, en Linux y con
Python 3.12. El entorno `.venv` es independiente de Conda y de los entornos de
HandUMI/XHUMAN. No necesitas el MCP para seguir estos pasos.

**En este equipo Dream Labs ya está instalado. Puedes empezar en el paso 4.**

## 1. Comprobar los requisitos

Abre una terminal y ejecuta:

```bash
git --version
uv --version
```

El procedimiento principal utiliza `uv`, que ya está disponible en este equipo.
Si en otro equipo no tienes `uv`, al final del paso 3 hay una alternativa con
Python y `pip`.

Necesitas conexión a Internet para descargar dependencias. El visor 3D del editor
también carga una biblioteca desde Internet. El editor TCP local no necesita una
API key, cámaras conectadas ni motores encendidos.

## 2. Obtener el repositorio, solo en una instalación nueva

El repositorio es privado: tu cuenta de GitHub debe tener acceso y Git debe estar
autenticado. Si ya tienes la carpeta `dream-1`, omite este bloque y usa el siguiente.

```bash
mkdir -p "$HOME/GITHUB/mu-robotics"
cd "$HOME/GITHUB/mu-robotics"
git clone https://github.com/MwkOC/dream1-piper.git dream-1
cd dream-1
```

Si la carpeta ya existe:

```bash
cd "$HOME/GITHUB/mu-robotics/dream-1"
git status --short
```

No vuelvas a clonar encima de la carpeta existente. No hace falta modificar ni
descartar archivos locales para instalar los paquetes.

## 3. Crear el entorno e instalar Dream Labs

Desde la raíz del proyecto, ejecuta estos comandos **solo si todavía no existe
el entorno `.venv`**:

```bash
uv venv .venv --python 3.12
uv pip install --python .venv/bin/python -r requirements.txt
```

Se instalan desde PyPI los dos paquetes fijados en `requirements.txt`:

| Paquete | Versión instalada en este checkout |
| --- | --- |
| `dreamlabs` | 1.0.18 |
| `dreamlabs-client` | 1.0.9 |

La primera instalación descarga dependencias de vídeo, visualización y cinemática,
por lo que puede tardar varios minutos. Las dependencias transitivas se resuelven
al instalar. El repositorio mantiene la integración Piper, no una copia del SDK.

Si ya existe `.venv` y solo falta instalar los paquetes, ejecuta únicamente:

```bash
uv pip install --python .venv/bin/python -r requirements.txt
```

### Alternativa sin `uv`

Úsala en lugar del procedimiento anterior, si ya tienes Python 3.12 con soporte
para crear entornos virtuales y todavía no existe `.venv`:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

No necesitas ejecutar ambos procedimientos.

## 4. Activar el entorno en cada terminal nueva

Este es el bloque que debes usar normalmente en este equipo:

```bash
cd "$HOME/GITHUB/mu-robotics/dream-1"
source .venv/bin/activate
```

El prompt mostrará `(.venv)`. Si también aparece `(base)`, es porque Conda sigue
activo: comprueba que los comandos que uses correspondan a `.venv`:

```bash
command -v python
command -v dreamcli
python --version
dreamcli --version
```

Las dos primeras rutas deben apuntar a `dream-1/.venv/bin/`. En la instalación
realizada aquí se verificaron Python 3.12.14 y `dreamcli 1.0.18`.

Si prefieres no activar el entorno, también puedes ejecutar directamente:

```bash
cd "$HOME/GITHUB/mu-robotics/dream-1"
.venv/bin/dreamcli --version
```

## 5. Comprobar la instalación

Con el entorno activado:

```bash
dreamcli --version
dreamcli tcp --help
python -c "import dream, dream_ik; from robots import setup_wizard; print('Dream Labs y editor TCP: OK')"
```

Si instalaste con `uv`, puedes comprobar además las dependencias:

```bash
uv pip check --python .venv/bin/python
```

Estas comprobaciones no conectan los brazos ni llaman a la API de inferencia.

## 6. Abrir el editor TCP

Este bloque activa el entorno y arranca el editor, guardando sus archivos de brazo
debajo de `integrations/piper/arms/`:

```bash
cd "$HOME/GITHUB/mu-robotics/dream-1"
source .venv/bin/activate
dreamcli --home "$PWD/integrations/piper" tcp --host 127.0.0.1
```

Deja esa terminal abierta. Si el navegador no se abre automáticamente, copia la
**dirección completa impresa en la terminal**, incluido `?token=...`, y pégala en
Vivaldi. Abrir solo `http://127.0.0.1:8094` puede mostrar un error de acceso si el
navegador todavía no tiene la cookie del editor.

Para imprimir la dirección sin abrir automáticamente un navegador:

```bash
dreamcli --home "$PWD/integrations/piper" tcp --host 127.0.0.1 --no-browser
```

Ejecuta una sola de estas variantes a la vez. Para detener el editor, vuelve a su
terminal y pulsa **Ctrl+C**.

## 7. Si aparece “Address already in use”

Significa que otro proceso ocupa el puerto 8094. Primero busca la terminal donde
dejaste el editor abierto y detenlo con **Ctrl+C**. Puedes consultar el puerto sin
terminar ningún proceso:

```bash
ss -ltnp '( sport = :8094 )'
```

Si prefieres dejar esa instancia funcionando y abrir otra, elige un puerto distinto:

```bash
dreamcli --home "$PWD/integrations/piper" tcp --host 127.0.0.1 --port 8095
```

Usa la nueva dirección impresa. No ejecutes comandos para matar todos los procesos
Python o del navegador.

## 8. Cargar Piper y guardar el TCP

En el editor:

1. Elige **My arm's URDF** y **Choose folder**.
2. En este equipo, selecciona la carpeta siguiente, incluyendo sus meshes:

   ```text
   /home/mwkoc/GITHUB/NoHuman/handumi/handumi-sw/assets/piper
   ```

   Los assets de HandUMI son externos a este repositorio. En otro equipo debes
   disponer de esa carpeta y elegir su ubicación real.
3. Selecciona una cadena de un brazo: base `left_base_link`, flange `left_link6`.
   Comprueba que el editor identifique seis articulaciones móviles.
4. Pulsa **Yes, it ends there** y coloca el marcador donde se encuentran las
   puntas de los dedos cerrados. Las traslaciones de la interfaz están en mm.
5. Orienta los ejes: X en la dirección de cierre, Z hacia fuera de la pinza y Y
   según la referencia visual del editor.
6. Pulsa **Set tool center point** y conserva la ruta del archivo JSON generado.

El URDF HandUMI sitúa nominalmente el TCP a 135.8 mm sobre z de `link6`; verifica
que corresponda a las pinzas instaladas. El editor registra el valor que confirmes,
no realiza una medición física automática.

Luego edita la configuración:

```bash
nano integrations/piper/station.readonly.yaml
```

Sustituye únicamente el valor de `custom.ik` por la ruta del JSON que generó el
editor. Conserva `custom.driver: piper_readonly.py:ReadOnlyArm`. La pose `rest`
generada por el editor también necesita revisión antes de utilizar el modelo IK.

## 9. Salir y volver otro día

Para cerrar el editor: **Ctrl+C** en su terminal. Después puedes salir del entorno:

```bash
deactivate
```

Para volver a abrirlo otro día basta repetir:

```bash
cd "$HOME/GITHUB/mu-robotics/dream-1"
source .venv/bin/activate
dreamcli --home "$PWD/integrations/piper" tcp --host 127.0.0.1
```

## Estado al terminar

Con estos pasos quedan disponibles Dream Labs, `dreamcli` y el editor TCP local.
El driver Piper del repositorio sigue siendo de solo lectura. Registrar el
embodiment, completar el driver activo y validar movimiento son tareas posteriores;
abrir el editor no las realiza automáticamente.

Continúa con la [guía Piper](docs/SETUP_PIPER.md) y el
[estado de los pendientes](docs/DRIVER_STATUS.md).
