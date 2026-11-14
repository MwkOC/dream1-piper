#!/usr/bin/env python3
"""Capture ChArUco views and calibrate the cameras in configs/cameras.yaml."""
from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cv2
import numpy as np

from calibration.spatial import (CharucoBoardSpec, calibrate_fisheye, calibrate_pinhole,
                                 detect_charuco, draw_detection, load_yaml,
                                 new_spatial_calibration, write_yaml)
LOG = logging.getLogger(__name__)


def capture_views(name, config, board, count):
    if any(line.strip().split() == ['GUI:', 'NONE']
           for line in cv2.getBuildInformation().splitlines()):
        raise RuntimeError(
            'OpenCV no tiene soporte gráfico. Usa el entorno de calibración '
            'descrito en docs/calibracion_camaras.md.'
        )
    source = config['index_or_path']
    width, height = int(config['width']), int(config['height'])
    fps = int(config.get('fps', 30))
    backend_name = str(config.get('backend', 'V4L2')).upper()
    backend = getattr(cv2, 'CAP_' + backend_name, None)
    if backend is None:
        raise ValueError(f'Unknown OpenCV backend: {backend_name}')
    if config.get('type') != 'opencv':
        raise ValueError(f'Unsupported ChArUco camera type: {config.get("type")}')
    camera = cv2.VideoCapture(source, backend)
    if not camera.isOpened():
        camera.release()
        raise RuntimeError(f'Cannot open camera {name}: {source}')
    camera.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    camera.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    camera.set(cv2.CAP_PROP_FPS, fps)
    def read():
        ok, frame = camera.read()
        if not ok or frame is None:
            raise RuntimeError(f'Cannot read camera {name}: {source}')
        if frame.shape[:2] != (height, width):
            raise RuntimeError(f'{name}: expected {width}x{height}, got {frame.shape[1]}x{frame.shape[0]}')
        return frame
    close = camera.release

    title = f'Calibration: {name}'
    detections, signatures = [], []
    size = None
    next_capture = time.monotonic() + 2
    window_open = False
    try:
        cv2.namedWindow(title, cv2.WINDOW_NORMAL)
        window_open = True
        while len(detections) < count:
            frame = read()
            size = (frame.shape[1], frame.shape[0])
            detection = detect_charuco(frame, board, min_corners=12)
            distinct = False
            if detection is not None:
                points = detection.image_points.reshape(-1, 2)
                signature = np.r_[points.mean(axis=0) / size, np.ptp(points, axis=0) / size]
                distinct = all(np.linalg.norm(signature - old) >= 0.05 for old in signatures)
            preview = draw_detection(frame, detection)
            status = f'{name}: {len(detections)}/{count} | move board | Q: quit'
            cv2.putText(preview, status, (10, 25), cv2.FONT_HERSHEY_SIMPLEX, .55, (0, 255, 0), 2)
            cv2.imshow(title, preview)
            if cv2.waitKey(1) & 0xff in (ord('q'), 27):
                break
            now = time.monotonic()
            if now >= next_capture:
                next_capture = now + 2
                if detection is not None and distinct:
                    detections.append(detection)
                    signatures.append(signature)
                    LOG.info('%s: accepted view %d/%d (%d corners)', name, len(detections), count, detection.count)
    finally:
        close()
        if window_open:
            try:
                cv2.destroyWindow(title)
            except cv2.error:
                LOG.warning('No se pudo cerrar la ventana de calibración.', exc_info=True)
    if len(detections) != count:
        raise RuntimeError(f'{name}: only {len(detections)}/{count} views captured; calibration not saved')
    return detections, size


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT / 'configs/cameras.yaml')
    parser.add_argument('--camera', action='append', help='OpenCV camera name; repeat to select several (default: all OpenCV cameras)')
    parser.add_argument('--views', type=int, default=15)
    parser.add_argument('--model', choices=('pinhole', 'fisheye'), default='pinhole')
    parser.add_argument('--max-mean-error-px', type=float, default=0.8)
    parser.add_argument('--output', type=Path, default=ROOT / 'outputs/calibration/spatial.yaml')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    if args.views < 10:
        parser.error('--views must be at least 10')
    config = load_yaml(args.config)
    cameras = config.get('cameras', {})
    names = args.camera or [name for name, camera in cameras.items() if camera.get('type') == 'opencv']
    if not names or any(name not in cameras for name in names):
        parser.error(f'Unknown or missing camera. Available: {", ".join(cameras)}')
    if any(cameras[name].get('type') != 'opencv' for name in names):
        parser.error('Only OpenCV cameras can be calibrated; ZED uses its factory calibration')
    board = CharucoBoardSpec.from_dict(config.get('spatial_calibration', {}).get('board'))
    spatial = load_yaml(args.output) if args.output.exists() else new_spatial_calibration(board)
    if spatial.get('kind') != 'handumi_spatial_calibration' or CharucoBoardSpec.from_dict(spatial.get('board')) != board:
        raise SystemExit('Output file has an incompatible calibration or board configuration')
    for name in names:
        LOG.info('Capture %s: show the board in varied positions, distances and angles.', name)
        detections, size = capture_views(name, cameras[name], board, args.views)
        calibrate = calibrate_pinhole if args.model == 'pinhole' else calibrate_fisheye
        intrinsics = calibrate(name, detections, size)
        if not np.isfinite(intrinsics.mean_error_px) or intrinsics.mean_error_px > args.max_mean_error_px:
            raise RuntimeError(f'{name}: reprojection error {intrinsics.mean_error_px:.3f}px exceeds limit; calibration not saved')
        spatial.setdefault('cameras', {})[name] = {**intrinsics.to_dict(),
            'index_or_path': cameras[name]['index_or_path'],
            'captured_at': datetime.now(UTC).isoformat()}
        write_yaml(args.output, spatial)
        LOG.info('%s saved to %s; mean error %.3f px', name, args.output, intrinsics.mean_error_px)


if __name__ == '__main__':
    main()
