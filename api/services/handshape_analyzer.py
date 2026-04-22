"""
handshape_analyzer.py ─ [P0] KSL Handshape 분류기

MediaPipe HandLandmarker 21개 관절 좌표로부터:
  1) 손가락별 MCP / PIP / DIP 굴곡 각도(도 단위) 추출
  2) KSL 기본 수형 6종(FIST / PALM / POINT / V / L / OK)으로 분류
  3) 손바닥 방향(Orientation)과 손목-중지 축 기반 손 회전 추정

ws_vision.py 에서 각 손마다 호출되어 meta_features 에 주입됩니다.

── MediaPipe 21 landmark 구조 ──────────────────────────
 0 : WRIST
 1-4   : THUMB    (CMC, MCP, IP, TIP)
 5-8   : INDEX    (MCP, PIP, DIP, TIP)
 9-12  : MIDDLE   (MCP, PIP, DIP, TIP)
13-16  : RING     (MCP, PIP, DIP, TIP)
17-20  : PINKY    (MCP, PIP, DIP, TIP)
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional

import numpy as np

# ── 손가락별 landmark 인덱스 ──────────────────────────────────
FINGER_INDICES: Dict[str, List[int]] = {
    "thumb":  [1, 2, 3, 4],
    "index":  [5, 6, 7, 8],
    "middle": [9, 10, 11, 12],
    "ring":   [13, 14, 15, 16],
    "pinky":  [17, 18, 19, 20],
}
WRIST_IDX = 0

# 굴곡 판정 임계값(도). 90도 이하는 'curled', 160도 이상은 'extended'
CURLED_THRESHOLD_DEG = 90.0
EXTENDED_THRESHOLD_DEG = 160.0

# 엄지는 구조가 달라 완화된 임계값 사용
THUMB_CURLED_THRESHOLD_DEG = 130.0
THUMB_EXTENDED_THRESHOLD_DEG = 150.0


def _to_np(p: dict) -> np.ndarray:
    """{'x':..,'y':..,'z':..} 딕셔너리를 np.ndarray 로 변환"""
    return np.array([p["x"], p["y"], p.get("z", 0.0)], dtype=np.float32)


def _angle_deg(a: np.ndarray, b: np.ndarray, c: np.ndarray) -> float:
    """벡터 BA 와 BC 사이 각도(도). b 가 꼭짓점."""
    ba = a - b
    bc = c - b
    norm = np.linalg.norm(ba) * np.linalg.norm(bc)
    if norm < 1e-8:
        return 180.0
    cos_t = float(np.dot(ba, bc) / norm)
    cos_t = max(-1.0, min(1.0, cos_t))
    return math.degrees(math.acos(cos_t))


def compute_finger_bends(landmarks: List[dict]) -> Dict[str, Dict[str, float]]:
    """
    손가락별 MCP·PIP·DIP 관절 각도를 반환.
    값이 180에 가까울수록 '곧게 펴진 상태', 90 이하면 '접힌 상태'.

    엄지는 관절 구조가 달라 CMC·MCP·IP 3관절 각도로 대체 계산.
    """
    wrist = _to_np(landmarks[WRIST_IDX])
    bends: Dict[str, Dict[str, float]] = {}

    for finger, idx in FINGER_INDICES.items():
        p0 = _to_np(landmarks[idx[0]])  # MCP (엄지는 CMC)
        p1 = _to_np(landmarks[idx[1]])  # PIP (엄지는 MCP)
        p2 = _to_np(landmarks[idx[2]])  # DIP (엄지는 IP)
        p3 = _to_np(landmarks[idx[3]])  # TIP

        # MCP 각도 = WRIST - MCP - PIP (손바닥에서 손가락이 얼마나 들렸는가)
        mcp_angle = _angle_deg(wrist, p0, p1)
        # PIP 각도 = MCP - PIP - DIP (중간 마디 굴곡)
        pip_angle = _angle_deg(p0, p1, p2)
        # DIP 각도 = PIP - DIP - TIP (끝 마디 굴곡)
        dip_angle = _angle_deg(p1, p2, p3)

        is_thumb = finger == "thumb"
        curl_th = THUMB_CURLED_THRESHOLD_DEG if is_thumb else CURLED_THRESHOLD_DEG
        ext_th = THUMB_EXTENDED_THRESHOLD_DEG if is_thumb else EXTENDED_THRESHOLD_DEG

        # 대표 굴곡도:
        #   - 엄지: MCP + PIP 평균 (엄지 IP 관절은 DIP 역할)
        #   - 그 외: PIP 각도 단독 (중간 마디가 손가락 굴곡을 가장 직관적으로 반영하고,
        #           DIP 는 사람에 따라 곧게 유지되는 경우가 많아 평균을 내면 오판 유발)
        representative = (mcp_angle + pip_angle) / 2 if is_thumb else pip_angle

        if representative >= ext_th:
            state = "extended"
        elif representative <= curl_th:
            state = "curled"
        else:
            state = "half"

        bends[finger] = {
            "mcp": round(mcp_angle, 1),
            "pip": round(pip_angle, 1),
            "dip": round(dip_angle, 1),
            "representative": round(representative, 1),
            "state": state,
        }
    return bends


def _finger_extended(bends: Dict[str, Dict[str, float]], finger: str) -> bool:
    return bends[finger]["state"] == "extended"


def _finger_curled(bends: Dict[str, Dict[str, float]], finger: str) -> bool:
    return bends[finger]["state"] == "curled"


def _thumb_index_pinch(landmarks: List[dict]) -> float:
    """엄지 끝(4)과 검지 끝(8) 사이 거리. OK 수형 판정용."""
    t = _to_np(landmarks[4])
    i = _to_np(landmarks[8])
    return float(np.linalg.norm(t - i))


def _palm_size(landmarks: List[dict]) -> float:
    """손바닥 기준 길이 = WRIST(0) ~ MIDDLE_MCP(9)"""
    return float(np.linalg.norm(_to_np(landmarks[0]) - _to_np(landmarks[9])))


def classify_handshape(
    bends: Dict[str, Dict[str, float]],
    landmarks: List[dict],
) -> str:
    """
    KSL 기본 수형 6종으로 분류:
      FIST  : 모든 손가락이 접힘 (주먹)
      PALM  : 모든 손가락이 펴짐 (평손)
      POINT : 검지만 펴짐 (가리키기)
      V     : 검지+중지 펴짐, 그 외 접힘
      L     : 엄지+검지 펴짐, 그 외 접힘
      OK    : 엄지와 검지 끝이 닿고 나머지 펴짐
      UNKNOWN: 위 조건 어디에도 매칭 안 됨
    """
    ext = {f: _finger_extended(bends, f) for f in FINGER_INDICES}
    cur = {f: _finger_curled(bends, f) for f in FINGER_INDICES}

    palm = _palm_size(landmarks) or 1e-6
    pinch = _thumb_index_pinch(landmarks) / palm  # 손바닥 크기로 정규화

    # OK: 엄지-검지 끝이 가깝고(손바닥 대비 25% 이하), 중·약·소지는 펴짐
    if pinch < 0.25 and ext["middle"] and ext["ring"] and ext["pinky"]:
        return "OK"

    # FIST: 네 손가락(검지~소지) 모두 접힘, 엄지는 무관
    if cur["index"] and cur["middle"] and cur["ring"] and cur["pinky"]:
        return "FIST"

    # PALM: 네 손가락 모두 펴짐
    if ext["index"] and ext["middle"] and ext["ring"] and ext["pinky"]:
        return "PALM"

    # V: 검지+중지 펴지고 약지+소지 접힘
    if ext["index"] and ext["middle"] and cur["ring"] and cur["pinky"]:
        return "V"

    # L: 엄지+검지 펴지고 중지+약지+소지 접힘
    if ext["thumb"] and ext["index"] and cur["middle"] and cur["ring"] and cur["pinky"]:
        return "L"

    # POINT: 검지만 펴지고 나머지 네 손가락(엄지 포함 X - 중/약/소) 접힘
    if ext["index"] and cur["middle"] and cur["ring"] and cur["pinky"]:
        return "POINT"

    return "UNKNOWN"


def compute_orientation(landmarks: List[dict]) -> Dict[str, float]:
    """
    손 회전(손목→중지 MCP 축)과 손바닥 법선(엄지 MCP × 새끼 MCP) 근사.
    카메라 좌표계 기준이며, z 부호로 '손바닥이 카메라를 향함 / 등을 향함' 구분.
    """
    wrist = _to_np(landmarks[0])
    mid_mcp = _to_np(landmarks[9])
    thumb_mcp = _to_np(landmarks[2])
    pinky_mcp = _to_np(landmarks[17])

    forward = mid_mcp - wrist  # 손가락이 향한 방향
    side = pinky_mcp - thumb_mcp  # 손바닥 좌우 축
    normal = np.cross(side, forward)
    n_norm = np.linalg.norm(normal)
    if n_norm > 1e-6:
        normal = normal / n_norm

    # 손가락이 향한 방향의 화면 각도(0도=오른쪽, 90도=위)
    finger_angle_deg = math.degrees(math.atan2(-forward[1], forward[0]))

    return {
        "finger_angle_deg": round(finger_angle_deg, 1),
        "palm_normal_z": round(float(normal[2]), 3),  # >0: 손등이 카메라, <0: 손바닥이 카메라
        "palm_facing_camera": bool(normal[2] < 0),
    }


def analyze_hand(hand: dict) -> Optional[Dict]:
    """
    ws_vision 에서 호출하는 진입점.

    입력: {"handedness": "Left"/"Right", "keypoints": [{"x","y","z"}, ... 21개]}
    출력: {
        "handedness": ...,
        "handshape":  "FIST" | "PALM" | ...,
        "bends":      {finger: {mcp, pip, dip, representative, state}},
        "orientation":{finger_angle_deg, palm_normal_z, palm_facing_camera}
    }
    키포인트가 21개 미만이면 None.
    """
    kps = hand.get("keypoints") or []
    if len(kps) < 21:
        return None

    bends = compute_finger_bends(kps)
    shape = classify_handshape(bends, kps)
    orient = compute_orientation(kps)

    return {
        "handedness": hand.get("handedness", "Unknown"),
        "handshape": shape,
        "bends": bends,
        "orientation": orient,
    }


def describe_for_slm(analyses: List[Dict]) -> str:
    """
    분석 결과를 SLM 프롬프트에 그대로 주입할 수 있는 자연어로 요약.
    예: "오른손: 수형 POINT, 손바닥이 카메라 반대, 검지 펴짐 / 왼손: 수형 FIST"
    """
    if not analyses:
        return "손이 감지되지 않음"

    parts = []
    for a in analyses:
        side = a["handedness"]
        shape = a["handshape"]
        facing = "카메라 방향" if a["orientation"]["palm_facing_camera"] else "카메라 반대"
        extended = [k for k, v in a["bends"].items() if v["state"] == "extended"]
        ext_txt = (", ".join(extended) + " 펴짐") if extended else "모두 접힘"
        parts.append(f"{side}손: 수형 {shape}, 손바닥 {facing}, {ext_txt}")
    return " / ".join(parts)
