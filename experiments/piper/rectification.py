"""Measured camera calibration; rectification precedes the model resize."""
from functools import lru_cache
from pathlib import Path

import numpy as np
import yaml


@lru_cache(maxsize=8)
def _maps(path, width, height):
    import cv2
    data = yaml.safe_load(Path(path).read_text())
    if data["resolution"] != [width, height]:
        raise ValueError("Camera calibration resolution does not match the selected eye")
    k = np.asarray(data["camera_matrix"], dtype=float).reshape(3, 3)
    d = np.asarray(data["distortion_coefficients"], dtype=float)
    if not np.isfinite(k).all() or not np.isfinite(d).all() or min(k[0, 0], k[1, 1]) <= 0:
        raise ValueError("Invalid camera intrinsics")
    size = (width, height)
    model = data["model"]
    if model == "fisheye":
        new = cv2.fisheye.estimateNewCameraMatrixForUndistortRectify(k, d, size, np.eye(3), balance=0)
        maps = cv2.fisheye.initUndistortRectifyMap(k, d, np.eye(3), new, size, cv2.CV_32FC1)
    elif model == "pinhole":
        new, _ = cv2.getOptimalNewCameraMatrix(k, d, size, 0, size)
        maps = cv2.initUndistortRectifyMap(k, d, None, new, size, cv2.CV_32FC1)
    else:
        raise ValueError(f"Unsupported camera model: {model}")
    return maps


def rectify(image, spec):
    import cv2
    opts = spec.get("rectification", {})
    if not opts.get("enabled", False):
        return image
    if opts.get("already_rectified", False):
        result = image
    else:
        path = opts.get("calibration_file")
        if not path:
            raise ValueError(f"Missing measured camera calibration: {spec['index_or_path']}")
        result = cv2.remap(image, *_maps(str(Path(path).expanduser().resolve()), image.shape[1], image.shape[0]), cv2.INTER_LINEAR)
    fraction = float(opts.get("retain_fraction", 0.8))
    if not 0 < fraction <= 1:
        raise ValueError("retain_fraction must be in (0, 1]")
    h, w = result.shape[:2]
    ch, cw = max(1, round(h*fraction)), max(1, round(w*fraction))
    y, x = (h-ch)//2, (w-cw)//2
    return result[y:y+ch, x:x+cw]


def letterbox(image, width=320, height=176):
    import cv2
    h, w = image.shape[:2]
    scale = min(width/w, height/h)
    rw, rh = max(1, round(w*scale)), max(1, round(h*scale))
    output = np.zeros((height, width, 3), dtype=image.dtype)
    x, y = (width-rw)//2, (height-rh)//2
    output[y:y+rh, x:x+rw] = cv2.resize(image, (rw, rh), interpolation=cv2.INTER_AREA)
    return output
