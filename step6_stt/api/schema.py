"""
schema.py - 6단계: STT + RAG 수어 검색 공유 스키마
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
3대 약속 #1 — 이 파일이 JSON 데이터 모양의 유일한 기준입니다.
  · 변수명 임의 변경 금지
  · 필드 추가 시 팀 합의 후 이 파일 먼저 수정

WebSocket 프로토콜:
  클라이언트 → 서버:
    Frame-1 (text/JSON) : AudioMeta
    Frame-2 (binary)    : WebM Opus 오디오 바이트
  서버 → 클라이언트:
    Frame-1 (text/JSON) : STTResponse
"""

from pydantic import BaseModel, Field
from typing import List, Optional


# ══════════════════════════════════════════════════════════════
# 클라이언트 → 서버
# ══════════════════════════════════════════════════════════════

class AudioMeta(BaseModel):
    """
    오디오 청크 전송 직전에 보내는 메타데이터 (JSON 텍스트 프레임).
    이 메시지 바로 다음 프레임이 바이너리 오디오입니다.
    """
    session_id:   str   = Field(..., description="세션 고유 ID")
    chunk_id:     int   = Field(..., description="청크 순번 (단조 증가)")
    timestamp_ms: float = Field(..., description="클라이언트 타임스탬프 (ms)")
    source:       str   = Field(default="system",
                                description="'system' | 'mic'  — 오디오 소스")
    duration_ms:  float = Field(default=2000.0,
                                description="청크 길이 (ms)")


# ══════════════════════════════════════════════════════════════
# 서버 → 클라이언트
# ══════════════════════════════════════════════════════════════

class SignTerm(BaseModel):
    """
    RAG 검색으로 찾은 수어 단어 항목.
    1단계 팀이 KCISA API 데이터를 FAISS 에 넣으면 이 구조로 반환됩니다.
    """
    word:        str            = Field(...,        description="수어 단어")
    sign_id:     Optional[str]  = Field(default=None, description="KCISA 수어 사전 ID")
    description: Optional[str]  = Field(default=None, description="수어 동작 설명")
    video_url:   Optional[str]  = Field(default=None, description="수어 교육 영상 URL")
    emotion_tag: Optional[str]  = Field(default=None,
                                        description="감정 태그 (따뜻함 / 격려 / 중립 …)")
    confidence:  float          = Field(default=1.0, ge=0.0, le=1.0,
                                        description="검색 신뢰도")


class STTResponse(BaseModel):
    """
    서버가 한 청크 처리 후 클라이언트에 돌려주는 통합 응답.
    STT 결과 + RAG 수어 검색 결과를 하나의 메시지로 묶습니다.
    """
    # ── STT 결과 ──────────────────────────────────────────────
    session_id:    str           = Field(...,         description="세션 ID")
    chunk_id:      int           = Field(...,         description="처리한 청크 순번")
    text:          str           = Field(default="",  description="Whisper 인식 텍스트")
    confidence:    float         = Field(default=1.0, ge=0.0, le=1.0)
    language:      str           = Field(default="ko")
    is_final:      bool          = Field(default=True)

    # ── RAG 수어 검색 결과 ─────────────────────────────────────
    sign_terms:    List[SignTerm] = Field(default_factory=list,
                                         description="검색된 수어 단어 목록")
    emotion_weight: float        = Field(default=0.5, ge=0.0, le=1.0,
                                         description="감정 가중치 (아바타 표현 강도)")
    rag_status:    str           = Field(default="ok",
                                         description="'ok' | 'no_result' | 'rag_pending'")

    # ── 처리 메타 ──────────────────────────────────────────────
    process_ms:    float         = Field(default=0.0, description="서버 처리 시간 (ms)")
    status:        str           = Field(default="ok", description="'ok' | 'error'")
    error_msg:     Optional[str] = Field(default=None)
