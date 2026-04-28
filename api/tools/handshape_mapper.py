"""
handshape_mapper.py

AI Hub (OpenPose) 키포인트 데이터를 분석하여 22개 표준 수형(KSL) 중 
가장 유사한 수형 ID를 단어별로 매핑합니다.

알고리즘:
1. OpenPose 3D 손 키포인트 → 5개 손가락 flexion 각도 추출
2. 전체 프레임 중 '가장 손가락이 많이 굽혀진' 혹은 '가장 오래 유지되는' 대표 수형 추출
3. generate_handshape_library.py 의 22개 수형 정의값과 각도 거리(L2 norm) 비교
4. 최적 ID 매칭
"""

import json
import math
import numpy as np
from pathlib import Path
from typing import Dict, List

# 라이브러리 정의값 참조 (flexion 각도만 비교)
# generate_handshape_library.py 의 HANDSHAPES 구조와 동일하게 유지
STRAIGHT = [0, 0, 0]
FULL_CURL = [90, 90, 45]
MID_CURL = [45, 60, 30]
TIP_CURL = [10, 90, 60]

# 비교용 표준 수형 각도 맵 (Thumb 제외 4지 flexion 기준)
# Thumb은 구조가 복잡하여 우선 4지(Index~Pinky)의 flexion 합으로 비교
CANONICAL_ANGLES = {
    "주먹": [FULL_CURL, FULL_CURL, FULL_CURL, FULL_CURL],
    "5지": [STRAIGHT, STRAIGHT, STRAIGHT, STRAIGHT],
    "1지": [STRAIGHT, FULL_CURL, FULL_CURL, FULL_CURL],
    "2지": [STRAIGHT, STRAIGHT, FULL_CURL, FULL_CURL],
    "3지": [STRAIGHT, STRAIGHT, STRAIGHT, FULL_CURL],
    "4지": [STRAIGHT, STRAIGHT, STRAIGHT, STRAIGHT], # Thumb 접힘은 별도 체크 필요
    "엄지": [FULL_CURL, FULL_CURL, FULL_CURL, FULL_CURL],
    "새끼": [FULL_CURL, FULL_CURL, FULL_CURL, STRAIGHT],
    "OK": [[45, 30, 20], STRAIGHT, STRAIGHT, STRAIGHT],
    "ㄱ": [STRAIGHT, FULL_CURL, FULL_CURL, FULL_CURL],
    "납작손": [STRAIGHT, STRAIGHT, STRAIGHT, STRAIGHT],
    "갈고리": [[30, 60, 30], [30, 60, 30], [30, 60, 30], [30, 60, 30]],
    "O": [[50, 40, 30], [50, 40, 30], [50, 40, 30], [50, 40, 30]],
}

def get_flexion_angle(p1, p2, p3):
    """세 점 사이의 각도 계산 (v1=p1-p2, v2=p3-p2)"""
    v1 = p1 - p2
    v2 = p3 - p2
    norm = np.linalg.norm(v1) * np.linalg.norm(v2)
    if norm < 1e-6: return 0
    cos = np.dot(v1, v2) / norm
    angle = math.degrees(math.acos(max(-1.0, min(1.0, cos))))
    return 180 - angle # 180이면 완전히 굽힘, 0이면 펴짐

def analyze_hand_kps(kps_flat: List[float]) -> List[List[float]]:
    """OpenPose 21 keypoints → 4개 손가락 (Index~Pinky) flexion [MCP, PIP, DIP] 추출"""
    if not kps_flat or len(kps_flat) < 84: return None
    
    pts = []
    for i in range(21):
        pts.append(np.array([kps_flat[i*4], kps_flat[i*4+1], kps_flat[i*4+2]]))
    
    fingers_angles = []
    # Index(5-8), Middle(9-12), Ring(13-16), Pinky(17-20)
    # MCP: wrist(0)-mcp(5)-pip(6)
    # PIP: mcp(5)-pip(6)-dip(7)
    # DIP: pip(6)-dip(7)-tip(8)
    for start_idx in [5, 9, 13, 17]:
        mcp = get_flexion_angle(pts[0], pts[start_idx], pts[start_idx+1])
        pip = get_flexion_angle(pts[start_idx], pts[start_idx+1], pts[start_idx+2])
        dip = get_flexion_angle(pts[start_idx+1], pts[start_idx+2], pts[start_idx+3])
        fingers_angles.append([mcp, pip, dip])
    
    return fingers_angles

def calculate_distance(angles1, angles2):
    """두 수형 각도 세트 간의 L2 거리 계산"""
    a1 = np.array(angles1).flatten()
    a2 = np.array(angles2).flatten()
    return np.linalg.norm(a1 - a2)

def find_best_match(target_angles: List[List[float]]) -> str:
    """가장 유사한 표준 수형 ID 반환"""
    best_id = "5지"
    min_dist = float('inf')
    
    for shape_id, ref_angles in CANONICAL_ANGLES.items():
        dist = calculate_distance(target_angles, ref_angles)
        if dist < min_dist:
            min_dist = dist
            best_id = shape_id
            
    return best_id

def process_word_dir(keypoint_dir: Path) -> str:
    """한 단어의 폴더 내 모든 프레임을 분석하여 대표 수형 하나를 추출"""
    json_files = sorted(keypoint_dir.glob("*_keypoints.json"))
    if not json_files: return "5지"
    
    all_frame_matches = []
    for jf in json_files:
        with open(jf, encoding="utf-8") as f:
            data = json.load(f)
        people = data.get("people", [])
        if not people: continue
        
        # 주로 오른손 수어이므로 오른손 먼저 체크
        kps = people[0].get("hand_right_keypoints_3d")
        angles = analyze_hand_kps(kps)
        if angles:
            all_frame_matches.append(find_best_match(angles))
            
    if not all_frame_matches: return "5지"
    
    # 최빈값(Mode) 반환
    return max(set(all_frame_matches), key=all_frame_matches.count)

if __name__ == "__main__":
    # 사용 예시 (Batch 처리용)
    # root = Path("C:/data/AI_Hub/keypoints")
    # results = {}
    # for word_dir in root.iterdir():
    #     if word_dir.is_dir():
    #         shape_id = process_word_dir(word_dir)
    #         results[word_dir.name] = shape_id
    print("Handshape Mapper 준비됨. process_word_dir(path) 로 매핑 가능.")
