# Custom BiPiper recovery

The active probe uses the installation URDF in `assets/piper/piper.urdf`
and the custom solver recovered from scripts (9426238, b01b76f).
SDK arm JSON files are no longer used. The two TCP transforms are already
in the URDF; never add a second 145 mm offset.

Internal joints and IK outputs use radians; XYZ uses metres. Dream's
current EEF contract uses rot6, not quaternions. The SDK boundary alone
converts joint radians to milli-degrees. Grippers use separate measured
closed/open micrometre ranges in the configured calibration file.
The side labels on that file must be checked against the physical bus mapping.

## Camera configuration

Each camera in configs/cameras.yaml accepts:

```yaml
rectification:
  enabled: true
  calibration_file: /absolute/path/to/measured-camera.yaml
  retain_fraction: 0.8
  already_rectified: false
```

Measured camera YAML contains `resolution: [width, height]`,
`model: pinhole` or `fisheye`, `camera_matrix` (3x3), and
`distortion_coefficients`. Resolution must match capture resolution
(one eye for the ZED). Only mark already_rectified when the source is
known to deliver rectified images. The central 80% of each image dimension
is retained after rectification and then letterboxed to 320x176.
Intrinsics are not estimated from arbitrary scene images. Rectification defaults
to disabled: raw images are usable without intrinsics or the 80% crop.

## Outstanding deployment artifacts

No measured camera intrinsics or initial-pose values were found locally.
scripts/initial_pose.py is a loader, not the pose artifact. Dataset initial pose
is optional; if enabled, the probe validates the file and limits before hardware
initialization, moves both arms preserving aperture, and requests fresh actions.
If disabled, inference starts at the measured pose without automatic homing. No geometric
avoidance algorithm was found in scripts history: collision meshes and
driver collision bits do not establish preventive collision checking.
Physical joint limits are enforced by IK. These limits are not a geometric
collision checker. Neither optional dataset pose nor missing camera intrinsics
block execution when those features are disabled. This is not a validated grasp deployment.
No physical calibration or collision guarantee is claimed by passing unit tests.
