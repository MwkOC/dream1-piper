"""ZED Mini SDK capture of the rectified left image."""
from __future__ import annotations

import os
from pathlib import Path

import cv2
import numpy as np


class ZedMiniCameraDevice:
    """Capture BGR images and matching intrinsics from the ZED SDK."""

    def __init__(self, *, fps: int = 30, serial_number: int | None = None):
        self.fps = int(fps)
        self.serial_number = serial_number
        self.camera = None
        self.sl = None
        self.image = None
        self.intrinsics = None

    def connect(self) -> None:
        if self.camera is not None:
            raise RuntimeError('ZED Mini is already connected')
        try:
            import pyzed.sl as sl
        except ImportError as exc:
            raise RuntimeError('ZED SDK o pyzed no disponible; consulta docs/calibracion_camaras.md') from exc
        camera = sl.Camera()
        params = sl.InitParameters()
        params.camera_resolution = sl.RESOLUTION.VGA
        params.camera_fps = self.fps
        params.depth_mode = sl.DEPTH_MODE.NONE
        if os.environ.get('ZED_SDK_ROOT_DIR'):
            settings = Path.home() / '.cache' / 'zed' / 'settings'
            settings.mkdir(parents=True, exist_ok=True)
            params.optional_settings_path = str(settings) + os.sep
        if self.serial_number is not None:
            params.set_from_serial_number(int(self.serial_number))
        status = camera.open(params)
        if status != sl.ERROR_CODE.SUCCESS:
            camera.close()
            if status == getattr(sl.ERROR_CODE, 'CALIBRATION_FILE_NOT_AVAILABLE', None):
                settings_path = getattr(params, 'optional_settings_path', '') or '/usr/local/zed/settings/'
                serial = str(self.serial_number) if self.serial_number is not None else '<serial mostrado en el log del SDK>'
                raise RuntimeError(
                    'ZED Mini: archivo de calibración de fábrica no disponible '
                    f'(CALIBRATION FILE NOT AVAILABLE). Carpeta de búsqueda: {settings_path}. '
                    'Comprueba que exista y tengas permiso de escritura. '
                    f'Descarga la calibración de tu cámara en https://calib.stereolabs.com '
                    f'o ejecuta ZED Explorer con --dc {serial}. '
                    'Si usas el SDK local del proyecto, define ZED_SDK_ROOT_DIR '
                    'para usar ~/.cache/zed/settings/. '
                    'Esta calibración de fábrica es distinta de la calibración ChArUco; '
                    'consulta docs/calibracion_camaras.md.'
                )
            raise RuntimeError(f'No se pudo abrir la ZED Mini mediante el SDK: {status}')
        try:
            info = camera.get_camera_information()
            config = info.camera_configuration
            left = config.calibration_parameters.left_cam
            size = config.resolution
            if (size.width, size.height) != (672, 376):
                raise RuntimeError(f'Resolución VGA inesperada: {size.width}x{size.height}')
            self.intrinsics = {
                'resolution': [int(size.width), int(size.height)],
                'model': 'pinhole',
                'matrix': [[float(left.fx), 0.0, float(left.cx)],
                           [0.0, float(left.fy), float(left.cy)],
                           [0.0, 0.0, 1.0]],
                'distortion': np.asarray(left.disto, dtype=float).reshape(-1).tolist(),
                'source': 'zed_sdk_rectified_left',
                'serial_number': int(info.serial_number),
                'views': 0,
                'rms_px': None,
                'mean_error_px': None,
            }
            self.image = sl.Mat()
        except Exception:
            camera.close()
            raise
        self.sl, self.camera = sl, camera

    @property
    def output_width(self) -> int:
        return 672

    def read(self) -> np.ndarray:
        if self.camera is None:
            raise RuntimeError('ZED Mini is not connected')
        status = self.camera.grab()
        if status != self.sl.ERROR_CODE.SUCCESS:
            raise RuntimeError(f'ZED grab failed: {status}')
        status = self.camera.retrieve_image(self.image, self.sl.VIEW.LEFT)
        if status != self.sl.ERROR_CODE.SUCCESS:
            raise RuntimeError(f'ZED retrieve_image failed: {status}')
        frame = self.image.get_data()
        if frame is None or frame.shape != (376, 672, 4):
            raise RuntimeError(f'Unexpected ZED image shape: {getattr(frame, "shape", None)}')
        return cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)

    def disconnect(self) -> None:
        if self.camera is not None:
            self.camera.close()
            self.camera = None
        self.image = None
