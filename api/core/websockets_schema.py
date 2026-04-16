from pydantic import BaseModel, Field
from typing import List, Optional

class Landmark(BaseModel):
    x: float = Field(..., ge=0.0, le=1.0, description="정규화된 X 좌표 (0~1)")
    y: float = Field(..., ge=0.0, le=1.0, description="정규화된 Y 좌표 (0~1)")
    z: float = Field(..., description="손목 기준 상대 깊이")

ESSENTIAL_INDICES = [0, 3, 4, 6, 8, 10, 12, 14, 16, 18, 20]

class HandKeypoints(BaseModel):
    handedness: str = Field(..., description="'Left' 또는 'Right'")
    keypoints: List[Landmark] = Field(..., min_length=11, max_length=11)
    full_landmarks: Optional[List[Landmark]] = Field(default=None)

class VisionFrame(BaseModel):
    frame_id: int = Field(...)
    session_id: str = Field(...)
    timestamp_ms: float = Field(...)
    fps: float = Field(..., ge=0)
    hands: List[HandKeypoints] = Field(..., max_length=2)

class VisionAck(BaseModel):
    frame_id: int
    status: str = Field(default="ok")
    rag_result: Optional[dict] = Field(default=None)
    message: Optional[str] = None
