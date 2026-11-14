from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from piper.active_driver import RAD_TO_MDEG, MDEG_TO_RAD, PiperGripperRange
from piper.custom_policy import PiperPolicy
from piper.rectification import rectify, letterbox


def test_sdk_units_and_asymmetric_grippers():
    q = np.array([-90., 0., 45.]) * np.pi / 180
    np.testing.assert_allclose(q * RAD_TO_MDEG, [-90000, 0, 45000])
    np.testing.assert_allclose(q * RAD_TO_MDEG * MDEG_TO_RAD, q)
    left, right = PiperGripperRange(-2000, 99700), PiperGripperRange(-900, 101400)
    assert left.command_for_opening(0.5) != right.command_for_opening(0.5)
    for grip in (left, right):
        assert abs(grip.normalize(grip.command_for_opening(.5))-.5) < 1e-4


def test_custom_solver_roundtrip_for_both_arms():
    config = SimpleNamespace(urdf=Path('assets/piper/piper.urdf'), frames={
        'left_base':'left_base_link', 'left_tcp':'left_tcp',
        'right_base':'right_base_link', 'right_tcp':'right_tcp'})
    observations = []
    client = SimpleNamespace(set_observation=lambda f,o,**kw: observations.append(o))
    policy = PiperPolicy(client, config)
    q = np.array([.1,.4,-.5,.2,.3,-.2])
    policy.set_observation({}, {f'state.{side}_arm':q.tolist() for side in ('left','right')})
    parts = {}
    for side in ('left','right'):
        for field in ('xyz','rot6'):
            parts[f'action.{side}_eef_{field}'] = [observations[0][f'state.{side}_eef_{field}']]
        parts[f'action.{side}_grip'] = [.4]
    client.get_action = lambda: {'per_key':parts}
    action = policy.get_action()
    for side,key in [('left','q_l_chunk'),('right','q_r_chunk')]:
        assert action[key].shape == (1,7)
        np.testing.assert_allclose(action[key][0,:6],q,atol=1e-4)
    parts['action.right_eef_rot6'] = [[0]*6]
    with pytest.raises(ValueError, match='degenerate'):
        policy.get_action()


def test_camera_requires_calibration_and_preserves_aspect():
    pytest.importorskip('cv2')
    image = np.full((100,200,3),255,dtype=np.uint8)
    assert rectify(image, {'index_or_path':'fake'}) is image
    with pytest.raises(ValueError, match='Missing measured'):
        rectify(image, {'index_or_path':'fake', 'rectification':{'enabled':True}})
    cropped = rectify(image, {'rectification':{'enabled':True,'already_rectified':True,'retain_fraction':.8}})
    assert cropped.shape == (80,160,3)
    output = letterbox(cropped)
    assert output.shape == (176,320,3)
    assert not output[0].any()


def test_rectification_uses_measured_resolution(tmp_path):
    pytest.importorskip('cv2')
    import yaml
    p = tmp_path/'camera.yaml'
    p.write_text(yaml.safe_dump({'resolution':[200,100], 'model':'pinhole',
        'camera_matrix':[[100,0,100],[0,100,50],[0,0,1]],
        'distortion_coefficients':[0,0,0,0,0]}))
    spec = {'rectification':{'enabled':True,'calibration_file':str(p)}}
    assert rectify(np.zeros((100,200,3),dtype=np.uint8),spec).shape == (80,160,3)
    with pytest.raises(ValueError, match='resolution'):
        rectify(np.zeros((50,100,3),dtype=np.uint8),spec)
