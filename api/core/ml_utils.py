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
        # 거리 불변성을 위해 원본 landmarks에서 직접 계산한 scale 사용
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
    
    # 둘 다 감지 안 된 경우(스케일이 0인 경우) 무시
    if right_feats[-1] == 0.0 and left_feats[-1] == 0.0:
        return None
        
    return combined
