#!/usr/bin/env python3
"""Rectificar y recortar al 80 % las cámaras OpenCV configuradas."""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import cv2
import numpy as np

from calibration.spatial import load_yaml


def rectification_maps(name, calibration):
    """Crear mapas de rectificación para el modelo y resolución calibrados."""
    size = tuple(int(value) for value in calibration['resolution'])
    if len(size) != 2 or min(size) <= 0:
        raise ValueError(f'{name}: resolución de calibración inválida')
    matrix = np.asarray(calibration['matrix'], dtype=np.float64)
    distortion = np.asarray(calibration['distortion'], dtype=np.float64).reshape(-1, 1)
    if matrix.shape != (3, 3) or not np.isfinite(matrix).all() or not np.isfinite(distortion).all():
        raise ValueError(f'{name}: parámetros de calibración inválidos')
    model = calibration['model']
    if model == 'pinhole':
        maps = cv2.initUndistortRectifyMap(matrix, distortion, None, matrix, size, cv2.CV_32FC1)
    elif model == 'fisheye':
        if distortion.size != 4:
            raise ValueError(f'{name}: el modelo fisheye requiere cuatro coeficientes')
        maps = cv2.fisheye.initUndistortRectifyMap(
            matrix, distortion, np.eye(3), matrix, size, cv2.CV_32FC1)
    else:
        raise ValueError(f'{name}: modelo de calibración desconocido: {model}')
    return size, maps


def crop_center(frame, fraction=0.8):
    """Conservar la fracción central del ancho y del alto, sin redimensionar."""
    height, width = frame.shape[:2]
    crop_width = max(1, int(width * fraction))
    crop_height = max(1, int(height * fraction))
    x = (width - crop_width) // 2
    y = (height - crop_height) // 2
    return frame[y:y + crop_height, x:x + crop_width]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT / 'configs/cameras.yaml')
    parser.add_argument('--calibration', type=Path, default=ROOT / 'outputs/calibration/spatial.yaml')
    parser.add_argument('--camera', action='append', help='Nombre de cámara; repetir para seleccionar varias')
    parser.add_argument('--output', type=Path, default=ROOT / 'outputs/fisheye_crops')
    args = parser.parse_args()
    cameras = load_yaml(args.config).get('cameras', {})
    names = args.camera or [name for name, config in cameras.items() if config.get('type') == 'opencv']
    if not names or any(name not in cameras or cameras[name].get('type') != 'opencv' for name in names):
        parser.error('Selecciona cámaras OpenCV existentes en la configuración')
    if len(set(names)) != len(names):
        parser.error('No se puede seleccionar la misma cámara dos veces')
    calibrations = load_yaml(args.calibration).get('cameras', {})
    missing = [name for name in names if name not in calibrations]
    if missing:
        parser.error(f'Falta la calibración de: {", ".join(missing)}')
    maps = {name: rectification_maps(name, calibrations[name]) for name in names}
    if any(line.strip().split() == ['GUI:', 'NONE'] for line in cv2.getBuildInformation().splitlines()):
        parser.error('OpenCV no tiene soporte gráfico; consulta docs/calibracion_camaras.md')

    captures = []
    try:
        for name in names:
            config = cameras[name]
            backend = getattr(cv2, 'CAP_' + str(config.get('backend', 'V4L2')).upper(), None)
            if backend is None:
                raise ValueError(f'{name}: backend OpenCV desconocido')
            camera = cv2.VideoCapture(config['index_or_path'], backend)
            captures.append((name, camera))
            if not camera.isOpened():
                raise RuntimeError(f'{name}: no se pudo abrir {config["index_or_path"]}')
            camera.set(cv2.CAP_PROP_FRAME_WIDTH, int(config['width']))
            camera.set(cv2.CAP_PROP_FRAME_HEIGHT, int(config['height']))
            camera.set(cv2.CAP_PROP_FPS, int(config.get('fps', 30)))
        print('S: guardar imágenes | Q o Esc: salir')
        while True:
            frames = {}
            for name, camera in captures:
                ok, frame = camera.read()
                if not ok or frame is None:
                    raise RuntimeError(f'{name}: no se pudo leer la cámara')
                size, (map_x, map_y) = maps[name]
                if (frame.shape[1], frame.shape[0]) != size:
                    raise RuntimeError(f'{name}: resolución capturada {frame.shape[1]}x{frame.shape[0]} '
                                       f'distinta de la calibración {size[0]}x{size[1]}')
                rectified = cv2.remap(frame, map_x, map_y, cv2.INTER_LINEAR)
                frames[name] = crop_center(rectified)
                cv2.imshow(f'Recorte: {name}', frames[name])
            key = cv2.waitKey(1) & 0xff
            if key in (ord('q'), 27):
                break
            if key == ord('s'):
                args.output.mkdir(parents=True, exist_ok=True)
                stamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
                for name, frame in frames.items():
                    path = args.output / f'{name}_{stamp}.png'
                    if not cv2.imwrite(str(path), frame):
                        raise RuntimeError(f'No se pudo guardar {path}')
                    print(f'Guardado: {path}')
    finally:
        for _, camera in captures:
            camera.release()
        cv2.destroyAllWindows()


if __name__ == '__main__':
    main()
