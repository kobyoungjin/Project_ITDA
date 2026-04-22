"""
skeleton_extractor.py

AI Hub 라벨 JSON 의 keypoints 를 3D 아바타용 뼈대 회전값으로 변환합니다.

■ 두 가지 모드
  Mode A (AI Hub 라벨 기반): AI Hub 가 이미 keypoints(x,y,conf) 배열을 제공하는 경우
  Mode B (영상 기반):         원천영상(MP4)에서 MediaPipe 로 직접 추출하는 경우

■ AI Hub 수어(109) keypoints 좌표계
  - 정규화된 픽셀 좌표 (0~1 또는 0~width/height)
  - body:      18개 관절 (COCO 형식)
  - left_hand / right_hand: 21개 관절 (MediaPipe 형식)
  - face:      70개 관절 (선택)

■ 출력 형식
  뼈대 회전값 dict: { "RightArm": {"x": 0.3, "y": 0.1, "z": -0.2}, ... }
"""

import math
from pathlib import Path
from typing import Optional

import numpy as np

# ── COCO 18-joint 인덱스 정의 ──────────────────────────────────
COCO = {
    "NOSE": 0, "NECK": 1,
    "R_SHOULDER": 2, "R_ELBOW": 3, "R_WRIST": 4,
    "L_SHOULDER": 5, "L_ELBOW": 6, "L_WRIST": 7,
    "R_HIP": 8,  "R_KNEE": 9,  "R_ANKLE": 10,
    "L_HIP": 11, "L_KNEE": 12, "L_ANKLE": 13,
    "R_EYE": 14, "L_EYE": 15, "R_EAR": 16, "L_EAR": 17,
}

# ── 아바타 뼈 이름 매핑 (Three.js RobotExpressive / Mixamo 공용) ──
BONE_NAMES = {
    "RightArm":    "RightArm",
    "RightForeArm":"RightForeArm",
    "LeftArm":     "LeftArm",
    "LeftForeArm": "LeftForeArm",
    "Neck":        "Neck",
    "Spine":       "Spine",
    "RightHand":   "RightHand",
    "LeftHand":    "LeftHand",
}

# 손가락 관절 — MediaPipe 21 랜드마크 기반
FINGER_JOINTS = {
    "Thumb1":  2,  "Thumb2":  3,
    "Index1":  5,  "Index2":  6,
    "Middle1": 9,  "Middle2": 10,
    "Ring1":   13, "Ring2":   14,
    "Pinky1":  17, "Pinky2":  18,
}


# ── 수치 유틸 ──────────────────────────────────────────────────
def _to_np(pt: list | tuple | None) -> Optional[np.ndarray]:
    """[x, y, conf] 또는 [x, y, z, conf] → numpy 3D 벡터 (conf 제거)"""
    if pt is None or len(pt) < 2:
        return None
    return np.array(pt[:3] if len(pt) >= 3 else [pt[0], pt[1], 0.0], dtype=float)


def _angle_between(parent: np.ndarray, child: np.ndarray) -> dict:
    """두 3D 좌표 사이의 방향을 Euler 각도(라디안)로 반환합니다."""
    d = child - parent
    # 수어 영상 좌표계: y축 반전 (화면 아래=양수 → 실세계 위=양수)
    dx, dy, dz = d[0], -d[1], d[2] if len(d) > 2 else 0.0
    dist_xz = math.sqrt(dx ** 2 + dz ** 2) or 1e-6

    return {
        "x": math.atan2(-dy, dist_xz),
        "y": math.atan2(dx, dz or 1e-6),
        "z": 0.0,
    }


def _bend_angle(a: np.ndarray, b: np.ndarray, c: np.ndarray) -> float:
    """세 점으로 이루어진 관절 굽힘 각도(라디안)를 반환합니다."""
    ab = b - a
    bc = c - b
    cos_val = np.dot(ab, bc) / (np.linalg.norm(ab) * np.linalg.norm(bc) + 1e-8)
    return float(math.acos(np.clip(cos_val, -1.0, 1.0)))


