# Estado del driver activo Piper

La integración experimental de `experiments/piper` consolida la lógica de
`origin/temasA` para conexiones CAN, habilitación, streaming, límites de
velocidad/aceleración, home, reset de pinzas y control bimanual.

## Implementado

- Feedback inicial antes de seleccionar el modo de movimiento o habilitar.
- Reset condicional del estado del brazo y timeout de habilitación.
- Cierre automático ante errores de conexión.
- Streamer de objetivos con límites de velocidad y aceleración.
- Conversión de unidades Piper en un único límite de hardware.
- Diagnósticos de motores, drivers, colisiones y estado del brazo.
- FK/IK sobre el URDF dual y validación de límites físicos.
- Ejecución Dream opcional mediante `dream-piper-models --execute`.

## Pendiente de validación física

- Calibración medida de ambas pinzas y confirmación de ceros/signos.
- Verificación de CAN, cámaras, TCP físico y separación de bases.
- Pruebas supervisadas de arranque, home, pérdida de feedback, parada y
  desconexión.
- Confirmación de checkpoint y embodiment remoto de Dream.

Las pruebas automatizadas usan mocks y no habilitan motores. La ejecución real
requiere el SDK Piper, calibración local y supervisión humana.
