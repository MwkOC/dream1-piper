# Métricas de pose TCP y viabilidad de rosbag/MCAP

## Qué mide la implementación

Para cada acción Dream el worker calcula, con la FK del URDF Piper validado,
la pose TCP esperada a partir de las seis articulaciones objetivo de cada brazo.
Envía posición, cuaternión y frame como metadatos de la acción. El bridge ROS
conserva el objetivo más reciente y lo compara con `/{left,right}/feedback/tcp_pose`
cuando llega feedback físico fresco.

La distancia euclídea entre posiciones se presenta en milímetros. El error de
orientación es el ángulo mínimo entre cuaterniones, en grados. Cada muestra
incluye brazo, secuencia e invocación Dream, frame, timestamp ROS del feedback y
edad local del objetivo. La frecuencia y edad máxima se configuran con
`RSTACK_POSE_METRICS_HZ` (2 Hz por brazo por defecto) y
`RSTACK_POSE_METRICS_MAX_TARGET_AGE_MS` (250 ms por defecto).

Las muestras se publican en `/dream1/metrics/tcp_tracking`, se agregan a los
eventos en vivo y se guardan como `stage_metrics` en PostgreSQL. La UI muestra
último error, p95 y número de muestras por brazo. Objetivos vencidos no producen
métrica. Si `frame_id` no coincide, la muestra se marca `unavailable` y se
conserva el motivo; no se calcula una distancia entre marcos distintos. El
driver AgileX fijado deja vacío `header.frame_id`; el bridge interpreta esa
pose como el frame base del namespace (`left_base_link` o `right_base_link`),
que es el frame local en el que el driver reporta el TCP. El launch entrega al
driver el `robot.options.tcp_offset` del mismo `configs/app_robot.yaml` que
define la herramienta en el perfil de la aplicación; así la pose física
reportada y la FK teórica incluyen el mismo desplazamiento TCP.

Antes de interpretar resultados como precisión física, confirmar en el robot
real que el feedback del driver está efectivamente expresado relativo a
`left_base_link`/`right_base_link` y que TCP/URDF tienen la misma calibración y herramienta. La pose teórica usa
el TCP configurado para Dream; una diferencia de offsets aparecerá como error
sistemático y no debe “corregirse” automáticamente en esta métrica.

## Rosbag2 y MCAP

La integración es viable. El tópico `/dream1/metrics/tcp_tracking` lleva cada
medición con sus poses fuente y correlación. Al conservar además feedback y
comandos ROS se puede auditar la métrica, investigar diferencias de frame y
recalcular series sin hacer que la escritura a disco participe en el ciclo de
control.

Topics recomendados para una captura de diagnóstico:

- `/dream1/metrics/tcp_tracking`
- `/left/feedback/tcp_pose`, `/right/feedback/tcp_pose`
- `/left/feedback/joint_states`, `/right/feedback/joint_states`
- `/left/control/joint_states`, `/right/control/joint_states`
- `/tf`, `/tf_static`

En el host Jazzy usado para validar este patch, `rosbag2_storage_mcap` está
instalado. En otra máquina, comprobarlo antes de usar `ros2 bag record -s mcap`.
Una captura de diagnóstico inicial se puede hacer así:

```bash
ros2 bag record -s mcap -o outputs/rosbags/diagnostic \
  /dream1/metrics/tcp_tracking \
  /left/feedback/tcp_pose /right/feedback/tcp_pose \
  /left/feedback/joint_states /right/feedback/joint_states \
  /left/control/joint_states /right/control/joint_states /tf /tf_static
```

No se recomienda grabar permanentemente
las tres cámaras en este primer patch: el volumen y la escritura sostenida
pueden afectar disco/CPU y requieren política de retención. La primera
integración debería ser opt-in por operación, con directorio por `operation_id`,
almacenamiento separado de PostgreSQL, límite de espacio/retención y un evento
que registre la ruta del bag y el resultado de cierre. Para análisis visual se
puede añadir después una selección explícita de cámaras comprimidas.

## Recomendación del patch

Aplicar en una etapa posterior un recorder opcional administrado por ROS 2, que
grabe los tópicos de diagnóstico anteriores a petición del operador y vincule
el archivo a `operation_id`. Antes de habilitarlo en operación real, verificar
el plugin MCAP, permisos/espacio de almacenamiento, cierre limpio ante SIGINT y
que la grabación no causa pérdida de feedback. Mantener las métricas PostgreSQL
como consulta inmediata; usar bags para auditoría y análisis fuera de línea.
