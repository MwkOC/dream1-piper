# Revisión de conversión Piper ↔ Dream

## Estado de esta revisión

La implementación actual deja una frontera clara:

- El SDK Piper expone las articulaciones en miligrados y el driver las convierte a radianes con `pi / 180000`.
- Los comandos vuelven de radianes a miligrados en un único punto del driver CAN.
- La cinemática y el solver trabajan en radianes y metros.
- La apertura de pinza se normaliza con `closed_microm` y `open_microm` medidos por brazo.

## Pendiente antes de fijar la conversión final

No se deben codificar todavía offsets o factores por articulación como constantes del modelo. Faltan mediciones físicas para confirmar, por cada brazo:

1. Cero mecánico frente al cero del feedback CAN.
2. Sentido de cada articulación respecto al URDF.
3. TCP real desde el flange hasta el punto entre los dedos.
4. Transformación entre las bases izquierda y derecha y la separación del montaje.
5. Rangos de pinza cerrada y abierta.

El `tcp` de `experiments/piper/arms/piper.json` y los valores de `approach`/`jaw` son artefactos de instalación y deben conservarse como configuración revisable, no como sustituto de una calibración física independiente.

## Patch recomendado

La siguiente revisión debe introducir una calibración explícita por brazo, con `scale`, `offset_rad`, `lower_rad` y `upper_rad`, y aplicar la misma transformación en lectura, escritura e IK. La prueba mínima debe comprobar la ida y vuelta:

```text
raw_mdeg -> q_rad -> raw_mdeg
q_rad -> raw_mdeg -> q_rad
```

También debe validar una pose física conocida por lado y rechazar diferencias de signo, escala o offset fuera de tolerancia. Hasta que esas mediciones existan, el driver actual es una base de integración y no una conversión final certificada.

