"""Dream camera source: the same ZED Mini UVC left-eye crop XHUMAN uses."""

import os

import cv2


class ZedLeft:
    """Input mode 1344x376 stereo; output one 672x376 BGR eye.

    Config width is the output width. Do not apply to an already monocular stream.
    """

    def __init__(self, cfg) -> None:
        self._width, self._height = cfg.width, cfg.height
        self._capture = cv2.VideoCapture(os.environ.get("PIPER_ZED_DEVICE", "/dev/video2"), cv2.CAP_V4L2)
        try:
            if not self._capture.isOpened():
                raise RuntimeError("Cannot open ZED Mini UVC device")
            self._capture.set(cv2.CAP_PROP_FRAME_WIDTH, 2 * cfg.width)
            self._capture.set(cv2.CAP_PROP_FRAME_HEIGHT, cfg.height)
            self._capture.set(cv2.CAP_PROP_FPS, cfg.fps)
        except BaseException:
            self.release()
            raise

    def read(self):
        ok, frame = self._capture.read()
        if not ok:
            return False, None
        expected = (self._height, self._width * 2, 3)
        if frame is None or frame.shape != expected:
            raise RuntimeError(f"Expected stereo frame {expected}; got {None if frame is None else frame.shape}")
        return True, frame[:, :self._width].copy()

    def release(self) -> None:
        self._capture.release()
