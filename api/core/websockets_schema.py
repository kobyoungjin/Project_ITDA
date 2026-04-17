from pydantic import BaseModel, Field
from typing import List, Dict, Optional

class Vector3(BaseModel):
    x: float
    y: float
    z: float

class HandData(BaseModel):
    handedness: str
    keypoints: List[Vector3]

class VisionFrame(BaseModel):
    frame_id: int
    session_id: str
    timestamp_ms: float
    fps: float
    hands: List[HandData]
    meta_features: Optional[Dict] = None
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
