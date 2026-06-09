import math
from typing import List, Dict

COCO = {
    "NOSE": 0, "NECK": 1,
    "R_SHOULDER": 2, "R_ELBOW": 3, "R_WRIST": 4,
    "L_SHOULDER": 5, "L_ELBOW": 6, "L_WRIST": 7,
    "R_HIP": 8,  "L_HIP": 11,
}

def _get_pt(kp_list, idx):
    if not kp_list or idx >= len(kp_list): return None
    pt = kp_list[idx]
    if len(pt) < 2: return None
    # x, y, conf
    if len(pt) >= 3 and pt[2] < 0.2: return None  # low confidence
    return {"x": pt[0], "y": pt[1]}

def guess_location(wrist_y: float, nose_y: float, neck_y: float, hip_y: float) -> str:
    """Y축 (화면 위가 0, 아래가 커짐) 기반 위치 추정"""
    if wrist_y < nose_y:
        return "얼굴 위"
    elif wrist_y < neck_y:
        return "얼굴 앞"
    elif wrist_y < hip_y:
        return "가슴 앞"
    else:
        return "몸통 아래"

def guess_movement(start_pt: dict, end_pt: dict) -> Dict[str, str]:
    """시작점과 끝점의 변위로 움직임 종류와 방향 추정"""
    dx = end_pt["x"] - start_pt["x"]
    dy = end_pt["y"] - start_pt["y"]
    
    dist = math.hypot(dx, dy)
    
    if dist < 0.05: # 거의 움직이지 않음 (정규화 좌표 기준 임계값)
        return {"type": "정지", "direction": "없음"}
        
    direction = "알 수 없음"
    if abs(dx) > abs(dy):
        direction = "오른쪽" if dx > 0 else "왼쪽"
    else:
        direction = "아래쪽" if dy > 0 else "위쪽"
        
    return {"type": "직선형", "direction": direction}

def analyze_location_movement(frames: List[Dict]) -> Dict:
    """프레임 리스트를 분석하여 위치와 움직임을 반환"""
    if not frames:
        return {
            "location": {"start": "알 수 없음", "end": "알 수 없음"},
            "movement": {"type": "알 수 없음", "direction": "알 수 없음"}
        }
        
    start_frame = frames[0]
    end_frame = frames[-1]
    
    # 오른손(주동손) 기준 분석
    sk_start = start_frame.get("keypoints", {}).get("body", start_frame.get("keypoints", {}).get("pose", []))
    sk_end = end_frame.get("keypoints", {}).get("body", end_frame.get("keypoints", {}).get("pose", []))
    
    start_wrist = _get_pt(sk_start, COCO["R_WRIST"])
    end_wrist = _get_pt(sk_end, COCO["R_WRIST"])
    nose = _get_pt(sk_start, COCO["NOSE"]) or {"y": 0.2}
    neck = _get_pt(sk_start, COCO["NECK"]) or {"y": 0.3}
    hip = _get_pt(sk_start, COCO["R_HIP"]) or {"y": 0.7}
    
    if start_wrist and end_wrist:
        loc_start = guess_location(start_wrist["y"], nose["y"], neck["y"], hip["y"])
        loc_end = guess_location(end_wrist["y"], nose["y"], neck["y"], hip["y"])
        movement = guess_movement(start_wrist, end_wrist)
    else:
        loc_start = "가슴 앞"
        loc_end = "가슴 앞"
        movement = {"type": "알 수 없음", "direction": "알 수 없음"}
        
    return {
        "location": {
            "start": loc_start,
            "end": loc_end
        },
        "movement": movement
    }
