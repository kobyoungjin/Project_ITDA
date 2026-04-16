"""
rag_bridge.py - 1단계 RAG 엔진 연동 브릿지
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
3대 약속 #2: /api/ 폴더 안에서만 작업

현재 상태: 스텁(Stub) 구현
  - 키워드 기반 샘플 수어 데이터 반환
  - 1단계 팀이 FAISS + Gemini RAG 완성하면 아래 [1단계 연동 지점] 교체

교체 방법 (1단계 팀용):
  1. `from step1_rag.search_engine import faiss_search` 추가
  2. `_stub_search()` 호출 부분을 `faiss_search(text)` 로 교체
  3. 반환값을 List[SignTerm] 형태로 맞추면 끝
"""

import logging
from typing import List

from schema import SignTerm, STTResponse

logger = logging.getLogger("itda.rag_bridge")

# ── [1단계 연동 지점] ────────────────────────────────────────
# 1단계 완성 후 아래 주석 해제 + _stub_search 대신 faiss_search 사용
#
# from step1_rag.search_engine import faiss_search
# async def search_sign_language(session_id: str, text: str) -> tuple[List[SignTerm], float]:
#     results = await faiss_search(text)          # FAISS 벡터 검색
#     terms   = [SignTerm(**r) for r in results]
#     emotion = _calc_emotion_weight(terms)
#     return terms, emotion
# ─────────────────────────────────────────────────────────────

# ── 샘플 수어 사전 (스텁용) ─────────────────────────────────
_SIGN_DICT: dict[str, SignTerm] = {
    "안녕": SignTerm(
        word="안녕하세요",
        sign_id="KSL-0001",
        description="오른손을 이마 옆에서 앞으로 내밀며 인사합니다.",
        emotion_tag="따뜻함",
        confidence=0.95,
    ),
    "감사": SignTerm(
        word="감사합니다",
        sign_id="KSL-0002",
        description="양손을 가슴 앞에서 앞으로 내밀며 고마움을 표현합니다.",
        emotion_tag="따뜻함",
        confidence=0.93,
    ),
    "사랑": SignTerm(
        word="사랑해요",
        sign_id="KSL-0003",
        description="오른손 주먹을 쥐어 가슴에 가볍게 두드립니다.",
        emotion_tag="온기",
        confidence=0.98,
    ),
    "도움": SignTerm(
        word="도와주세요",
        sign_id="KSL-0004",
        description="한 손을 펼쳐 다른 손바닥 위에 올리고 위아래로 움직입니다.",
        emotion_tag="격려",
        confidence=0.88,
    ),
    "이해": SignTerm(
        word="이해했어요",
        sign_id="KSL-0005",
        description="검지손가락을 관자놀이에 대고 가볍게 두드립니다.",
        emotion_tag="중립",
        confidence=0.85,
    ),
    "맞아": SignTerm(
        word="맞아요",
        sign_id="KSL-0006",
        description="양손 검지를 세워 서로 마주치게 합니다.",
        emotion_tag="동의",
        confidence=0.87,
    ),
    "어려": SignTerm(
        word="어렵다",
        sign_id="KSL-0007",
        description="양 손등을 위로 향하게 하여 서로 비틉니다.",
        emotion_tag="고민",
        confidence=0.82,
    ),
    "쉬워": SignTerm(
        word="쉬워요",
        sign_id="KSL-0008",
        description="손을 펼쳐 가볍게 아래로 내립니다.",
        emotion_tag="중립",
        confidence=0.83,
    ),
    "좋아": SignTerm(
        word="좋아요",
        sign_id="KSL-0009",
        description="엄지손가락을 위로 세웁니다.",
        emotion_tag="긍정",
        confidence=0.96,
    ),
    "잠깐": SignTerm(
        word="잠깐만요",
        sign_id="KSL-0010",
        description="손을 앞으로 펼쳐 멈추는 동작을 합니다.",
        emotion_tag="중립",
        confidence=0.80,
    ),
}

# 감정 태그별 가중치
_EMOTION_WEIGHTS: dict[str, float] = {
    "따뜻함": 0.90,
    "온기":   0.95,
    "격려":   0.85,
    "긍정":   0.80,
    "동의":   0.70,
    "중립":   0.50,
    "고민":   0.45,
}


async def search_sign_language(
    session_id: str,
    text: str,
) -> tuple[List[SignTerm], float]:
    """
    텍스트에서 수어 단어를 검색합니다.

    Returns:
        (sign_terms, emotion_weight)
        sign_terms     : 찾은 수어 단어 목록 (SignTerm 리스트)
        emotion_weight : 감정 가중치 0.0~1.0 (3D 아바타 표정 강도에 사용)
    """
    logger.info(f"[RAG Bridge] 검색: '{text[:30]}' (sess={session_id})")

    found: List[SignTerm] = []
    for keyword, term in _SIGN_DICT.items():
        if keyword in text:
            found.append(term)

    # 결과 없을 때 — 인식 텍스트 앞 8자를 임시 단어로 반환
    if not found and text.strip():
        found.append(SignTerm(
            word=text.strip()[:8],
            description=f"'{text.strip()[:8]}' — 1단계 RAG 연동 후 정밀 검색 예정",
            confidence=0.30,
            emotion_tag="중립",
        ))

    emotion = _calc_emotion_weight(found)
    logger.info(f"[RAG Bridge] 결과 {len(found)}개, 감정 가중치={emotion:.2f}")
    return found, emotion


def _calc_emotion_weight(terms: List[SignTerm]) -> float:
    """찾은 수어들의 감정 가중치 평균을 계산합니다."""
    if not terms:
        return 0.3
    weights = [_EMOTION_WEIGHTS.get(t.emotion_tag or "중립", 0.5) for t in terms]
    return round(sum(weights) / len(weights), 2)
