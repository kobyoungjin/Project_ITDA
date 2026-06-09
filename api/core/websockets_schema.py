from pydantic import BaseModel, Field
from typing import List, Dict, Optional, Any

class Vector3(BaseModel):
    x: float
    y: float
    z: float

class HandData(BaseModel):
    handedness: str
    keypoints: List[Vector3]
    # [P0] Handshape 분류기용: 원본 픽셀 좌표에서 손목 기준으로 정규화되었는지 여부
    normalized: bool = False


class HandAnalysis(BaseModel):
    """[P0] handshape_analyzer.analyze_hand() 반환값을 그대로 담는 응답용 모델."""
    handedness: str
    handshape: str  # FIST | PALM | POINT | V | L | OK | UNKNOWN
    bends: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    orientation: Dict[str, Any] = Field(default_factory=dict)


class PoseLandmark(BaseModel):
    x: float
    y: float
    z: float = 0.0
    visibility: float = 1.0


class PoseData(BaseModel):
    """[P0] 프론트에서 넘어오는 상체 Pose 좌표. 키는 pose_analyzer.POSE 라벨을 따름."""
    landmarks: Dict[str, PoseLandmark] = Field(default_factory=dict)


class PoseAnalysis(BaseModel):
    """[P0] pose_analyzer.analyze_pose() 반환값."""
    elbow_bend_L: float
    elbow_bend_R: float
    wrist_region_L: str
    wrist_region_R: str
    arm_dir_L: str
    arm_dir_R: str
    shoulder_raise: float
    arms_crossed: bool
    summary: str

class VisionFrame(BaseModel):
    frame_id: int
    session_id: str
    timestamp_ms: float
    fps: float
    hands: List[HandData]
    meta_features: Optional[Dict] = None
    # [P0] 상체 Pose (어깨·팔꿈치·손목·엉덩이) — 수어 위치 해석용
    pose: Optional[PoseData] = None
    # [Cyborg Alpha] 센서 퓨전 전용 필드 추가
    detection_data: Optional[Dict] = {
        "visual_confidence": 0.0,
        "audio_confidence": 0.0,
        "detected_area_m2": 0.0
    }

class VisionAck(BaseModel):
    frame_id: int
    status: str
    message: str
    rag_result: Optional[Dict] = None
    # [Cyborg Alpha] 경고 레벨 및 NMS 가이드 추가
    alert_level: str = "Low" # Low, Medium, High
    nms_guide: Optional[Dict] = {
        "eyebrows": "neutral",
        "mouth": "pa",
        "confidence_score": 0.0
    }
    # [P0] Handshape 분석 결과(손별 최대 2개) - 프론트 디버그 HUD 및 교육용 피드백에 활용
    hand_analyses: Optional[List[HandAnalysis]] = None
    # [P0] Pose 분석 결과 - 팔꿈치 각도/손목 구역/어깨 상승도 등 상체 정보
    pose_analysis: Optional[PoseAnalysis] = None
