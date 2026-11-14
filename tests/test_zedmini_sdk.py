"""Contract checks for the rectified ZED SDK integration without hardware."""
import sys
import types
import os
from unittest.mock import patch

import numpy as np

from hardware.zedmini.zedmini import ZedMiniCameraDevice
from calibration.spatial import CameraIntrinsics


def test_rectified_left_and_matching_intrinsics(tmp_path):
    sdk = types.ModuleType('pyzed.sl')
    sdk.ERROR_CODE = types.SimpleNamespace(SUCCESS=0)
    sdk.RESOLUTION = types.SimpleNamespace(VGA='vga')
    sdk.DEPTH_MODE = types.SimpleNamespace(NONE='none')
    sdk.VIEW = types.SimpleNamespace(LEFT='rectified-left')
    sdk.InitParameters = types.SimpleNamespace
    frame = np.zeros((376, 672, 4), dtype=np.uint8)
    frame[0, 0] = [10, 20, 30, 255]
    sdk.Mat = lambda: types.SimpleNamespace(get_data=lambda: frame)
    left = types.SimpleNamespace(fx=500, fy=501, cx=336, cy=188, disto=np.zeros(5))
    cfg = types.SimpleNamespace(resolution=types.SimpleNamespace(width=672, height=376),
                                calibration_parameters=types.SimpleNamespace(left_cam=left))
    class FakeCamera:
        def open(self, params):
            assert params.camera_resolution == 'vga'
            assert params.optional_settings_path == str(tmp_path / '.cache' / 'zed' / 'settings') + os.sep
            return 0
        def get_camera_information(self):
            return types.SimpleNamespace(camera_configuration=cfg, serial_number=123)
        def grab(self):
            return 0
        def retrieve_image(self, image, view):
            assert view == 'rectified-left'
            return 0
        def close(self):
            self.closed = True
    sdk.Camera = FakeCamera
    with (patch.dict(sys.modules, {'pyzed': types.ModuleType('pyzed'), 'pyzed.sl': sdk}),
          patch.dict(os.environ, {'ZED_SDK_ROOT_DIR': str(tmp_path)}),
          patch('pathlib.Path.home', return_value=tmp_path)):
        camera = ZedMiniCameraDevice()
        camera.connect()
        assert camera.read()[0, 0].tolist() == [10, 20, 30]
        entry = {'camera': 'top', **camera.intrinsics}
        calibration = CameraIntrinsics.from_dict(entry)
        assert calibration.width == 672 and calibration.matrix[0, 0] == 500
        assert calibration.rms_px is None and calibration.distortion.max() == 0
        handle = camera.camera
        camera.disconnect()
        assert handle.closed
