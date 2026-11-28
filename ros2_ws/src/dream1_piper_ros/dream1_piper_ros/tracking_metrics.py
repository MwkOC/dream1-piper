import math


def match_feedback_target(targets, feedback_stamp_sec, received_at, max_age_s):
    """Return the newest command no later than this feedback measurement."""
    for target in reversed(targets):
        ros_age = feedback_stamp_sec - target["issued_stamp_sec"]
        arrival_age = received_at - target["issued_at"]
        if 0 <= ros_age <= max_age_s and 0 <= arrival_age <= max_age_s:
            return target
    return None


def position_error_mm(target, measured):
    distance_m = math.sqrt(
        sum((float(a) - float(b)) ** 2 for a, b in zip(target, measured, strict=True))
    )
    return distance_m * 1000


def orientation_error_deg(target, measured):
    left = [float(value) for value in target]
    right = [float(value) for value in measured]
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        raise ValueError("feedback orientation quaternion must be non-zero")
    dot = abs(sum(a * b for a, b in zip(left, right, strict=True)) / (left_norm * right_norm))
    return 2 * math.acos(min(1.0, dot)) * 180 / math.pi
