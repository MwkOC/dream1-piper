# Estado del template de driver Piper

Revisión: 2026-11-07.

Actualización HandUMI: se extrajeron las homes y los parámetros nativos a
[`handumi_reference.yaml`](handumi_reference.yaml), con revisión de origen.
La plantilla ya contiene las homes configuradas en HandUMI; no son mediciones
nuevas ni una validación de movimiento en Dream. El TCP nominal de ese URDF es
0.1358 m desde `link6`, y se mantiene pendiente la confirmación del TCP físico.

**El template no está completo para operar los Piper.** Hay una implementación
derivada para leer feedback y comprobar el contrato sin habilitar motores.
El template original se conserva sin editar en
[`driver_template.py`](../../dream_library/robots/src/robots/driver_template.py).
La adaptación está en [`piper_readonly.py`](piper_readonly.py), seleccionada desde
[`station.readonly.yaml`](station.readonly.yaml).

Se intentó consultar la [página indicada del template](https://platform.dreamlabs.ai/docs/drivers/#the-driver-template),
pero el lector web no pudo acceder. Se contrastó el archivo del checkout con el
[template publicado en el repositorio oficial](https://github.com/dreamlabs-co/dreamlabs/blob/main/dream_library/robots/src/robots/driver_template.py).
No se comprobó el contenido de una sesión autenticada de la plataforma.

## Comparación con el contrato oficial

| Parte del template | Implementación actual | Pendiente para un driver activo |
| --- | --- | --- |
| `__init__(cfg, side)` | Abre feedback CAN con `piper_init=False`, lee calibración de pinza y espera feedback | Habilitar manteniendo la posición medida, comprobar fallos y soportar identificación durante setup, cuando `side` aún puede ser un ID de adaptador |
| `read()` | J1..J6 en radianes y pinza entre 0 y 1; comprueba actualización y valores finitos | Validar ceros/signos/orden contra el URDF y medir velocidad real; actualmente reporta velocidad cero |
| `write(positions_rad, gripper)` | Rechaza siempre con error | Enviar objetivos Piper, con conversiones, límites, velocidad y tratamiento de fallos verificados |
| `close()` | Cierra CAN sin ordenar movimiento | Comprobarlo físicamente en el ciclo completo de inicio/cierre y ante fallos |
| `torque_off()` | Solo cierra la conexión; intencionalmente no cambia potencia | Implementar deshabilitación real y definir estacionamiento/soporte según el comportamiento del hardware |
| `disengage()` opcional | Hereda el comportamiento base, devuelve `False` | Decidir si habrá modo manual; si se implementa, comprobar la reactivación sin salto |
| `drops_when_limp` | Hereda `False`; no está caracterizado físicamente | Confirmar comportamiento real al quitar torque y declarar el valor correcto |
| Calibración de pinza | Lee extremos medidos del YAML de XHUMAN | Confirmar archivo completo para ambos lados, límites y fuerza en control activo |

La clase satisface las firmas abstractas para pruebas de lectura, pero eso no
significa que implemente todos los efectos físicos que exige un driver activo.
No seleccionar esta clase para los pasos motorizados del wizard ni quitar
`--dry-run` esperando que mueva los brazos.

## Mediciones y configuración pendientes

1. **TCP y orientación:** rellenar `tcp`, `approach` y `jaw` en
   [`arm.pending.json`](arm.pending.json), medidos en el marco del flange elegido.
   Usar `dreamcli tcp` para confirmar el punto; el offset nominal del URDF no
   sustituye la medida de las pinzas montadas.
2. **Reposo:** completar los seis valores `rest` del modelo IK. Las homes de ambos
   brazos ya se importaron de HandUMI: `[0, 0, 0, 0, 0.4363323, 0]` radianes.
   Comprobar trayectorias de acceso y estado de apertura de pinzas durante home.
   La preferencia `posture_q` de HandUMI es parcial; no permite completar `rest`
   sustituyendo arbitrariamente sus valores `null`.
3. **CAN y geometría:** confirmar izquierda=`can0`, derecha=`can1`, ceros y signos
   J1..J6, límites del firmware y separación/orientación física de bases. El URDF
   local representa 0.60 m de separación; no es un requisito de Dream Labs.
4. **Cámaras:** confirmar los dispositivos persistentes, modos reales y rotación.
   La asignación sigue la corrección del usuario: ZED Mini general `/dev/video2`
   con recorte monocular, OpenCV wrist izquierda `/dev/video0` y OpenCV wrist
   derecha `/dev/video4`. Esta asignación reemplaza los roles del rig local HandUMI.
   Falta verificar captura física y calidad de imágenes para el modelo.
5. **Plataforma:** registrar el embodiment custom, reemplazar
   `REPLACE_ACCOUNT/piper-bimanual`, comprobar los roles de cámara y seleccionar
   un checkpoint EEF realmente accesible para la cuenta.
6. **Control activo:** implementar los métodos anteriores y comprobar arranque,
   reinicio, pérdida de feedback, parada y salida con el hardware supervisado.

Los puntos de implementación de software se pueden desarrollar antes de disponer
de las medidas, usando mocks. El movimiento real requiere las medidas y la
validación física; no deben inventarse para hacer que cargue la plantilla.

## Qué ya está verificado

Seis pruebas offline cubren unidades, apertura de pinza, ausencia de objetivos
de motor, feedback antiguo/no finito, recorte de la ZED, esquema de estación y
seis articulaciones de la cadena del URDF. La comprobación del URDF se omite si
el workspace XHUMAN no existe en la máquina donde se ejecutan las pruebas.
La comprobación de referencias HandUMI se omite si su workspace no está presente.

HandUMI aporta implementaciones de envío, habilitación y deshabilitación que
sirven de base, pero todavía no se han integrado como driver activo de Dream.
Su calibración PICO es mando→herramienta, distinta de flange→pinza. No están
presentes en este equipo sus ceros locales de pinza ni una calibración completa
de extremos compatible con nuestro driver de lectura.

No se ejecutaron motores, inferencia remota, registro de robot ni fine-tuning.
Las calibraciones físicas y credenciales permanecen fuera del repositorio.
