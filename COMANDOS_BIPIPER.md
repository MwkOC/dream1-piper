# Comandos del montaje BiPiper

Ejecutar desde la raíz. El flujo usa el URDF bimanual personalizado y el solver
local, sin abrir el editor TCP de Dream Labs. La rectificación está desactivada
por defecto. No publicar `.env`: contiene credenciales.

## 1. Directorio y dependencias existentes

```bash
cd /home/nonhuman/NONHUMAN/dream1-piper
experiments/.venv/bin/python -c 'import dream, piper_sdk, cv2, numpy, scipy, yaml; print("Dependencias OK")'
experiments/.venv/bin/dream-piper-models --help
```

## 2. Estado y asignación CAN

Encender ambos brazos y conectar sus adaptadores. Comprobar físicamente el
estado del paro de emergencia antes de habilitar control.
La configuración actual es izquierdo físico `can0`, derecho físico `can1`.
Los nombres CAN pueden cambiar después de reconectar USB: verificar antes de mover.

```bash
ip -details -statistics link show can0
ip -details -statistics link show can1
readlink -f /sys/class/net/can0/device
readlink -f /sys/class/net/can1/device
```

Se espera `UP`, bitrate `1000000` y ausencia de `BUS-OFF`.
Si una interfaz está DOWN, activarla individualmente:

```bash
sudo ip link set can0 type can bitrate 1000000
sudo ip link set can0 up
sudo ip link set can1 type can bitrate 1000000
sudo ip link set can1 up
```

No bajar una interfaz usada por un controlador. Si ya está UP a 1 Mbps, omitir
estos comandos de activación.

## 3. Telemetría real, sin comandos de movimiento

```bash
PYTHONPATH=experiments experiments/.venv/bin/python - <<'PY'
from pathlib import Path
from piper.active_config import PiperConfig
from piper.active_driver import PiperFeedbackArm
from piper.gripper_calibration import load_piper_gripper_calibrations

config = PiperConfig.from_file(Path('configs/bipiper.yaml'))
calibration = load_piper_gripper_calibrations(config.calibration_path)
for side, port in [('left', config.left_port), ('right', config.right_port)]:
    arm = PiperFeedbackArm(port, calibration[side])
    try:
        arm.wait_ready(timeout_s=3)
        joints, opening = arm.read()
        print(side, port, 'joints_rad=', joints.tolist(), 'opening=', opening)
    finally:
        arm.disconnect()
PY
```

Si falla por ausencia de feedback, detener la secuencia: una interfaz UP no
demuestra que el brazo esté transmitiendo. Revisar alimentación, cable CAN,
adaptador, bitrate y estado del controlador. No sustituir feedback por ceros.

## 4. Verificar configuración y cámaras

```bash
PYTHONPATH=experiments experiments/.venv/bin/python - <<'PY'
from pathlib import Path
from piper.active_config import PiperConfig
from piper.gripper_calibration import load_piper_gripper_calibrations
c = PiperConfig.from_file(Path('configs/bipiper.yaml'))
print('URDF:', c.urdf)
print('Frames:', c.frames)
print('CAN:', c.left_port, c.right_port)
print('Pose inicial opcional:', c.inference_start)
print('Calibración:', c.calibration_path)
for side, grip in load_piper_gripper_calibrations(c.calibration_path).items():
    print(side, grip)
for name, camera in c.cameras.items():
    print(name, camera)
PY
v4l2-ctl --list-devices
```

Conservar los valores propios de cada pinza. No intercambiar calibraciones
solo porque haya cambiado un nombre de interfaz CAN.

## 5. Pruebas de software

Este entorno ya tiene pytest en `.venv` de la raíz:

```bash
PYTHONPATH=experiments .venv/bin/python -m pytest experiments/tests/test_custom_policy.py experiments/tests/test_active_driver.py experiments/tests/test_dream_probe.py experiments/tests/test_active_kinematics.py experiments/tests/test_active_config.py
```

## 6. Dream e IK sin mover motores

El programa lee `.env` desde el directorio actual; no hace falta mostrar ni
exportar la clave. No usa `DREAM_ARM_FILE` ni requiere el wizard TCP.

```bash
experiments/.venv/bin/dream-piper-models --models
experiments/.venv/bin/dream-piper-models --infer --prompt 'Use the left arm to pick up the black wallet from the table. Keep the right arm stationary.'
```

Se espera `solver: custom_bimanual_piper` e informe `ik_report` de ambos brazos.
Si el solver rechaza límites o alcanzabilidad, no ejecutar el siguiente paso.
Pasar IK no comprueba colisiones con la mesa ni entre brazos.

## 7. Ejecución física limitada

Solo después de revisar vistas, asociación de cada brazo y resultado de IK,
con la persona presente y el paro de emergencia disponible. Este comando mueve
hardware y puede accionar ambas pinzas. El prompt no es una garantía de que el
modelo mantenga un brazo quieto. Exige Enter antes de iniciar.

```bash
experiments/.venv/bin/dream-piper-models --infer --execute --max-duration-s 15 --log experiments/data/wallet-run.jsonl --prompt 'Use the left arm to pick up the black wallet from the table. Keep the right arm stationary.'
```

Ctrl-C termina el loop; ante peligro usar el paro de emergencia físico.
El límite de tiempo detiene el streaming, no desconecta la energía de motores
ni verifica que el objeto se haya recogido. La calibración óptica y una
validación física de agarre siguen pendientes.
