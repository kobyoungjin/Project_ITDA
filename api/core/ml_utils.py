import math
from typing import Optional


def extract_ksl_features(right_landmarks: Optional[list], left_landmarks: Optional[list]) -> Optional[list]:
    """
    양손의 MediaPipe 랜드마크 (각 21개) -> 35차원 통합 특징 벡터
    - 오른손 (16차원): 15개 각도 + 1개 스케일
    - 왼손 (16차원): 15개 각도 + 1개 스케일
    - 양손 상대 위치 (3차원): 오른손 손목 기준 왼손 손목의 (dx, dy, dz)
    """
    
    def _extract_single_hand_features(landmarks: Optional[list]) -> list[float]:
        # 손이 감지되지 않은 경우 0으로 채움 (16차원)
        if not landmarks or len(landmarks) < 21:
            return [0.0] * 16

        # 손목을 원점으로 평면 이동
        wrist = landmarks[0]
        pts = [(lm["x"] - wrist["x"], lm["y"] - wrist["y"], 
                lm.get("z", 0) - wrist.get("z", 0)) for lm in landmarks]

        # 중지 끝까지의 3D 거리를 1.0으로 정규화
        mid_tip = pts[12]
        scale = math.sqrt(mid_tip[0]**2 + mid_tip[1]**2 + mid_tip[2]**2)
        if scale < 1e-6:
            return [0.0] * 16
        
        pts = [(p[0]/scale, p[1]/scale, p[2]/scale) for p in pts]

        def angle(a, b, c):
            ba = (a[0]-b[0], a[1]-b[1], a[2]-b[2])
            bc = (c[0]-b[0], c[1]-b[1], c[2]-b[2])
            dot = ba[0]*bc[0] + ba[1]*bc[1] + ba[2]*bc[2]
            m = math.sqrt(ba[0]**2 + ba[1]**2 + ba[2]**2) * math.sqrt(bc[0]**2 + bc[1]**2 + bc[2]**2)
            return math.acos(max(-1.0, min(1.0, dot/m))) if m > 1e-9 else 0.0

        fingers = [[1,2,3,4], [5,6,7,8], [9,10,11,12], [13,14,15,16], [17,18,19,20]]
        feats = []
        for f in fingers:
            feats.append(angle(pts[0], pts[f[0]], pts[f[1]]))
            feats.append(angle(pts[f[0]], pts[f[1]], pts[f[2]]))
            feats.append(angle(pts[f[1]], pts[f[2]], pts[f[3]]))
        
        # 마지막 scale 값은 거리 불변성을 위해 1.0으로 고정 (차원수 16 유지)
        feats.append(1.0) 
        return feats

    # 1. 각 손의 특징 추출
    right_feats = _extract_single_hand_features(right_landmarks)
    left_feats = _extract_single_hand_features(left_landmarks)

    # 2. 양손 상대 위치 (오른손 손목 기준 왼손 손목)
    rel_pos = [0.0, 0.0, 0.0]
    if right_landmarks and left_landmarks:
        rw = right_landmarks[0]
        lw = left_landmarks[0]
        def get_scale(lms):
            w = lms[0]
            m = lms[12]
            return math.sqrt((m['x']-w['x'])**2 + (m['y']-w['y'])**2 + (m.get('z',0)-w.get('z',0))**2)
        
        r_scale = get_scale(right_landmarks)
        if r_scale > 1e-6:
            rel_pos = [
                (lw["x"] - rw["x"]) / r_scale,
                (lw["y"] - rw["y"]) / r_scale,
                (lw.get("z", 0) - rw.get("z", 0)) / r_scale
            ]

    # 3. 통합 (35차원: 16 + 16 + 3)
    combined = right_feats + left_feats + rel_pos
    
    # 둘 다 감지 안 된 경우 무시
    if right_feats[-1] == 0.0 and left_feats[-1] == 0.0:
        return None
        
    return combined


# ── 데이터 증강 (Augmentation) ────────────────────────────────────────────
import random

def augment_landmarks(landmarks: list, n: int = 8) -> list[list]:
    """
    MediaPipe 손 랜드마크 1세트 -> 증강된 N세트 자동 생성.
    영상 속 한 명의 데이터만으로도 개인별 손 크기·각도 차이에
    강건한 모델을 만들기 위해 다음 변형을 적용합니다:
      1) XY 미세 2D 회전  (-15도 ~ +15도)
      2) 스케일 변동      (+-15%)
      3) XY 가우시안 노이즈  (sigma = 0.01)
      4) Z축 깊이 노이즈  (sigma = 0.005, 2D 카메라 Z 불확실성 반영)
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
        pts = _rotate_xy(pts, random.uniform(-15, 15))
        pts = _scale(pts, random.uniform(0.85, 1.15))
        pts = _jitter(pts)
        # 손목 위치 복원
        pts = [{"x": p["x"] + wrist["x"],
                "y": p["y"] + wrist["y"],
                "z": p["z"] + wrist.get("z", 0)} for p in pts]
        augmented.append(pts)

    return augmented
