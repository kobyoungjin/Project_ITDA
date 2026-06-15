import math
import numpy as np
from typing import Optional


# 오른손 11개 핵심 랜드마크 인덱스 (× xyz = 33차원)
# 엄지: MCP(2), IP(3), Tip(4)  /  검지: MCP(5), Tip(8)
# 중지: MCP(9), Tip(12)        /  약지: MCP(13), Tip(16)
# 소지: MCP(17), Tip(20)
_HAND_KEY_IDXS = [2, 3, 4, 5, 8, 9, 12, 13, 16, 17, 20]


def _extract_key_positions(landmarks: Optional[list]) -> list:
    """오른손 11개 핵심 랜드마크 (x,y,z) — 손목 기준 정규화 → 33차원. 미감지 시 0."""
    if not landmarks or len(landmarks) < 21:
        return [0.0] * 33
    wrist = landmarks[0]
    ref   = landmarks[9]  # 중지 MCP → 스케일 기준
    scale = math.sqrt((wrist['x']-ref['x'])**2 + (wrist['y']-ref['y'])**2
                      + (wrist.get('z',0)-ref.get('z',0))**2)
    if scale < 1e-6:
        scale = 1.0
    out = []
    for idx in _HAND_KEY_IDXS:
        lm = landmarks[idx]
        out.extend([
            (lm['x']         - wrist['x'])         / scale,
            (lm['y']         - wrist['y'])         / scale,
            (lm.get('z', 0)  - wrist.get('z', 0)) / scale,
        ])
    return out  # 11 × 3 = 33


