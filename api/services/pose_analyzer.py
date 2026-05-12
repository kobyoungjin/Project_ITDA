"""
pose_analyzer.py ─ [P0] 상체 Pose(어깨/팔꿈치/손목) 분석기

MediaPipe PoseLandmarker 의 33개 관절 중 수어 해석에 필요한
어깨·팔꿈치·손목·힙 좌표만 받아 다음을 계산합니다:

  1) 팔꿈치 굽힘 각도 (어깨-팔꿈치-손목 사이각, 도)
  2) 어깨 상승도 (엉덩이 대비 어깨 높이, 0~1 상대치)
  3) 팔 확장 방향 (어깨 기준 손목 위치 → 위/아래/옆/앞)
  4) 양팔 좌우 교차 여부

수어는 손가락뿐 아니라 팔 전체의 공간적 위치가 의미를 갖습니다.
ex) "안녕하세요" = 이마 높이 → 가슴 높이 직선 하강 + PALM 수형
     "미안합니다" = 가슴 앞 + FIST + 약간 고개 숙임
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional

import numpy as np

# MediaPipe Pose landmark 인덱스 (33개 중 수어용 8개)
POSE = {
    "nose": 0,
    "left_shoulder": 11,
    "right_shoulder": 12,
    "left_elbow": 13,
    "right_elbow": 14,
    "left_wrist": 15,
    "right_wrist": 16,
    "left_hip": 23,
    "right_hip": 24,
}

VISIBILITY_THRESHOLD = 0.3 # 관절이 겹칠 때(Occlusion)의 인식률 보완을 위해 0.5 -> 0.3으로 하향


def _to_np(p: dict) -> np.ndarray:
    return np.array([p["x"], p["y"], p.get("z", 0.0)], dtype=np.float32)


def _angle_deg(a: np.ndarray, b: np.ndarray, c: np.ndarray) -> float:
    ba = a - b
    bc = c - b
    n = np.linalg.norm(ba) * np.linalg.norm(bc)
    if n < 1e-8:
        return 180.0
    cos_t = max(-1.0, min(1.0, float(np.dot(ba, bc) / n)))
    return math.degrees(math.acos(cos_t))


def _visible(lm: Optional[dict]) -> bool:
    if not lm:
        return False
    return lm.get("visibility", 1.0) >= VISIBILITY_THRESHOLD


def _classify_wrist_region(wrist: np.ndarray, shoulder: np.ndarray, hip: np.ndarray) -> str:
    """
    어깨·엉덩이를 기준으로 손목이 얼굴/가슴/허리/아래 구역 어디에 있는지 분류.
    화면 좌표(y는 아래로 증가)를 사용하므로 음수가 위쪽임을 유의.
    """
    torso = abs(hip[1] - shoulder[1]) or 1e-6
    # shoulder 기준 상대 높이 (위로 갈수록 양수)
    rel_y = (shoulder[1] - wrist[1]) / torso

    if rel_y > 0.9:
        return "얼굴 위"
    elif rel_y > 0.4:
        return "얼굴"
    elif rel_y > -0.2:
        return "가슴"
    elif rel_y > -0.7:
        return "허리"
    else:
        return "하체"


def _classify_arm_extension(shoulder: np.ndarray, wrist: np.ndarray) -> str:
    """어깨 대비 손목의 방향(위/아래/앞/옆/교차)을 문자열로 반환."""
    dx = wrist[0] - shoulder[0]
    dy = wrist[1] - shoulder[1]  # 화면 좌표: 아래로 +
    dz = wrist[2] - shoulder[2]  # 카메라 방향: 앞으로 -

    # 가장 큰 성분을 주축으로 선택
    ax = abs(dx); ay = abs(dy); az = abs(dz)
    if ay >= ax and ay >= az:
        return "아래로" if dy > 0 else "위로"
    if ax >= az:
        return "옆으로"
    return "앞으로"


def analyze_pose(pose: dict) -> Optional[Dict]:
    """
    입력: {
      "landmarks": { "left_shoulder": {x,y,z,visibility}, ... }  # 또는 idx 키 0~33
    }
    출력: {
      "elbow_bend_L": float,       # 팔꿈치 굽힘 각도 (도, 180=펼침)
      "elbow_bend_R": float,
      "wrist_region_L": str,       # "얼굴|가슴|허리|하체"
      "wrist_region_R": str,
      "arm_dir_L": str,            # "위로|아래로|옆으로|앞으로"
      "arm_dir_R": str,
      "shoulder_raise": float,     # 0~1 (평상시 0.5, 들어올림 1.0)
      "arms_crossed": bool,
      "summary": str               # SLM 프롬프트에 주입할 자연어 요약
    }
    필수 관절(어깨·팔꿈치·손목) 중 한쪽도 감지 안 되면 None.
    """
    lms = pose.get("landmarks") or {}
    required = ["left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
                "left_wrist", "right_wrist"]
    if not all(_visible(lms.get(k)) for k in required):
        return None

    ls = _to_np(lms["left_shoulder"]);   rs = _to_np(lms["right_shoulder"])
    le = _to_np(lms["left_elbow"]);      re = _to_np(lms["right_elbow"])
    lw = _to_np(lms["left_wrist"]);      rw = _to_np(lms["right_wrist"])

    # 엉덩이는 없어도 가능하나, 있으면 구역 분류 정확도 향상
    lh = _to_np(lms["left_hip"]) if _visible(lms.get("left_hip")) else ls + np.array([0, 1.0, 0])
    rh = _to_np(lms["right_hip"]) if _visible(lms.get("right_hip")) else rs + np.array([0, 1.0, 0])

    elbow_bend_L = _angle_deg(ls, le, lw)
    elbow_bend_R = _angle_deg(rs, re, rw)

    region_L = _classify_wrist_region(lw, ls, lh)
    region_R = _classify_wrist_region(rw, rs, rh)

    arm_dir_L = _classify_arm_extension(ls, lw)
    arm_dir_R = _classify_arm_extension(rs, rw)

    # 어깨 상승: 엉덩이 대비 어깨 Y 위치 (정상=0.5, 들어올림=1.0)
    torso_len = abs((lh[1] + rh[1]) / 2 - (ls[1] + rs[1]) / 2) or 1e-6
    shoulder_raise = max(0.0, min(1.0,
        0.5 + (((lh[1] + rh[1]) / 2) - ((ls[1] + rs[1]) / 2) - torso_len) / torso_len
    ))

    # 양팔 교차: 왼손목이 오른어깨보다 오른쪽, 오른손목이 왼어깨보다 왼쪽
    arms_crossed = (lw[0] > rs[0]) and (rw[0] < ls[0])

    summary = (
        f"오른팔: 손목이 {region_R}, {arm_dir_R} 뻗음(팔꿈치 {elbow_bend_R:.0f}도) / "
        f"왼팔: 손목이 {region_L}, {arm_dir_L} 뻗음(팔꿈치 {elbow_bend_L:.0f}도)"
    )
    if arms_crossed:
        summary += " / 양팔 교차"

    return {
        "elbow_bend_L": round(elbow_bend_L, 1),
        "elbow_bend_R": round(elbow_bend_R, 1),
        "wrist_region_L": region_L,
        "wrist_region_R": region_R,
        "arm_dir_L": arm_dir_L,
        "arm_dir_R": arm_dir_R,
        "shoulder_raise": round(float(shoulder_raise), 3),
        "arms_crossed": arms_crossed,
        "summary": summary,
    }
