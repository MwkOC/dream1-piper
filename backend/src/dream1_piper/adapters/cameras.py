import threading
import time


class CameraInput:
    def __init__(self, configs):
        self.configs = configs
        self.devices = {item["name"]: item["device"] for item in configs}
        self.frames = {}
        self.errors = {}
        self.captures = {}
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.threads = []

    def start(self):
        import cv2

        for config in self.configs:
            name = config["name"]
            capture = cv2.VideoCapture(config["device"], cv2.CAP_V4L2)
            capture.set(cv2.CAP_PROP_FRAME_WIDTH, config["source_width"])
            capture.set(cv2.CAP_PROP_FRAME_HEIGHT, config["source_height"])
            capture.set(cv2.CAP_PROP_FPS, config["fps"])
            capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            self.captures[name] = capture
            thread = threading.Thread(target=self._read_loop, args=(config, capture), daemon=True)
            thread.start()
            self.threads.append(thread)

    def _read_loop(self, config, capture):
        import cv2

        name = config["name"]
        while not self.stop_event.is_set():
            ok, frame = capture.read()
            if not ok:
                with self.lock:
                    self.errors[name] = "camera frame read failed"
                self.stop_event.wait(0.03)
                continue
            frame = self._prepare_frame(frame, config, cv2)
            ok, encoded = cv2.imencode(
                ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, config.get("jpeg_quality", 85)]
            )
            if ok:
                with self.lock:
                    self.frames[name] = (time.monotonic_ns(), encoded.tobytes())
                    self.errors.pop(name, None)

    @staticmethod
    def _prepare_frame(frame, config, cv2):
        if config.get("crop", "").startswith("left_half"):
            frame = frame[:, : frame.shape[1] // 2]
        height, width = frame.shape[:2]
        if width / height > 16 / 9:
            width = round(height * 16 / 9)
            offset = (frame.shape[1] - width) // 2
            frame = frame[:, offset : offset + width]
        else:
            height = round(width / (16 / 9))
            offset = (frame.shape[0] - height) // 2
            frame = frame[offset : offset + height, :]
        return cv2.resize(frame, (config["width"], config["height"]), interpolation=cv2.INTER_AREA)

    def health(self):
        now = time.monotonic_ns()
        with self.lock:
            return {
                config["name"]: {
                    "connected": name in self.frames,
                    "age_ms": (now - self.frames[name][0]) / 1e6 if name in self.frames else None,
                    "error": self.errors.get(name),
                }
                for config in self.configs
                for name in [config["name"]]
            }

    def coherent_frames(self, max_age_ms, max_skew_ms, wait_ms=0):
        deadline = time.monotonic() + max(0.0, wait_ms / 1000)
        snapshot = dict(self.frames_by_name())
        ages, skew = self._frame_timing(snapshot)
        while time.monotonic() < deadline and self._frames_out_of_sync(
            snapshot, ages, skew, max_age_ms, max_skew_ms
        ):
            time.sleep(min(0.01, max(0.0, deadline - time.monotonic())))
            snapshot = dict(self.frames_by_name())
            ages, skew = self._frame_timing(snapshot)
        if set(snapshot) != set(self.devices):
            raise RuntimeError("not all configured cameras have frames")
        if max(ages.values()) > max_age_ms:
            raise RuntimeError(f"camera frame is stale: {ages}")
        if skew > max_skew_ms:
            raise RuntimeError(
                f"camera frames exceed allowed skew: {skew:.1f} ms > {max_skew_ms:.1f} ms"
            )
        return {name: image for name, (_, image) in snapshot.items()}

    def _frame_timing(self, snapshot):
        if set(snapshot) != set(self.devices):
            return {}, float("inf")
        now = time.monotonic_ns()
        ages = {name: (now - stamp) / 1e6 for name, (stamp, _) in snapshot.items()}
        stamps = [stamp for stamp, _ in snapshot.values()]
        skew = (max(stamps) - min(stamps)) / 1e6
        return ages, skew

    @staticmethod
    def _frames_out_of_sync(snapshot, ages, skew, max_age_ms, max_skew_ms):
        return (
            len(ages) != len(snapshot)
            or max(ages.values(), default=float("inf")) > max_age_ms
            or skew > max_skew_ms
        )

    def frames_by_name(self):
        with self.lock:
            return {name: value for name, value in self.frames.items()}

    def frame(self, name):
        with self.lock:
            if name not in self.frames:
                raise RuntimeError(f"camera {name} has no frame")
            return self.frames[name][1]

    def close(self):
        self.stop_event.set()
        for thread in self.threads:
            thread.join(timeout=1)
        for capture in self.captures.values():
            capture.release()
