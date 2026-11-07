# Setup Dream Labs para dos AgileX Piper

Revisión: 2026-10-29, SDK del checkout `2d2f5239eb737c9271e15054637fe952758d5823`.

La opción adecuada de la captura es **Set up your own robot**. Los seis robots
anteriores son integraciones ya preparadas; no son una lista cerrada de cuerpos
compatibles. No seleccionar YAM, Maker o Metal como sustituto de Piper: cambian
driver, cinemática, ceros y límites aunque tengan el mismo número de articulaciones.

## Qué está preparado y qué falta

- `station.readonly.yaml`: plantilla `body: custom`, CAN por lado y tres cámaras.
- `piper_readonly.py`: driver de feedback compatible con el contrato `Driver` de
  Dream. Abre el SDK con `ConnectPort(piper_init=False)`, no habilita motores,
  rechaza todos los objetivos y desconecta sin movimiento ni cambio de potencia.
- `zed_left.py`: fuente de cámara custom que recibe estéreo UVC y entrega solo el
  ojo izquierdo, como el backend `zedmini` de XHUMAN.
- `arm.pending.json`: selección de cadena del URDF local; TCP, ejes de la pinza y
  pose de reposo pendientes. Es deliberadamente inválido hasta medirlos.
- `test_piper_setup.py`: comprobaciones offline con CAN y vídeo simulados.

La plantilla aún no puede ejecutar una política: el TCP y el embodiment pendientes
impiden tratarla como una estación lista. Las poses `home` se importaron de la
configuración de HandUMI y todavía requieren comprobación física en Dream.
Tampoco se incluye un driver
activo. Completarlo exige comprobar correspondencia física/URDF, habilitación con
feedback, velocidad, fuerza de pinza y comportamiento de parada/torque-off; no
basta cambiar el nombre de la clase. El driver de lectura no sirve para los pasos
del asistente que mueven articulaciones, descubren lados o graban el área de alcance.

## Ruta por la plataforma y el asistente local

1. En `https://platform.dreamlabs.ai/d`, entrar en **Set up your own robot**.
   La tarjeta de tu captura ya dice que permite zero-shot o registrar el cuerpo
   para fine-tuning. No hace falta escoger un cuerpo de otra marca.
2. Seguir la instalación del cliente/biblioteca completa y configurar la API key
   con el método de credenciales de la plataforma. No ponerla en estos archivos.
   Para que el entorno coincida exactamente con el código revisado, el README del
   monorepo permite instalar ambos paquetes desde el checkout:

   ```bash
   cd /home/mwkoc/GITHUB/mu-robotics/dream-1
   # En un entorno Python 3.12 dedicado, no sobre el entorno operativo de XHUMAN:
   pip install ./dream_library/dream_client ./dream_library
   pip install piper_sdk
   ```

3. La ruta custom del código local ofrece **My arm's URDF** y **Set it up myself**.
   Para preparar el modelo geométrico sin abrir los motores, usar primero
   `dreamcli tcp`: es el editor de URDF/TCP por separado, sin clave ni driver.
   `dreamcli setup` completo sí puede abrir y habilitar los brazos a través del
   driver; no confundir ambos comandos.
4. En el editor cargar la carpeta
   `/home/mwkoc/GITHUB/nonhuman/XHUMAN/assets/piper`, incluyendo `meshes`. El URDF
   actual es bimanual: elegir explícitamente **una cadena** con base
   `left_base_link` y flange candidato `left_gripper_base` (o `left_link6` si se
   decide medir el TCP en ese marco). No aceptar automáticamente `world` como base
   ni una punta móvil de un dedo como flange.
5. Confirmar físicamente el punto entre los dedos cerrados y su orientación, y
   guardar el archivo de brazo generado por la herramienta. Sustituir `custom.ik`
   por esa ruta. Si cambia el flange, todas las medidas del TCP deben expresarse
   en el nuevo marco; no reutilizar coordenadas del otro link.
6. Registrar un embodiment propio de seis articulaciones por brazo, utilizando
   el flujo zero-shot para URDF del asistente. Este usa
   `robots.adapter.zero_shot_embodiment(6)`, que incluye partes EEF y los roles
   `overhead`, `wrist_l`, `wrist_r`. El resultado tiene un nombre real
   `<cuenta>/<nombre>`: reemplazar `REPLACE_ACCOUNT/piper-bimanual`. No reutilizar
   el ID de un cuerpo YAM ni inventar un ID de checkpoint.
