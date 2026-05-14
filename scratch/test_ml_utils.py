import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from api.core.ml_utils import extract_ksl_features
import numpy as np

# Mock landmarks
r_lms = [{"x": 0.5, "y": 0.5, "z": 0.0}] * 21
l_lms = [{"x": 0.1, "y": 0.1, "z": 0.0}] * 21
pose_lms = {
    "landmarks": {
        "right_shoulder": {"x": 0.6, "y": 0.3},
        "left_shoulder": {"x": 0.4, "y": 0.3},
        "right_elbow": {"x": 0.7, "y": 0.5},
        "left_elbow": {"x": 0.3, "y": 0.5},
        "right_wrist": {"x": 0.5, "y": 0.5},
        "left_wrist": {"x": 0.1, "y": 0.1},
    }
}

try:
    feat = extract_ksl_features(r_lms, l_lms, pose_lms)
    print(f"Success: Feature length = {len(feat)}")
    print(f"Sample features: {feat[:5]}")
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
