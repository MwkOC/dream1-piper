"""One-shot, read-only Dream Labs API probe for the bimanual Piper.

Usage: python tests/test_dream_api.py --models | --infer --prompt "..."
"""

import argparse
import base64
import json
from pathlib import Path
import sys
import time
import xml.etree.ElementTree as ET
from contextlib import ExitStack

import numpy as np
from scipy.spatial.transform import Rotation
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.driver import PiperFeedbackArm
from scripts.gripper_calibration import load_piper_gripper_calibrations
from scripts.piper import BiPiperConfig


def _tr(xyz, rpy):
    result = np.eye(4)
    result[:3, :3] = Rotation.from_euler("xyz", rpy).as_matrix()
    result[:3, 3] = xyz
    return result


class PiperKinematics:
    def __init__(self, urdf: Path, base: str, tcp_link: str):
        root = ET.parse(urdf).getroot()
        by_child = {joint.find("child").get("link"): joint for joint in root.findall("joint")}
        chain = []
        link = tcp_link
        while link != base:
            if link not in by_child:
                raise ValueError(f"No URDF chain from {base} to {tcp_link}")
            joint = by_child[link]
            chain.append(joint)
            link = joint.find("parent").get("link")
            if len(chain) > 100:
                raise ValueError("URDF chain contains a cycle")
        self.chain = list(reversed(chain))
        moving = [j for j in self.chain if j.get("type") != "fixed"]
        if len(moving) != 6 or any(j.get("type") != "revolute" for j in moving):
            raise ValueError("Piper chain must contain exactly six revolute joints")
        self.joint_names = [j.get("name") for j in moving]
        self.lower = np.array([float(j.find("limit").get("lower")) for j in moving])
        self.upper = np.array([float(j.find("limit").get("upper")) for j in moving])
        if np.any(self.lower >= self.upper):
            raise ValueError("Invalid URDF joint limits")

    def _chain(self, q):
        t = np.eye(4)
        index = 0
        for joint in self.chain:
            origin = joint.find("origin")
            xyz = np.fromstring(origin.get("xyz", "0 0 0"), sep=" ") if origin is not None else np.zeros(3)
            rpy = np.fromstring(origin.get("rpy", "0 0 0"), sep=" ") if origin is not None else np.zeros(3)
            t = t @ _tr(xyz, rpy)
            if joint.get("type") == "fixed":
                continue
            axis_node = joint.find("axis")
            axis = np.fromstring(axis_node.get("xyz", "1 0 0"), sep=" ") if axis_node is not None else np.array([1., 0., 0.])
            t[:3, :3] = t[:3, :3] @ Rotation.from_rotvec(axis * float(q[index])).as_matrix()
            index += 1
        return t

    def forward_matrix(self, joints):
        return self._chain(joints)


def settings():
    values = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            key, sep, value = line.partition("=")
            if not sep:
                raise ValueError(f"Invalid .env line: {key}")
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def key_from_config(config):
    key = config.get("DREAM_API_KEY", "").strip()
    if not key or any(c.isspace() for c in key):
        raise ValueError("Set DREAM_API_KEY in .env")
    return key


def open_camera(spec):
    import cv2

    backend = cv2.CAP_V4L2 if spec.get("backend") == "V4L2" else cv2.CAP_ANY
    capture = cv2.VideoCapture(str(spec["index_or_path"]), backend)
    if not capture.isOpened():
        raise RuntimeError(f"Cannot open camera: {spec['index_or_path']}")
    capture.set(cv2.CAP_PROP_FRAME_WIDTH, int(spec["width"]))
    capture.set(cv2.CAP_PROP_FRAME_HEIGHT, int(spec["height"]))
    capture.set(cv2.CAP_PROP_FPS, int(spec["fps"]))
    return capture