7. Para comprobaciones de lectura elegir la ruta manual y
   `piper_readonly.py:ReadOnlyArm`. Las acciones de verificación bajo potencia del
   asistente requieren el futuro driver activo y no podrán completarse con este.
8. Una vez medidos los `home`, confirmado el TCP, registrado el embodiment y
   consultado un checkpoint EEF disponible con `DreamClient.get_models()`, el
   comando de contrato es:

   ```bash
   dreamcli robot run \
     --config /home/mwkoc/GITHUB/mu-robotics/dream-1/integrations/piper/station.readonly.yaml \
     --checkpoint <ID_REAL_DEL_MODELO_EEF> \
     --task "pick up the soft object" --dry-run
   ```

   Los valores entre `<...>` son marcadores que debes sustituir. Esta llamada
   usa realmente la API y puede facturar; no se ejecutó durante esta revisión.
   `--dry-run` evita objetivos desde el bucle, pero por sí solo no impide que un
   constructor de driver habilite motores: por eso se preparó `ReadOnlyArm`.

No pude inspeccionar la página autenticada: el lector web no pudo acceder a `/d`
y la herramienta de navegador no tiene navegadores conectados. Los nombres del
asistente local anteriores están verificados en `setup_wizard.html` y el SDK del
checkout; no afirmo que la web autenticada tenga exactamente los mismos pasos.

## Valores del setup para este workspace

| Campo | Configuración |
| --- | --- |
| Tipo de cuerpo | `custom` |
| Brazos | Dos Piper, 6 articulaciones por lado y pinza paralela |
| CAN izquierdo / derecho | `can0` / `can1`, según `XHUMAN/bin/set_env.sh`; confirmar conexión física |
| Modelo IK | Archivo propio de URDF/TCP medido, cabeza de acción EEF |
| `home` izquierdo y derecho | Importadas de HandUMI: J5=0.4363323 rad (25°), las otras cinco articulaciones a cero; verificar trayectoria |
| `rest` del brazo IK | Pose de trabajo medida; el cliente aplica el mismo modelo a ambos lados |
| Cero y dirección | J1..J6 nativos del driver moderno Piper, comprobar visualmente con el URDF |
| Pinza | Apertura calibrada entre 0 y 1, extremos independientes por lado |
| Cámara general | `overhead`, ZED Mini solo ojo izquierdo |
| Cámaras de muñeca | `wrist_l` y `wrist_r`, comprobar que los lados y la rotación coincidan |
| Frecuencia del bucle | 20 Hz en la plantilla, default de la estación Dream; no mezclar con 30/50 Hz de XHUMAN |
| Historial de vídeo | 9 frames a 5 Hz según SDK; captura solicitada 30 fps |
| Modelo | Checkpoint EEF realmente disponible para la cuenta; no hay un checkpoint Piper implícito |

### Dos rutas Piper diferentes en XHUMAN

La revisión del código encontró ambas rutas, que no deben mezclarse:

- `xhuman/robots/piper/driver.py` y `piper.py`: API pública en radianes, feedback
  SDK J1..J6 en miligrados convertido con `pi / 180000`. Esta es la referencia
  usada por el driver de lectura nuevo. No añadirle `JOINT_SIGNS` del follower.
- `bi_piper_follower` y `piper_sdk_interface.py`: posiciones normalizadas
  [-100,100], signos y límites internos propios. Un futuro puente por el servidor
  de robot existente tendrá que invertir esa transformación antes de hablar con
  Dream. Los valores de `home` de Dream no se copian desde esta escala.

El driver de lectura reutiliza los extremos medidos del archivo de XHUMAN:
`$XHUMAN_PIPER_GRIPPER_CALIBRATION` o, por defecto,
`${XDG_CACHE_HOME:-~/.cache}/xhuman/piper_grippers.yaml`. Exige `closed_microm`
y `open_microm` válidos para el lado solicitado y rechaza feedback ausente,
no finito o que deja de actualizarse durante 0.2 s. Informa velocidad cero porque
esta ruta solo verifica posiciones y apertura; no es un sensor de velocidad.

