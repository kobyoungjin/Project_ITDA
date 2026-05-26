import math
import numpy as np
from typing import Optional


# ── 시계열 특징을 위한 상태 저장 (속도 계산용) ──────────────────
_prev_state = {"right_wrist": None, "left_wrist": None}

def reset_prev_state():
    """영상 전환 시 이전 프레임 좌표 정보를 초기화합니다."""
    global _prev_state
    _prev_state = {"right_wrist": None, "left_wrist": None}

def snapshot_prev_state() -> dict:
    """현재 모션 상태(_prev_state)를 깊은 복사로 저장합니다.
    좌우 스왑 평가 등 보조 추론이 속도 계산용 상태를 오염시키는 것을 막는 용도입니다."""
    return {k: (dict(v) if v else None) for k, v in _prev_state.items()}

def restore_prev_state(snapshot: dict) -> None:
    """snapshot_prev_state()로 저장해 둔 모션 상태를 복원합니다."""
    global _prev_state
    _prev_state = {k: (dict(v) if v else None) for k, v in snapshot.items()}

def extract_ksl_features(right_landmarks: Optional[list], left_landmarks: Optional[list], pose_landmarks: Optional[dict] = None) -> Optional[list]:
    global _prev_state
    
    def _extract_single_hand_features(landmarks: Optional[list]) -> list[float]:
        # 손이 감지되지 않은 경우 0으로 채움 (16차원)
        if not landmarks or len(landmarks) < 21:
            return [0.0] * 16

        # 손목을 원점으로 이동
        wrist = landmarks[0]
        pts = np.array([[lm["x"] - wrist["x"], lm["y"] - wrist["y"], lm.get("z", 0) - wrist.get("z", 0)] for lm in landmarks])

        # 관절 벡터 및 각도 계산 (기존 로직 유지)
        parents = [0,1,2,3, 0,5,6,7, 0,9,10,11, 0,13,14,15, 0,17,18,19]
        children = [1,2,3,4, 5,6,7,8, 9,10,11,12, 13,14,15,16, 17,18,19,20]
        v = pts[children] - pts[parents]
        v_norm = np.linalg.norm(v, axis=1)[:, np.newaxis]
        v_unit = np.divide(v, v_norm, out=np.zeros_like(v), where=v_norm > 1e-9)
        idx1 = [0,1,2, 4,5,6, 8,9,10, 12,13,14, 16,17,18]
        idx2 = [1,2,3, 5,6,7, 9,10,11, 13,14,15, 17,18,19]
        dot_product = np.einsum('nt,nt->n', v_unit[idx1], v_unit[idx2])
        angles = np.arccos(np.clip(dot_product, -1.0, 1.0)) / np.pi
        
        feats = angles.tolist()
        feats.append(1.0) # 감지 플래그
        return feats

    # 1. 각 손의 특징 추출
    right_feats = _extract_single_hand_features(right_landmarks)
    left_feats = _extract_single_hand_features(left_landmarks)

    # 2. [NEW] 이동 속도 및 방향 특징 (Velocity, 6차원)
    # 이전 프레임과의 손목 좌표 차이를 계산하여 '움직임의 궤적'을 파악함
    velocity = [0.0] * 6 # [rx, ry, rz, lx, ly, lz]
    
    if right_landmarks:
        rw = right_landmarks[0]
        if _prev_state["right_wrist"]:
            pw = _prev_state["right_wrist"]
            velocity[0] = math.tanh((rw["x"] - pw["x"]) * 10) # 변화량 증폭
            velocity[1] = math.tanh((rw["y"] - pw["y"]) * 10)
            velocity[2] = math.tanh((rw.get("z",0) - pw.get("z",0)) * 10)
        _prev_state["right_wrist"] = {"x": rw["x"], "y": rw["y"], "z": rw.get("z", 0)}
    else:
        _prev_state["right_wrist"] = None

    if left_landmarks:
        lw = left_landmarks[0]
        if _prev_state["left_wrist"]:
            pw = _prev_state["left_wrist"]
            velocity[3] = math.tanh((lw["x"] - pw["x"]) * 10)
            velocity[4] = math.tanh((lw["y"] - pw["y"]) * 10)
            velocity[5] = math.tanh((lw.get("z",0) - pw.get("z",0)) * 10)
        _prev_state["left_wrist"] = {"x": lw["x"], "y": lw["y"], "z": lw.get("z", 0)}
    else:
        _prev_state["left_wrist"] = None

    # 3. 상대 위치 특징 (Nose, Shoulders)
    rel_pos = [0.0] * 12
    if pose_landmarks:
        lms = pose_landmarks.get("landmarks", {})
        rs, ls, nose = lms.get("right_shoulder"), lms.get("left_shoulder"), lms.get("nose")
        shoulder_width = 0.2
        if rs and ls:
            shoulder_width = math.sqrt((rs['x']-ls['x'])**2 + (rs['y']-ls['y'])**2)
        if shoulder_width < 0.01: shoulder_width = 0.2

        if rs and right_landmarks:
            rw = right_landmarks[0]
            rel_pos[0:3] = [math.tanh((rw["x"]-rs["x"])/shoulder_width), math.tanh((rw["y"]-rs["y"])/shoulder_width), math.tanh((rw.get("z",0)-rs.get("z",0))/shoulder_width)]
        if ls and left_landmarks:
            lw = left_landmarks[0]
            rel_pos[3:6] = [math.tanh((lw["x"]-ls["x"])/shoulder_width), math.tanh((lw["y"]-ls["y"])/shoulder_width), math.tanh((lw.get("z",0)-ls.get("z",0))/shoulder_width)]
        if nose:
            if right_landmarks:
                rw = right_landmarks[0]
                rel_pos[6:9] = [math.tanh((rw["x"]-nose["x"])/shoulder_width), math.tanh((rw["y"]-nose["y"])/shoulder_width), math.tanh((rw.get("z",0)-nose.get("z",0))/shoulder_width)]
            if left_landmarks:
                lw = left_landmarks[0]
                rel_pos[9:12] = [math.tanh((lw["x"]-nose["x"])/shoulder_width), math.tanh((lw["y"]-nose["y"])/shoulder_width), math.tanh((lw.get("z",0)-nose.get("z",0))/shoulder_width)]

    # 4. 팔 관절 및 통합
    arm_feats = [0.5, 0.5]
    if pose_landmarks:
        lms = pose_landmarks.get("landmarks", {})
        def _get_elbow_angle(side):
            s, e, w = lms.get(f"{side}_shoulder"), lms.get(f"{side}_elbow"), lms.get(f"{side}_wrist")
            if s and e and w:
                ba, bc = np.array([s['x']-e['x'], s['y']-e['y'], (s.get('z',0)-e.get('z',0))]), np.array([w['x']-e['x'], w['y']-e['y'], (w.get('z',0)-e.get('z',0))])
                m = np.linalg.norm(ba) * np.linalg.norm(bc)
                if m > 1e-9: return np.arccos(np.clip(np.dot(ba, bc)/m, -1.0, 1.0)) / math.pi
            return 0.5
        arm_feats = [_get_elbow_angle("right"), _get_elbow_angle("left")]

    # 특징 통합 (가중치 부여 전략)
    # 1. Velocity(모션 궤적)를 3번 중첩 (움직임 방향성)
    # 2. Y-Relative to Nose (높이 정보)를 3번 더 추가 (얼굴 vs 가슴 구분)
    # 3. X-Relative to Nose (좌우 정보)를 3번 더 추가 (코 옆[좋다] vs 볼/입 옆[맛있다] 구분)
    y_heights = [rel_pos[7], rel_pos[10]] * 3 
    x_widths = [rel_pos[6], rel_pos[9]] * 3
    combined = right_feats + left_feats + rel_pos + (velocity * 3) + y_heights + x_widths + arm_feats
    
    # 양손 모두 감지되지 않은 경우 무시
    if right_feats[-1] == 0.0 and left_feats[-1] == 0.0:
        return None
    return combined