def _conf(pt: list | None) -> float:
    """keypoint confidence 값을 반환합니다."""
    if pt is None or len(pt) < 3:
        return 0.0
    return float(pt[2])


# ── Mode A: AI Hub 라벨 keypoints → 뼈대 회전 ─────────────────
def extract_from_label_frame(frame: dict, conf_threshold: float = 0.3) -> dict:
    """
    AI Hub 수어 라벨의 단일 프레임 keypoints 를 아바타 뼈대 회전값으로 변환합니다.

    입력:
      frame = {
        "frameNo": 1,
        "keypoints": {
          "body":       [[x,y,conf], ...],   # 18개
          "left_hand":  [[x,y,conf], ...],   # 21개
          "right_hand": [[x,y,conf], ...],   # 21개
        }
      }
    출력:
      { "RightArm": {"x": 0.3, "y": 0.1, "z": 0.0}, ... }
    """
    kp = frame.get("keypoints", {})
    body  = kp.get("body",       kp.get("pose", []))
    lhand = kp.get("left_hand",  kp.get("leftHand", []))
    rhand = kp.get("right_hand", kp.get("rightHand", []))

    result = {}

    def get(arr: list, idx: int):
        return arr[idx] if idx < len(arr) else None

    # ── 오른팔 (COCO 인덱스 2,3,4) ────────────────────────────
    r_sh = _to_np(get(body, COCO["R_SHOULDER"]))
    r_el = _to_np(get(body, COCO["R_ELBOW"]))
    r_wr = _to_np(get(body, COCO["R_WRIST"]))

    if r_sh is not None and r_el is not None and _conf(get(body, COCO["R_ELBOW"])) > conf_threshold:
        ang = _angle_between(r_sh, r_el)
        # T-Pose 오프셋 보정: 기본 팔 방향은 오른쪽(-Z), 내릴 때 Z 보정
        result["RightArm"] = {"x": ang["x"] * 0.9, "y": ang["y"] * 0.7, "z": ang["z"] - math.pi / 2}

    if r_el is not None and r_wr is not None and _conf(get(body, COCO["R_WRIST"])) > conf_threshold:
        bend = _bend_angle(r_sh or r_el, r_el, r_wr) if r_sh is not None else 0.0
        result["RightForeArm"] = {"x": bend * 1.1, "y": 0.0, "z": 0.0}

    # ── 왼팔 (COCO 인덱스 5,6,7) ──────────────────────────────
    l_sh = _to_np(get(body, COCO["L_SHOULDER"]))
    l_el = _to_np(get(body, COCO["L_ELBOW"]))
    l_wr = _to_np(get(body, COCO["L_WRIST"]))

    if l_sh is not None and l_el is not None and _conf(get(body, COCO["L_ELBOW"])) > conf_threshold:
        ang = _angle_between(l_sh, l_el)
        result["LeftArm"] = {"x": ang["x"] * 0.9, "y": ang["y"] * 0.7, "z": ang["z"] + math.pi / 2}

    if l_el is not None and l_wr is not None and _conf(get(body, COCO["L_WRIST"])) > conf_threshold:
        bend = _bend_angle(l_sh or l_el, l_el, l_wr) if l_sh is not None else 0.0
        result["LeftForeArm"] = {"x": bend * 1.1, "y": 0.0, "z": 0.0}

    # ── 목/척추 (어깨 중점 → 목 방향) ─────────────────────────
    nose = _to_np(get(body, COCO["NOSE"]))
    neck = _to_np(get(body, COCO["NECK"]))
    if nose is not None and neck is not None:
        ang = _angle_between(neck, nose)
        result["Neck"] = {"x": ang["x"] * 0.5, "y": ang["y"] * 0.3, "z": 0.0}

    # ── 오른손 손가락 (MediaPipe 21 관절) ─────────────────────
    if rhand:
        result.update(_extract_finger_bones(rhand, "Right", conf_threshold))

    # ── 왼손 손가락 ───────────────────────────────────────────
    if lhand:
        result.update(_extract_finger_bones(lhand, "Left", conf_threshold))

    return result