No se ejecutó el SDK contra CAN. La comprobación física de signos, ceros y límites
es imprescindible para convertir esta referencia en control activo.

### Colocación de brazos y calibración

El URDF local representa las bases a y=+0.30 m e y=-0.30 m, es decir, 0.60 m de
separación. Ese es un valor del workspace, no una separación obligatoria de Dream.
Medir la instalación real antes de reutilizar esa geometría. Dream resuelve cada
cadena en su propio marco de base; elegir `left_base_link` evita arrastrar el
offset lateral del mundo al modelo de cada brazo.

No hace falta fabricar una separación para imitar YAM, pero sí conservar un área
de trabajo compartida alcanzable y comprobar las colisiones con el otro brazo,
mesa y soporte de cámara. Las restricciones `reach`, `keep_out` y `region` que
documenta el cliente son por brazo y se deben definir con las dimensiones reales.
No se presupone detección de colisión entre ambos brazos. La plantilla no contiene
obstáculos ni áreas medidas; no está preparada para movimiento.

El código local también trae un TCP nominal de 0.145 m. Su presencia en XHUMAN no
certifica que corresponda a tus dedos/cámara/soporte: no se copió a la configuración.

Para leer posiciones sin tener todavía un embodiment ni llamar a la API, después
de instalar la biblioteca y verificar CAN/calibración de pinzas, se puede ejecutar:

```bash
cd /home/mwkoc/GITHUB/mu-robotics/dream-1/integrations/piper
python - <<'PY'
from types import SimpleNamespace
from piper_readonly import ReadOnlyArm
for side, port in (("left", "can0"), ("right", "can1")):
    # Solo determina el número de articulaciones; ReadOnlyArm nunca usa esta lista como objetivo.
    arm = ReadOnlyArm(SimpleNamespace(can_channel=port, home=[0] * 6), side)
    try:
        reading = arm.read()
        print(side, reading.positions_rad.tolist(), "opening", reading.gripper)
    finally:
        arm.close()
PY
```

Este comando abre únicamente feedback; no se ha ejecutado aquí contra los brazos.
Una lectura no se convierte automáticamente en `home`: elegir y comprobar primero
la postura física y su trayectoria de acceso. El setup de Dream abre la pinza en
algunos movimientos de home, mientras la home nativa de Piper en XHUMAN la define
cerrada; ese comportamiento también debe comprobarse antes de añadir el driver activo.

### ZED Mini: evitar enviar dos vistas como una sola

XHUMAN solicita UVC 1344×376 y recorta el ojo izquierdo a 672×376. La fuente
`zed_left.py:ZedLeft` conserva exactamente esa operación y entrega BGR como exige
el contrato de cámara Dream; la estación hace después la conversión de color.

En la plantilla, `width: 672` y `height: 376` son el tamaño monocular que recibe
Dream. La fuente solicita el doble de ancho a V4L2 y rechaza un tamaño diferente;
así no recorta por error una imagen que ya es monocular. La ruta actual por defecto
es `/dev/video2`. Para fijar el dispositivo de forma persistente:

```bash
export PIPER_ZED_DEVICE=/dev/v4l/by-id/REPLACE_ZED_COLOR_NODE
```

Si la ZED ya se procesa por XHUMAN y se entrega un solo ojo, reutilizar esa salida
en el futuro puente en vez de aplicar este recorte por segunda vez. No abrir las
mismas cámaras ni CAN simultáneamente desde la estación Dream y XHUMAN.

### Wrist fisheye de aproximadamente 200°

La API acepta imágenes, pero eso no demuestra robustez zero-shot a esa óptica.
No encontré en el SDK una focal, FOV o posición numérica obligatoria. Tampoco una
garantía de que rectificar a 100–120° mejore el modelo: ese rango mencionado antes
en el chat era una propuesta experimental, no una recomendación oficial.

La plantilla usa las vistas crudas como baseline. Comprobar la pinza, el objeto y
la zona delante de ella en cada vista; verificar la imagen final a 320×176. Las
resoluciones wrist 640×480 son provisionales y deben reemplazarse por modos
realmente negociados. Fijar además rotación, exposición y dispositivos persistentes.

