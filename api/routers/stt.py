"""
stt.py ─ [P3] 6단계 STT 라우터를 메인 API(포트 8000)로 편입하는 어댑터

step6_stt/api/ 는 독립 실행용으로 설계되어 flat import (`from rag_bridge import ...`)
를 사용합니다. 이 파일은:
  1) step6_stt/api/ 를 sys.path 에 추가해 해당 모듈을 임포트 가능하게 하고
  2) rag_bridge 의 스텁 검색을 api.services.rag_engine 로 교체(단일 지식베이스 사용)
  3) faster-whisper 미설치 환경에서도 서버 전체가 기동되도록 방어적 로드

`main.py` 에서 `from api.routers import stt` → `app.include_router(stt.router)` 로 사용.
"""

from __future__ import annotations

import logging
import os
import sys

from fastapi import APIRouter

logger = logging.getLogger("itda.stt.adapter")

# step6_stt/api 를 sys.path 에 추가
_STT_DIR = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "step6_stt", "api"
))
if _STT_DIR not in sys.path and os.path.isdir(_STT_DIR):
    sys.path.insert(0, _STT_DIR)

router = APIRouter()

try:
    # stt_router 는 이미 prefix="/api" 로 선언되어 있음 → 메인 include 시 prefix 중첩 주의
    from stt_router import stt_router  # type: ignore
    import rag_bridge                   # type: ignore
    from schema import SignTerm          # type: ignore

    # ── rag_bridge.search_sign_language 를 메인 RAG 엔진으로 교체 ─────
    # 스텁 10단어 사전 대신 FAISS 20K+ 지식베이스 활용
    from api.services.rag_engine import rag_engine

    async def _unified_search(session_id: str, text: str):
        data = rag_engine.retrieve_with_emotion(text)
        term = SignTerm(
            word=data.get("keyword", text[:8]),
            description=data.get("warm_translation", ""),
            video_url=data.get("video_url") or None,
            emotion_tag=(data.get("emotions") or ["중립"])[0],
            confidence=0.85,
        )
        # 감정 가중치 계산은 rag_bridge 의 내부 함수 재사용
        emotion = rag_bridge._calc_emotion_weight([term])
        return [term], emotion

    rag_bridge.search_sign_language = _unified_search
    router = stt_router
    STT_LOADED = True
    logger.info("[STT Adapter] step6_stt 라우터 로드 완료 (rag_engine 바인딩)")

except Exception as e:
    STT_LOADED = False
    logger.warning(f"[STT Adapter] STT 모듈 로드 실패 (fallback): {e}")

    @router.get("/status/stt")
    async def _stt_disabled():
        return {
            "model_loaded": False,
            "model_type": "disabled",
            "reason": str(e),
            "hint": "pip install faster-whisper 후 서버 재시작 필요",
        }
