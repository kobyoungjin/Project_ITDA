import math
from typing import Optional


def extract_ksl_features(right_landmarks: Optional[list], left_landmarks: Optional[list], pose_landmarks: Optional[dict] = None) -> Optional[list]:
    """
    양손의 MediaPipe 랜드마크 + 팔 관절 -> 37차원 통합 특징 벡터
    - 오른손 (16차원): 15개 각도 + 1개 스케일
    - 왼손 (16차원): 15개 각도 + 1개 스케일
    - 양손 상대 위치 (3차원): 오른손 손목 기준 왼손 손목의 (dx, dy, dz)
    - 팔 관절 (2차원): 좌우 팔꿈치 굴곡 각도 (도 단위, 0~180 -> 0~1 정규화)
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
            # 0~PI 범위를 0~1로 정규화하여 다른 특징들과 스케일을 맞춤
            feats.append(angle(pts[0], pts[f[0]], pts[f[1]]) / math.pi)
            feats.append(angle(pts[f[0]], pts[f[1]], pts[f[2]]) / math.pi)
            feats.append(angle(pts[f[1]], pts[f[2]], pts[f[3]]) / math.pi)
        
        # 마지막 scale 값은 존재 여부 플래그로 활용 (1.0=감지됨)
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
            # 양손 거리가 너무 멀어질 경우 특징값이 튀지 않도록 tanh로 -1~1 범위로 압축
            # 보통 손 크기의 5~10배 정도가 최대 범위이므로 0.2를 곱해 완만하게 만듦
            rel_pos = [
                math.tanh((lw["x"] - rw["x"]) / (r_scale * 5)),
                math.tanh((lw["y"] - rw["y"]) / (r_scale * 5)),
                math.tanh((lw.get("z", 0) - rw.get("z", 0)) / (r_scale * 5))
            ]

    # 3. 팔 관절 특징 (2차원: 팔꿈치 각도)
    arm_feats = [0.5, 0.5] # 기본값 (직각 정도)
    if pose_landmarks:
        # pose_landmarks 는 {'landmarks': {'left_shoulder':...}} 형태라고 가정 (pose_analyzer 규격)
        lms = pose_landmarks.get("landmarks", {})
        
        def _get_elbow_angle(side):
            s = lms.get(f"{side}_shoulder")
            e = lms.get(f"{side}_elbow")
            w = lms.get(f"{side}_wrist")
            if s and e and w:
                # 벡터 계산
                ba = (s['x']-e['x'], s['y']-e['y'], (s.get('z',0)-e.get('z',0)))
                bc = (w['x']-e['x'], w['y']-e['y'], (w.get('z',0)-e.get('z',0)))
                dot = ba[0]*bc[0] + ba[1]*bc[1] + ba[2]*bc[2]
                m = math.sqrt(ba[0]**2 + ba[1]**2 + ba[2]**2) * math.sqrt(bc[0]**2 + bc[1]**2 + bc[2]**2)
                if m > 1e-9:
                    ang = math.acos(max(-1.0, min(1.0, dot/m)))
                    return ang / math.pi # 0~1 정규화 (0=접힘, 1=펴짐)
            return 0.5

        arm_feats = [_get_elbow_angle("right"), _get_elbow_angle("left")]

    # 4. 통합 (37차원: 16 + 16 + 3 + 2)
    combined = right_feats + left_feats + rel_pos + arm_feats
    
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