# ── 데이터 증강 (Augmentation) ────────────────────────────────────────────
import random

def augment_landmarks(landmarks: list, n: int = 8) -> list[list]:
    """
    MediaPipe 손 랜드마크 1세트 -> 증강된 N세트 자동 생성.
    개인별 차이에 강건하도록 회전, 스케일, 노이즈를 적용합니다.
    """
    def _rotate_xy(pts, angle_deg):
        rad = math.radians(angle_deg)
        cos_a, sin_a = math.cos(rad), math.sin(rad)
        return [
            {**lm,
             "x": lm["x"] * cos_a - lm["y"] * sin_a,
             "y": lm["x"] * sin_a + lm["y"] * cos_a}
            for lm in pts
        ]

    def _scale(pts, factor):
        return [{**lm,
                 "x": lm["x"] * factor,
                 "y": lm["y"] * factor,
                 "z": lm.get("z", 0) * factor} for lm in pts]

    def _jitter(pts, sigma_xy=0.01, sigma_z=0.005):
        return [
            {**lm,
             "x": lm["x"] + random.gauss(0, sigma_xy),
             "y": lm["y"] + random.gauss(0, sigma_xy),
             "z": lm.get("z", 0) + random.gauss(0, sigma_z)}
            for lm in pts
        ]

    if not landmarks or len(landmarks) < 21:
        return []

    # 손목을 원점으로 이동 후 변형 → 복원
    wrist = landmarks[0]
    centered = [
        {"x": lm["x"] - wrist["x"],
         "y": lm["y"] - wrist["y"],
         "z": lm.get("z", 0) - wrist.get("z", 0)}
        for lm in landmarks
    ]

    augmented = []
    for _ in range(n):
        pts = list(centered)
        pts = _rotate_xy(pts, random.uniform(-20, 20)) # 회전 범위 확대
        pts = _scale(pts, random.uniform(0.75, 1.25)) # 스케일 범위 확대
        pts = _jitter(pts, sigma_xy=0.02)             # 노이즈 범위 확대
        # 손목 위치 복원
        pts = [{"x": p["x"] + wrist["x"],
                "y": p["y"] + wrist["y"],
                "z": p["z"] + wrist.get("z", 0)} for p in pts]
        augmented.append(pts)

    return augmented