Si se prueba rectificación, calibrar cada lente con un modelo que cubra realmente
su óptica; no aplicar una calibración de lente convencional por defecto a un FOV
de 200°. Comparar raw y rectificada con los mismos episodios, y luego mantener el
mismo procesamiento en grabación, fine-tuning e inferencia. No hay rectificación
automática implementada aquí porque faltan intrínsecos y distorsión medidos.

## Verificación offline realizada

```bash
cd /home/mwkoc/GITHUB/mu-robotics/dream-1
PYTHONDONTWRITEBYTECODE=1 \
PYTHONPATH="$PWD/dream_library/robots/src:$PWD/dream_library/dream_client/src:$PWD" \
  /home/mwkoc/miniconda3/envs/xhuman/bin/python -m pytest -q integrations/piper/test_piper_setup.py
```

Las pruebas comprueban recorte del ojo/color, conversión miligrados→radianes,
apertura con extremos medidos, ausencia de comandos de motores, rechazo de
feedback antiguo/NaN, coherencia con la configuración HandUMI y seis articulaciones en la cadena.
Usan mocks y el URDF local; no instalan paquetes, leen cámaras, acceden a CAN,
registran robots ni consumen la API. No validan físicamente la calibración.

## Extracción de HandUMI

Se revisó `handumi-sw` y se extrajeron sus datos a
[`handumi_reference.yaml`](handumi_reference.yaml). La referencia incluye el commit
de origen, las poses `home`, la preferencia parcial de postura, los parámetros de
control nativo y el TCP nominal del URDF. No importa ni ejecuta el driver de HandUMI.

La home de cada brazo es `[0, 0, 0, 0, 0.4363323, 0]` en radianes, con la pinza
cerrada en HandUMI. Dream puede abrir la pinza durante home: la equivalencia de las
seis articulaciones no elimina esa diferencia. `posture_q` deja tres coordenadas
articulares por lado en `null`; no es una pose `rest` completa para Dream.

El URDF de HandUMI corrigió el TCP desde 0.145 m a **0.1358 m** sobre z de `link6`.
Se conserva como referencia nominal, sin rellenar `tcp`, `approach` ni `jaw` de
`arm.pending.json`: todavía hace falta confirmar el conjunto físico y sus ejes.
La calibración `controller_tcp/pico_piper_beta.yaml` está medida en el marco del
mando PICO; copiar su posición como TCP de Dream mezclaría dos transformaciones
distintas. Se documentó la diferencia en vez de trasladar esas coordenadas.

Los métodos `send_mdeg`, `send_gripper_microm`, `disable_arm`, `disable_gripper`,
`disconnect` y la habilitación con posición inicial medida de
`src/handumi/real/piper/driver.py` son referencias concretas para un driver activo.
El constructor puede resetear y habilitar motores, por lo que no se instancia para
extraer información. La política de estacionamiento/deshabilitación todavía debe
adaptarse al ciclo de vida de Dream.

No se encontró `~/.cache/handumi/piper_grippers.yaml` ni el equivalente XHUMAN en
este equipo. HandUMI guarda solo `closed_microm` por lado, mientras nuestro driver
de lectura exige además `open_microm`; no basta cambiar la ruta del archivo.
HandUMI resuelve el recorrido por parámetros del controlador/SDK y permite
configuración por lado, pero no existe aquí una captura física exportada de ambos
extremos que podamos importar como calibración medida.

Finalmente, `configs/rig.yaml` de HandUMI asigna la ZED a `right_wrist` y `/dev/video4`
a `workspace`, en conflicto con la ZED top que describiste. Se mantiene la
asignación de cámaras de nuestra plantilla hasta comprobar el montaje actual.
No se copió el rig completo ni sus datos de red.

## Referencias verificadas

- [Plataforma indicada por el usuario](https://platform.dreamlabs.ai/d).
- [Guía de robots propios](../../dream_library/robots/README.md#a-robot-of-your-own).
- [Ejemplos oficiales y contrato de driver](../../dream_library/robots/examples/README.md).
- [Plantilla custom oficial](../../dream_library/robots/configs/custom.example.yaml).
- [Asistente local y campos URDF/driver/cámaras](../../dream_library/robots/src/robots/setup_wizard.html).
- [API y formato del archivo de brazo](../../dream_library/dream_client/README.md).
- [Pipeline general de XHUMAN](../../PIPELINE_DREAM1_XHUMAN.md).