def extract_ksl_features(right_landmarks: Optional[list], left_landmarks: Optional[list], pose_landmarks: Optional[dict] = None) -> Optional[list]:
    """
    양손 MediaPipe 랜드마크 + 팔 관절 → 76차원 특징 벡터
    - 오른손 각도    (16): 관절 각도 15 + 스케일 플래그 1
    - 왼손  각도    (16): 관절 각도 15 + 스케일 플래그 1
    - 상대 위치     ( 9): 어깨 기준 손목 위치 + 손목 간 거리
    - 오른손 키포인트(33): 11개 핵심 랜드마크 × (x,y,z) 정규화
    - 팔꿈치 각도   ( 2): 좌우 팔꿈치 굴곡
    합계: 16+16+9+33+2 = 76
    """
    
    def _extract_single_hand_features(landmarks: Optional[list]) -> list[float]:
        # 손이 감지되지 않은 경우 0으로 채움 (16차원)
        if not landmarks or len(landmarks) < 21:
            return [0.0] * 16

        # 손목을 원점으로 이동
        wrist = landmarks[0]
        pts = np.array([[lm["x"] - wrist["x"], lm["y"] - wrist["y"], lm.get("z", 0) - wrist.get("z", 0)] for lm in landmarks])

        # 관절 벡터 계산 (HandTalker 방식: 마디 벡터 간의 각도)
        # 0: Wrist, 1-4: Thumb, 5-8: Index, 9-12: Middle, 13-16: Ring, 17-20: Pinky
        # 각 손가락별 마디 벡터들
        parents = [0,1,2,3, 0,5,6,7, 0,9,10,11, 0,13,14,15, 0,17,18,19]
        children = [1,2,3,4, 5,6,7,8, 9,10,11,12, 13,14,15,16, 17,18,19,20]
        
        v1 = pts[parents]
        v2 = pts[children]
        v = v2 - v1 # [20, 3] 벡터들
        
        # 벡터 정규화 (Unit Vector)
        v_norm = np.linalg.norm(v, axis=1)[:, np.newaxis]
        v_unit = np.divide(v, v_norm, out=np.zeros_like(v), where=v_norm > 1e-9)
        
        # 마디 간 각도 계산 (15개 각도)
        # 엄지: (0,1)-(1,2), (1,2)-(2,3), (2,3)-(3,4) ...
        idx1 = [0,1,2, 4,5,6, 8,9,10, 12,13,14, 16,17,18]
        idx2 = [1,2,3, 5,6,7, 9,10,11, 13,14,15, 17,18,19]
        
        dot_product = np.einsum('nt,nt->n', v_unit[idx1], v_unit[idx2])
        angles = np.arccos(np.clip(dot_product, -1.0, 1.0)) / np.pi # 0~1 정규화
        
        feats = angles.tolist()
        # 마지막 scale 값은 존재 여부 플래그 (1.0=감지됨)
        feats.append(1.0) 
        return feats

    # 1. 각 손의 특징 추출
    right_feats = _extract_single_hand_features(right_landmarks)
    left_feats = _extract_single_hand_features(left_landmarks)

    # 2. 상대 위치 특징 추출 (Wrist relative to shoulders & Wrist to Wrist)
    # [개선] HandTalker 처럼 전신 맥락을 반영하기 위해 어깨 기준 손목 위치 추가
    rel_pos = [0.0] * 9 # [rw-rs(3), lw-ls(3), rw-lw(3)]
    
    if pose_landmarks:
        lms = pose_landmarks.get("landmarks", {})
        rs = lms.get("right_shoulder")
        ls = lms.get("left_shoulder")
        
        # 정규화 기준: 어깨 너비 (영상의 크기에 독립적)
        shoulder_width = 0.2 # 기본값
        if rs and ls:
            shoulder_width = math.sqrt((rs['x']-ls['x'])**2 + (rs['y']-ls['y'])**2)
        
        if shoulder_width < 0.01: shoulder_width = 0.2

        if rs and right_landmarks:
            rw = right_landmarks[0]
            rel_pos[0] = math.tanh((rw["x"] - rs["x"]) / shoulder_width)
            rel_pos[1] = math.tanh((rw["y"] - rs["y"]) / shoulder_width)
            rel_pos[2] = math.tanh((rw.get("z", 0) - rs.get("z", 0)) / shoulder_width)
            
        if ls and left_landmarks:
            lw = left_landmarks[0]
            rel_pos[3] = math.tanh((lw["x"] - ls["x"]) / shoulder_width)
            rel_pos[4] = math.tanh((lw["y"] - ls["y"]) / shoulder_width)
            rel_pos[5] = math.tanh((lw.get("z", 0) - ls.get("z", 0)) / shoulder_width)

    if right_landmarks and left_landmarks:
        rw = right_landmarks[0]
        lw = left_landmarks[0]
        # 양손 간 상대 위치
        dist = math.sqrt((rw['x']-lw['x'])**2 + (rw['y']-lw['y'])**2)
        rel_pos[6] = math.tanh((lw["x"] - rw["x"]) / 0.5)
        rel_pos[7] = math.tanh((lw["y"] - rw["y"]) / 0.5)
        rel_pos[8] = math.tanh((lw.get("z", 0) - rw.get("z", 0)) / 0.5)

    # 3. 팔 관절 특징 (2차원: 팔꿈치 각도)
    arm_feats = [0.5, 0.5]
    if pose_landmarks:
        lms = pose_landmarks.get("landmarks", {})
        def _get_elbow_angle(side):
            s = lms.get(f"{side}_shoulder")
            e = lms.get(f"{side}_elbow")
            w = lms.get(f"{side}_wrist")
            if s and e and w:
                ba = np.array([s['x']-e['x'], s['y']-e['y'], (s.get('z',0)-e.get('z',0))])
                bc = np.array([w['x']-e['x'], w['y']-e['y'], (w.get('z',0)-e.get('z',0))])
                dot = np.dot(ba, bc)
                m = np.linalg.norm(ba) * np.linalg.norm(bc)
                if m > 1e-9:
                    return np.arccos(np.clip(dot/m, -1.0, 1.0)) / math.pi
            return 0.5
        arm_feats = [_get_elbow_angle("right"), _get_elbow_angle("left")]

    # 4. 오른손 핵심 랜드마크 (33차원)
    right_key_pos = _extract_key_positions(right_landmarks)

    # 5. 통합 (76차원: 16+16+9+33+2)
    combined = right_feats + left_feats + rel_pos + right_key_pos + arm_feats

    # 둘 다 감지 안 된 경우 무시
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