def frame_b64(capture, spec):
    import cv2

    ok, image = capture.read()
    if not ok or image is None:
        raise RuntimeError(f"No frame from {spec['index_or_path']}")
    if spec["type"] == "zedmini":
        if image.shape[1] != int(spec["width"]):
            raise RuntimeError(f"Unexpected ZED stereo width: {image.shape[1]}")
        image = image[:, :image.shape[1] // 2]
    image = cv2.resize(image, (320, 176), interpolation=cv2.INTER_AREA)
    ok, jpeg = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ok:
        raise RuntimeError("JPEG encoding failed")
    return base64.b64encode(jpeg.tobytes()).decode("ascii")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--models", action="store_true", help="Check key and list accessible checkpoints")
    choice.add_argument("--infer", action="store_true", help="Capture one observation and request one action chunk; no motor commands")
    parser.add_argument("--prompt", help="Instruction for the inference observation")
    args = parser.parse_args()
    if args.infer and (not args.prompt or not args.prompt.strip()):
        parser.error("--infer requires a non-empty --prompt")
    if args.models and args.prompt is not None:
        parser.error("--prompt is only valid with --infer")
    config = settings()
    key = key_from_config(config)
    import dream

    with dream.DreamClient(api_key=key) as client:
        if args.models:
            models = client.get_models()
            print(json.dumps([{"id": model.id, "servable": getattr(model, "servable", None)} for model in models], indent=2))
            return

        bipiper = yaml.safe_load((ROOT / "configs/bipiper.yaml").read_text(encoding="utf-8"))
        robot_cfg = bipiper["robot"]
        cameras = yaml.safe_load((ROOT / "configs/cameras.yaml").read_text(encoding="utf-8"))["cameras"]
        if robot_cfg["type"] != "bi_piper" or set(cameras) != {"left", "right", "top"}:
            raise ValueError("Expected bi_piper and left/top/right cameras")
        control = BiPiperConfig(
            id=robot_cfg["id"],
            left_port=robot_cfg["left_port"],
            right_port=robot_cfg["right_port"],
            command_rate_hz=float(robot_cfg["command_rate_hz"]),
        )
        calibration = Path(robot_cfg["gripper_calibration_path"]).expanduser()
        ranges = load_piper_gripper_calibrations(calibration)
        if set(ranges) != {"left", "right"}:
            raise ValueError(f"Both Piper grippers need calibration in {calibration}")
        urdf = Path(config["PIPER_URDF"]).expanduser()
        if not urdf.is_absolute():
            urdf = ROOT / urdf
        kin, readers, captures = {}, {}, {}
        with ExitStack() as stack:
            for side in ("left", "right"):
                kin[side] = PiperKinematics(urdf, config[f"PIPER_{side.upper()}_BASE"], config[f"PIPER_{side.upper()}_TCP"])
                readers[side] = PiperFeedbackArm(getattr(control, f"{side}_port"), ranges[side])
                stack.callback(readers[side].disconnect)
            for name, spec in cameras.items():
                captures[name] = open_camera(spec)
                stack.callback(captures[name].release)

            time.sleep(0.2)
            state = {side: readers[side].read() for side in ("left", "right")}
            frames = {f"video.{role}": frame_b64(captures[name], cameras[name]) for name, role in (("left", "wrist_l"), ("top", "overhead"), ("right", "wrist_r"))}
            observation = {"prompt": args.prompt}
            for side in ("left", "right"):
                q, grip = state[side]
                pose = kin[side].forward_matrix(q)
                observation[f"state.{side}_arm"] = [0.0] * 6  # base model with other_embodiment ignores foreign joints
                observation[f"state.{side}_gripper"] = [grip]
                observation[f"state.{side}_grip"] = [grip]
                observation[f"state.{side}_eef_xyz"] = pose[:3, 3].tolist()
                observation[f"state.{side}_eef_rot6"] = pose[:3, :2].T.reshape(-1).tolist()

            client.policy({"checkpoint": config["DREAM_CHECKPOINT"], "robot": "other_embodiment", "strict": False})
            client.set_observation(frames, observation)
            action = client.get_action()
            per_key = action["per_key"]
            report = {"checkpoint": config["DREAM_CHECKPOINT"], "action_keys": sorted(per_key), "timing": client.last_timing}
            for side in ("left", "right"):
                xyz = np.asarray(per_key[f"action.{side}_eef_xyz"], dtype=float)
                rot6 = np.asarray(per_key[f"action.{side}_eef_rot6"], dtype=float)
                if xyz.ndim != 2 or xyz.shape[1] != 3 or len(xyz) == 0 or rot6.shape != (len(xyz), 6):
                    raise ValueError(f"Unexpected {side} EEF action shapes: {xyz.shape}, {rot6.shape}")
                if not np.isfinite(xyz).all() or not np.isfinite(rot6).all():
                    raise ValueError(f"Non-finite {side} EEF action")
                report[side] = {
                    "steps": len(xyz),
                    "measured_joints_rad": state[side][0].tolist(),
                    "first_eef_xyz_m": xyz[0].tolist(),
                    "first_eef_rot6": rot6[0].tolist(),
                }
            print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    try:
        main()
    except (OSError, KeyError, ValueError, RuntimeError) as exc:
        raise SystemExit(f"Dream API probe: {exc}") from None
