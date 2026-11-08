# Arquitectura unificada para PiPER + ZED Mini + VLA / JEPA / World Action Models

La arquitectura que te describieron:

> Cámara captura → entrega joints → brazo recibe una nueva posición con velocidad y aceleración parametrizadas → se mueve.

Es una simplificación válida del flujo de control, pero tiene una imprecisión importante: la cámara no entrega directamente los joints. La cámara proporciona observaciones visuales; un algoritmo o una red neuronal puede convertir esas observaciones, junto con el estado del robot, en una acción. Los ángulos articulares reales los proporciona el propio brazo mediante sus encoders y controladores.

Para tu investigación de pick-and-place, propondría una arquitectura con adquisición multimodal única, procesadores intercambiables y un controlador robótico común. Esto permitirá evaluar un algoritmo convencional, SmolVLA, un modelo basado en JEPA y DreamZero o Dream-1 sin modificar la infraestructura física.

## 1. Las fuentes de información del sistema

[MMaDA-VLA: Large Diffusion Vision-Language-Action Model](https://images.openai.com/static-rsc-4/tPW1nvaj5RpWy4PrPnbwnED81IQk29QXAxHTpJsJq0HLGhe_A7zFecwCQUtIX4fhd6hNZNZVtTb_zfZIxGU7hQ0SzZksa3agFuHGBYSAad1H0syS-YBemxCFEwAbn0GV7rfhPcGhrNiN5wMjL5xaVl2HkPh5HX80gz67YoWflmQ?purpose=inline)

PiPER izquierdo y derecho

Cada brazo proporciona 6 posiciones articulares, velocidades, estado de su pinza y retroalimentación de ejecución mediante su controlador.

[Continuous Trajectory Recording and Replay for AgileX PIPER - Hackster.io](https://images.openai.com/static-rsc-4/CxB2amrgbwPNsFJiu8pxvSvuC7uqs3QAuGdADpVx6UZ-P9ynsKPOkmhYSgD6TDzTWM6mAx3LxGBapwmLlprZiZiRxfRmr02CzMKZpPzrFLILqoTwffztVsAo8VpJYbykHYOLxFF8PJGpIWZM8ZY_ClJ3YngQesjdhA7UnwHSmZQ?purpose=inline)

Cámara de cada brazo

Vista local desde la muñeca para aproximación, agarre y alineación. La modalidad RGB o RGB-D depende del modelo instalado.

[ZED Mini Stereo Camera
 – InDro Robotics Store](https://images.openai.com/static-rsc-4/BuLdLINuGvjrg4yBvB5IdyKLhyf8KZPVNbBAisPg7yNOKuDPHmytACHzCk5ZdM7UkC2PtNpZuhJjHxVR1D1HJQ3e1anpA-9gMGG4ybcnV8Q8UP7dhXNk1RWiJG3oVunTD0RIdlhqNAExk5gje7wY7ZwvZerv4u7jfBpHiUqVCgs?purpose=inline)

ZED Mini

Vista global estéreo, RGB rectificado, profundidad métrica y puntos 3D calculados por el SDK.

No debe suponerse que las cámaras de las muñecas sean ZED Mini ni que entreguen profundidad. Por ejemplo, en una configuración bimanual PiPER documentada en Video2Act se usan una RealSense D435 frontal y dos Orbbec Dabai de muñeca.

shoepaly.app

En el sistema resultante existirían cuatro tipos de información:

| Fuente                  | Variable                         | Tipo de información         |
| ----------------------- | -------------------------------- | --------------------------- |
| ZED Mini                | `rgb`, `depth`, `pointcloud`     | Percepción externa 2D/3D    |
| Cámara izquierda        | `rgb_left`                       | Percepción local del agarre |
| Cámara derecha          | `rgb_right`                      | Percepción local del agarre |
| PiPER izquierdo/derecho | `q`, `dq`, `gripper`, `tcp_pose` | Estado propio del robot     |
| Controlador             | `q_target`, `q_actual`, estado   | Órdenes y retroalimentación |

El controlador oficial ROS 2 de AgileX publica posiciones en radianes, velocidades en rad/s y esfuerzos, y acepta comandos de posición de joints o poses del efector final.

GitHub

La distinción esencial para la investigación es que una observación visual, un estado articular, una acción propuesta y una acción realmente ejecutada son cuatro cosas diferentes. No deben mezclarse en el dataset.

## 2. Arquitectura propuesta por capas

La siguiente arquitectura conserva los datos originales y permite cambiar solamente el módulo de decisión.

CAPA 1 · Hardware y adquisición

ZED Mini · Cámara muñeca L/R · CAN PiPER L/R

CAPA 2 · Drivers y ROS 2

ZED SDK · Drivers de cámaras · PiPER SDK

RGB, depth, joint_states, gripper, timestamps

CAPA 3 · Sincronización y calibración

Timestamp común · TF2 · Intrínsecos · Extrínsecos

CAPA 4 · Observación unificada

Observation(t): RGB multivista + Z + joints + pinzas + instrucción

ALGORITMO

Geometría + IK + MoveIt 2

VLA

SmolVLA

JEPA

VLA-JEPA / JEPA-WAM

WAM

DreamZero / Dream-1

CAPA 5 · Adaptador de acciones

Pose EEF o joints → IK/FK → objetivos articulares

CAPA 6 · Planificación y seguridad

Límites, colisiones, velocidad, aceleración y trayectoria

CAPA 7 · Ejecución y retroalimentación

ROS 2 → CAN → PiPER → q real → nueva observación

CAPA TRANSVERSAL · Recorder y evaluación

Registra todas las fuentes, predicciones, comandos, estados reales, latencias y resultados.

Aquí la capa 4 es la interfaz común de entrada y la capa 5 es la interfaz común de salida. Estas dos capas son las que deben permanecer estables durante toda la investigación.

## 3. Formato único de captura

En lugar de unir los bytes de la ZED, los fotogramas de muñeca y los datos CAN, recomiendo construir un objeto lógico `Observation(t)`.

Un ejemplo simplificado:

```
{
  "timestamp_ns": 1794069971000000000,
  "episode_id": "pick_place_0001",
  "task": "Colocar el cubo rojo en la bandeja",
  "cameras": {
    "global": {
      "rgb_ref": "frame_global_00120",
      "depth_ref": "depth_00120",
      "frame_id": "zed_left_optical"
    },
    "wrist_left": {
      "rgb_ref": "frame_left_00120"
    },
    "wrist_right": {
      "rgb_ref": "frame_right_00120"
    }
  },
  "robot": {
    "left": {
      "q_rad": [0.0, 0.1, -0.2, 0.0, 0.3, 0.0],
      "dq_rad_s": [0, 0, 0, 0, 0, 0],
      "gripper_open_m": 0.06
    },
    "right": {
      "q_rad": [0.0, -0.1, 0.2, 0.0, -0.3, 0.0],
      "dq_rad_s": [0, 0, 0, 0, 0, 0],
      "gripper_open_m": 0.08
    }
  }
}
```

Valores y marcas de tiempo ilustrativos. Las referencias de imagen apuntan a archivos o buffers externos, no contienen los píxeles directamente.

El esquema debe incluir también metadatos de calibración, unidades, transformaciones y validez de cada muestra.

### Dimensionalidad para dos PiPER

Suponiendo seis articulaciones y una pinza escalar por brazo:

| Variable                | Dimensión | Tipo             |
| ----------------------- | --------- | ---------------- |
| Posiciones articulares  | 12        | `float32`, rad   |
| Apertura de pinzas      | 2         | `float32`, m     |
| Velocidades articulares | 12        | `float32`, rad/s |
| RGB global              | H × W × 3 | `uint8`          |
| RGB muñeca L            | H × W × 3 | `uint8`          |
| RGB muñeca R            | H × W × 3 | `uint8`          |
| Profundidad global      | H × W     | `float32`, m     |

En consecuencia, puedes definir un vector mínimo de posiciones:

\[
s_t=[q^L_1,\ldots,q^L_6,g^L,q^R_1,\ldots,q^R_6,g^R]
\]

Su dimensión es 14, mientras que las velocidades y demás mediciones se conservan como atributos adicionales.

El driver oficial de AgileX diferencia la posición de la pinza, expresada como apertura física, del estado y esfuerzo de la misma.

GitHub

## 4. Sincronizar todas las fuentes

Esto es especialmente importante porque una cámara puede entregar un fotograma cada 33 ms y el brazo puede publicar estados a una frecuencia mucho mayor.

Como configuración inicial de experimentación, propongo:

| Flujo                  | Frecuencia objetivo      |
| ---------------------- | ------------------------ |
| ZED Mini RGB/depth     | 30 Hz                    |
| Cámaras de muñeca      | 30 Hz, si lo permiten    |
| Feedback PiPER         | 100–200 Hz, según driver |
| Inferencia de política | 5–10 Hz inicialmente     |
| Ejecución/seguimiento  | Según controlador y modo |

Estas son frecuencias de diseño, no mediciones del hardware instalado. El driver de AgileX documenta una publicación configurable con valor predeterminado de 200 Hz.

GitHub

Para cada observación en el instante \(t\):

\[
O_t =
\left(
I^{G}_t,\,
D^{G}_t,\,
I^{L}_t,\,
I^{R}_t,\,
q_t,\,
\dot q_t,\,
g_t
\right)
\]

La recomendación es que el sincronizador utilice el instante de adquisición de las imágenes y alinee los estados articulares mediante interpolación temporal, siempre que existan muestras válidas que rodeen ese instante.

Debes registrar:

- Tiempo de captura del dispositivo y tiempo de llegada al host.

- Tiempo de inferencia y envío de acción.

- Tiempo de recepción del comando y feedback real.

- Antigüedad de cada observación y pérdidas de fotogramas.

Para inferencia causal en tiempo real, no debes utilizar mediciones futuras que todavía no estén disponibles. Los datos futuros pueden conservarse para supervisión durante entrenamiento, particularmente en JEPA.

## 5. Calibración espacial: lo que conecta RGB-D con joints

La ZED puede estimar una posición tridimensional respecto a su propia cámara. Pero PiPER necesita una posición respecto a la base del robot.

Para convertir un punto observado en la ZED:

\[
\mathbf p_{\mathrm{base}} =
T_{\mathrm{base}\leftarrow\mathrm{zed}}
\mathbf p_{\mathrm{zed}}
\]

Para una cámara fijada a la muñeca:

\[
T_{\mathrm{base}\leftarrow\mathrm{cam}}(t)
=
T_{\mathrm{base}\leftarrow\mathrm{eef}}(q_t)
T_{\mathrm{eef}\leftarrow\mathrm{cam}}
\]

La primera transformación puede permanecer fija cuando la ZED está inmóvil, como sugiere la instalación de la fotografía. La segunda cambia con las articulaciones del brazo.

Esto exige calibración cámara-robot (hand-eye), intrínsecos y extrínsecos. La ZED ya dispone de calibración intrínseca estéreo proporcionada por Stereolabs, pero eso no sustituye la calibración respecto a los PiPER.

StereoLabs

Sin estas transformaciones, una red puede aprender una política visual, pero no podrás comparar correctamente sus errores espaciales con un algoritmo geométrico.

## 6. Unificar la salida de ALGORITMO y RED

Propongo dos niveles de acción:

Acción semántica común: pose objetivo del efector final y apertura deseada de la pinza.

\[
a_t^{EEF} =
\left[
x,y,z,q_x,q_y,q_z,q_w,g
\right]
\]

Son ocho valores por brazo: tres de posición, cuatro para orientación mediante cuaternión y uno para la pinza.

Acción física común: posiciones articulares deseadas, con la pinza.

\[
a_t^{joint} =
[q^*_1,q^*_2,\ldots,q^*_6,g^*]
\]

El adaptador de control convierte las acciones cartesianas a joints:

\[
q^* = IK(T^*_{\mathrm{eef}},q_{\mathrm{actual}})
\]

Luego se aplican límites articulares, comprobaciones de colisión y parametrización temporal.

| Procesador           | Qué produce originalmente              | Qué hace el adaptador                                       |
| -------------------- | -------------------------------------- | ----------------------------------------------------------- |
| Algoritmo geométrico | Pose de agarre 3D                      | IK → joints                                                 |
| SmolVLA              | Chunk de acciones continuas            | Desnormaliza e interpreta el espacio de acciones entrenado  |
| VLA-JEPA             | Chunk de acciones continuas            | Igual que VLA, ajustado a la configuración de entrenamiento |
| DreamZero            | Acciones de su representación robótica | Conversión a acción común según checkpoint/adaptación       |
| Dream-1              | Poses EEF o joints compatibles         | IK si entrega EEF → joints                                  |

Dream-1 es especialmente pertinente porque su propuesta de generalización entre robots utiliza la pose de los efectores finales como interfaz común. Además, trabaja con tres vistas: una global y dos de muñeca.

Dream Labs

Punto importante sobre velocidad y aceleración: no basta con transmitir una nueva posición para afirmar que ambas están parametrizadas. El driver PiPER permite configurar un porcentaje de velocidad, pero el perfil de aceleración depende de la interfaz de movimiento y del controlador elegido. Para experimentar de manera comparable, conviene parametrizar trayectorias sujetas a límites de velocidad y aceleración y verificar esos límites con feedback. Evitaría enviar saltos articulares sin interpolación.

## 7. Qué arquitectura corresponde a cada modelo

[Design and implementation of a 6-DoF robot arm control with object detection based on machine learning using mini microcontroller · Clear Sky Science](https://images.openai.com/static-rsc-4/vu66q4vYR6lhXW-Vq1ETd0TXNW0PSE8PSV03gjBLmldIOghQ9xi_Z6iqZO1m4teh-CnUATQJf7Mv3zeM51s95hisIKwOYWEbEm1yFsizixO5q3lu9uZE0ORrocJVpqjJ8qhx1tHTY-8FAfnKEjzpp1vdFdSY16i9_Ee-lc7RoOY?purpose=inline)

Algoritmo geométrico + MoveIt 2

RGB-D → detección/segmentación → posición 3D → planificación de agarre → IK → trayectoria.

Baseline interpretable. Sirve para medir precisión geométrica, robustez y coste computacional sin entrenamiento neuronal de política.

[Lesson 3: The Transformer Revolution – Physical AI Laboratory](https://images.openai.com/static-rsc-4/0iiQzsX-lniU9U_EIx_dr-_wjMtE6YcNAf7ZTc3yq2H58QC4bj1WaDUzenSjis3RwSIAuLXo0tMQSGrSFsWerEztjmGxqrhtYboSSvoHDWnTWiM5aI3DeLiZi_-4Gt_boBx9IixXyI4vmMfiRkvEwWW1XKyYFAiM6fK4XLs0qjs?purpose=inline)

SmolVLA

RGB multivista + estado propio + instrucción → acción continua por bloques.

Es una referencia conveniente para fine-tuning en LeRobot con demostraciones propias.

GitHub

[VLA-JEPA: Enhancing Vision-Language-Action Model with Latent World Model](https://images.openai.com/static-rsc-4/OzZlJNAegHbT_27ZOBqgHTYGN6WoitJwZuFFHK5mS3cI2IiWmzDtXhNdwhC95h0g98hT4KWiMzTcCqWtYIU6hvlXGliYZt3RxPL_CQVJx9Vc0aazbDZeGjjLH9U9iESCD6g9KiQXS5xw_ie0wDI1xhrDnNeaXJh7LX9jdChUrHg?purpose=inline)

VLA-JEPA

RGB + instrucción + propriocepción → backbone multimodal y experto de acciones. Durante entrenamiento, una pérdida adicional predice representaciones visuales futuras.

La implementación actual de LeRobot incorpora checkpoints, fine-tuning y opción de desactivar la pérdida JEPA. En inferencia utiliza el backbone y el experto de acciones, sin ejecutar el predictor del futuro.

Hugging Face

[DreamZero：基于世界行动模型的零样本机器人策略 - 技术栈](https://images.openai.com/static-rsc-4/Oawxr3M18lWT2V8j3mUFa33OVGhFug7lP3BkDjY690R5KyWs6APpGY9KcXY_LnKM45bYSwamTS7L9MVH68P7itNfTZE60DwAjUHgIGj9JeVZR0S0LW0q9fUvcrZjFtYqo1a2wGvKOwtxGiECo7xqIBtulOqQ0-1DzJ5Cll5l0tE?purpose=inline)

DreamZero

Observaciones + lenguaje + estado → predicción conjunta de evolución visual y acciones.

Representa una familia generativa de WAM. El proyecto tiene código y checkpoints públicos, pero su coste computacional es considerable frente a un VLA pequeño.

GitHub+1

Una consideración técnica muy relevante: los checkpoints VLA-JEPA documentados en LeRobot utilizan dos vistas en la rama JEPA. Si se utilizan tres cámaras, el backbone multimodal puede recibirlas, pero el predictor JEPA requiere adaptar explícitamente su configuración para emplear las tres. No debes asumir que las tres contribuyen por igual a la pérdida predictiva.

Hugging Face

## 8. Cómo almacenaría las demostraciones

Usaría dos representaciones de almacenamiento, derivadas de una única sesión de adquisición.

| Nivel                    | Formato                             | Finalidad                                                                    |
| ------------------------ | ----------------------------------- | ---------------------------------------------------------------------------- |
| Captura original         | ROS 2 bag (`MCAP`)                  | Conservar mensajes, timestamps y feedback sin transformaciones irreversibles |
| Vídeo ZED original       | SVO/SVO2, si se habilita            | Reprocesar posteriormente la información estéreo                             |
| Dataset de entrenamiento | LeRobotDataset v3                   | Entrenar SmolVLA, VLA-JEPA y adaptadores                                     |
| Profundidad métrica      | Zarr, NPY o equivalente sin pérdida | Preservar `float32` y píxeles inválidos                                      |
| Calibraciones            | YAML/JSON                           | Intrínsecos, extrínsecos, TF, unidades                                       |
| Evaluación               | Parquet/CSV                         | Éxito, latencias, errores, seguridad, fallos                                 |

LeRobotDataset v3 ya separa vídeo multivista, tablas de estados/acciones en Parquet y metadatos de episodios. Es una buena base para no inventar un formato completamente nuevo.

Hugging Face

El registro mínimo de entrenamiento debe almacenar \(O_t\) y la acción demostrada \(a_t\), además de las posiciones realmente alcanzadas \(q_{t+\Delta t}\). Esta separación permite aprender por imitación y, simultáneamente, medir seguimiento de trayectoria.

Para JEPA y WAM, resulta especialmente útil guardar secuencias:

\[
(O_t,a_t,O_{t+1},a_{t+1},\ldots,O_{t+H})
\]

Así se pueden entrenar objetivos predictivos de evolución del entorno sin volver a capturar las demostraciones.

## 9. Experimentos recomendados para tu investigación

El diseño debería distinguir la comparación de políticas de la comparación de modalidades sensoriales.

| Experimento | Configuración                            | Qué determina                                 |
| ----------- | ---------------------------------------- | --------------------------------------------- |
| E1          | Algoritmo RGB-D + IK                     | Referencia geométrica                         |
| E2          | SmolVLA con RGB multivista               | Desempeño de VLA                              |
| E3          | VLA-JEPA sin pérdida predictiva          | Ablación de JEPA                              |
| E4          | VLA-JEPA con pérdida predictiva          | Aporte del modelado del futuro                |
| E5          | DreamZero adaptado a PiPER               | Generalización y eficiencia de WAM generativo |
| E6          | RGB de tres cámaras vs RGB + profundidad | Beneficio de la modalidad 3D                  |
| E7          | Posiciones conocidas vs nuevas           | Generalización espacial                       |

Si incorporas Dream-1, lo evaluaría inicialmente como modelo zero-shot mediante su API, separándolo de los métodos ajustados localmente. Dream-1 no es el mismo modelo ni el mismo sistema de despliegue que DreamZero.

Dream Labs

Como protocolo inicial, mantendría las pruebas de 25, 50 y 100 demostraciones y 30 ejecuciones por condición, separando escenarios conocidos, posiciones nuevas y cambios visuales. Para las métricas:

| Grupo          | Métrica                                                       |
| -------------- | ------------------------------------------------------------- |
| Tarea          | Éxito de pick-and-place, agarre exitoso, colocación exitosa   |
| Geometría      | Error de posición de agarre y colocación en mm                |
| Control        | Error articular, overshoot, suavidad, violaciones de límites  |
| Tiempo         | Duración, latencia de inferencia p50/p95, frecuencia efectiva |
| Eficiencia     | GPU/VRAM, datos de entrenamiento, tiempo de adaptación        |
| Generalización | Desempeño con objetos, iluminación y posiciones no vistos     |

Todos los métodos deben utilizar el mismo criterio de éxito, espacio físico, condiciones iniciales comparables y capa de seguridad. Registra por separado las acciones originales del modelo y las acciones modificadas por el controlador de seguridad; de lo contrario, podrías atribuir al modelo un comportamiento corregido externamente.

## 10. Primer paso práctico en ROS 2

El primer experimento no necesita ninguna red neuronal. Basta verificar que puedes obtener y sincronizar estas señales.

```
# Estado del brazo: adaptar namespace a cada PiPER
ros2 topic echo /left/feedback/joint_states --once
ros2 topic echo /right/feedback/joint_states --once

# Imagen ZED y profundidad
ros2 topic hz /zed/zed_node/rgb/color/rect/image
ros2 topic hz /zed/zed_node/depth/depth_registered

# Inspeccionar cámaras de muñeca
ros2 topic list -t | grep -E 'image|camera_info'

# Verificar estructura de transformaciones
ros2 run tf2_tools view_frames
```

Los nombres `/left` y `/right` son namespaces propuestos y deben coincidir con el lanzamiento efectivo de los drivers. Las rutas ZED mostradas corresponden a la nomenclatura habitual del wrapper y también pueden variar con el namespace.

StereoLabs+1

Posteriormente, verificaría que cada observación sincronizada corresponde al estado real de los brazos, realizaría la calibración cámara-base y ejecutaría un primer movimiento controlado con MoveIt 2, inicialmente en simulación y después en el robot bajo supervisión.

## Conclusión arquitectónica

La interfaz central de toda la tesis puede expresarse de forma sencilla:

\[
\boxed{
\pi_\theta(O_t,\text{instrucción})
\longrightarrow a_t
\longrightarrow \text{Adaptador PiPER}
}
\]

Donde \(\pi_\theta\) puede ser tanto una política neuronal como un algoritmo determinista.

No recomendaría unificar los modelos directamente en joints como única representación intermedia. Guardaría joints para feedback y ejecución, pero conservaría poses cartesianas para interoperabilidad entre robots, evaluación geométrica y adaptación de modelos como Dream-1.

La ventaja científica es que podrás distinguir tres contribuciones: cuánto aporta la percepción RGB-D, cuánto aporta la arquitectura de la política y cuánto aporta aprender a predecir la evolución del entorno. Esa separación te permitirá construir experimentos reproducibles de pick-and-place sin confundir rendimiento de percepción, inteligencia de la política y capacidades del controlador PiPER.