def _extract_finger_bones(hand_kp: list, side: str, conf_threshold: float) -> dict:
    """손 keypoints(21개) → 손가락 뼈대 회전값 dict"""
    result = {}
    wrist = _to_np(hand_kp[0]) if hand_kp else None
    if wrist is None:
        return result

    for joint_name, idx in FINGER_JOINTS.items():
        if idx >= len(hand_kp):
            continue
        pt = hand_kp[idx]
        if _conf(pt) < conf_threshold:
            continue
        tip = _to_np(pt)
        if tip is None:
            continue
        ang = _angle_between(wrist, tip)
        result[f"{side}Hand{joint_name}"] = {
            "x": ang["x"] * 0.8,
            "y": ang["y"] * 0.6,
            "z": 0.0,
        }

    return result


# ── Mode B: 영상(MP4) → MediaPipe 추출 ────────────────────────
def extract_from_video(video_path: str | Path, max_frames: int = 300) -> list[dict]:
    """
    원천영상(MP4)에서 MediaPipe PoseLandmarker + HandLandmarker로
    프레임별 뼈대 회전값을 추출합니다.

    반환: [{"time": 0.033, "bones": {...}}, ...]
    """
    try:
        import cv2
        import mediapipe as mp
    except ImportError:
        raise ImportError(
            "영상 기반 추출에는 opencv-python 과 mediapipe 가 필요합니다.\n"
            "pip install opencv-python mediapipe"
        )

    mp_pose  = mp.solutions.pose
    mp_hands = mp.solutions.hands

    cap = cv2.VideoCapture(str(video_path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    frame_results = []

    with mp_pose.Pose(min_detection_confidence=0.5, min_tracking_confidence=0.5) as pose, \
         mp_hands.Hands(max_num_hands=2, min_detection_confidence=0.5) as hands_model:

        frame_no = 0
        while cap.isOpened() and frame_no < max_frames:
            ret, bgr = cap.read()
            if not ret:
                break

            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
            pose_res  = pose.process(rgb)
            hands_res = hands_model.process(rgb)

            # MediaPipe Pose → 아바타 뼈 회전값
            bones = _mediapipe_pose_to_bones(pose_res, hands_res)
            frame_results.append({"time": frame_no / fps, "bones": bones})
            frame_no += 1

    cap.release()
    return frame_results


def _mediapipe_pose_to_bones(pose_result, hands_result) -> dict:
    """MediaPipe 결과를 아바타 뼈대 회전값으로 변환합니다."""
    bones = {}

    if pose_result.pose_landmarks:
        lm = pose_result.pose_landmarks.landmark
        import mediapipe as mp
        P = mp.solutions.pose.PoseLandmark

        def lm_np(idx): return np.array([lm[idx].x, lm[idx].y, lm[idx].z])

        r_sh, r_el, r_wr = lm_np(P.RIGHT_SHOULDER), lm_np(P.RIGHT_ELBOW), lm_np(P.RIGHT_WRIST)
        l_sh, l_el, l_wr = lm_np(P.LEFT_SHOULDER),  lm_np(P.LEFT_ELBOW),  lm_np(P.LEFT_WRIST)

        ra = _angle_between(r_sh, r_el)
        bones["RightArm"]     = {"x": ra["x"], "y": ra["y"], "z": ra["z"] - math.pi / 2}
        bones["RightForeArm"] = {"x": _bend_angle(r_sh, r_el, r_wr) * 1.1, "y": 0.0, "z": 0.0}

        la = _angle_between(l_sh, l_el)
        bones["LeftArm"]      = {"x": la["x"], "y": la["y"], "z": la["z"] + math.pi / 2}
        bones["LeftForeArm"]  = {"x": _bend_angle(l_sh, l_el, l_wr) * 1.1, "y": 0.0, "z": 0.0}

    if hands_result.multi_hand_landmarks:
        for hand_lm, hand_info in zip(
            hands_result.multi_hand_landmarks,
            hands_result.multi_handedness
        ):
            side = hand_info.classification[0].label  # "Left" | "Right"
            kp = [[lm.x, lm.y, lm.z, 1.0] for lm in hand_lm.landmark]
            bones.update(_extract_finger_bones(kp, side, conf_threshold=0.0))

    return bones
