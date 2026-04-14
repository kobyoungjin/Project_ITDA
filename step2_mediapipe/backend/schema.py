"""
schema.py - 2단계: 수어 좌표 데이터 스키마 정의

1단계(RAG 백엔드)와 통합 시 이 스키마를 공유합니다.
모든 WebSocket 메시지는 이 형식을 따릅니다.
"""
from pydantic import BaseModel, Field
from typing import List, Optional


# ─────────────────────────────────────────────────────────────
# 랜드마크 단일 좌표               (MediaPipe 정규화 좌표)
# x, y : 0.0 ~ 1.0 (화면 비율)
# z    : 손목 기준 상대 깊이 (단위 없음)
# ─────────────────────────────────────────────────────────────
class Landmark(BaseModel):
    x: float = Field(..., ge=0.0, le=1.0, description="정규화된 X 좌표 (0~1)")
    y: float = Field(..., ge=0.0, le=1.0, description="정규화된 Y 좌표 (0~1)")
    z: float = Field(..., description="손목 기준 상대 깊이")


# ─────────────────────────────────────────────────────────────
# 핵심 관절 11개 구성
#  idx | 이름
#   0  | WRIST (손목)
#   3  | INDEX_FINGER_MCP  (검지 손바닥 관절)
#   4  | INDEX_FINGER_TIP  (검지 끝)
#   6  | MIDDLE_FINGER_MCP (중지 손바닥 관절)
#   8  | MIDDLE_FINGER_TIP (중지 끝)
#  10  | RING_FINGER_MCP   (약지 손바닥 관절)
#  12  | RING_FINGER_TIP   (약지 끝)
#  14  | PINKY_MCP         (새끼 손바닥 관절)
#  16  | PINKY_TIP         (새끼 끝)
#  18  | THUMB_MCP         (엄지 손바닥 관절)
#  20  | THUMB_TIP         (엄지 끝)
# ─────────────────────────────────────────────────────────────
ESSENTIAL_INDICES = [0, 3, 4, 6, 8, 10, 12, 14, 16, 18, 20]

LANDMARK_NAMES = {
    0:  "WRIST",
    3:  "INDEX_MCP",
    4:  "INDEX_TIP",
    6:  "MIDDLE_MCP",
    8:  "MIDDLE_TIP",
    10: "RING_MCP",
    12: "RING_TIP",
    14: "PINKY_MCP",
    16: "PINKY_TIP",
    18: "THUMB_MCP",
    20: "THUMB_TIP",
}


class HandKeypoints(BaseModel):
    """단일 손의 핵심 11개 관절 좌표 (추출·정규화 완료)"""
    handedness: str = Field(..., description="'Left' 또는 'Right'")
    # 인덱스 순서를 ESSENTIAL_INDICES 순서로 고정
    keypoints: List[Landmark] = Field(
        ..., min_length=11, max_length=11,
        description="핵심 11개 관절 좌표 (ESSENTIAL_INDICES 순서)"
    )
    # 원본 21개 좌표 (옵션: 학습 데이터 수집 시 활용)
    full_landmarks: Optional[List[Landmark]] = Field(
        default=None,
        description="원본 21개 관절 좌표 (선택적 포함)"
    )


class VisionFrame(BaseModel):
    """
    WebSocket으로 전송되는 프레임 단위 메시지.

    ─ 클라이언트(브라우저) → 서버 방향 ─
    1단계 RAG 서버의 /ws/vision 엔드포인트가 이 포맷을 수신합니다.
    """
    frame_id: int = Field(..., description="프레임 일련번호 (클라이언트 단조 증가)")
    session_id: str = Field(..., description="세션 고유 ID")
    timestamp_ms: float = Field(..., description="클라이언트 타임스탬프 (ms)")
    fps: float = Field(..., ge=0, description="현재 클라이언트 측 FPS")
    hands: List[HandKeypoints] = Field(
        ..., max_length=2,
        description="감지된 손 목록 (최대 2개)"
    )


class VisionAck(BaseModel):
    """
    서버 → 클라이언트 응답 메시지.
    1단계 RAG 엔진에서 검색 결과가 있을 경우 함께 실어 보낼 수 있습니다.
    """
    frame_id: int
    status: str = Field(default="ok", description="'ok' | 'error'")
    # 1단계 RAG 결과 슬롯 (1단계 통합 후 채워짐)
    rag_result: Optional[dict] = Field(
        default=None,
        description="[1단계 연동용] RAG 검색 결과"
    )
    message: Optional[str] = None
