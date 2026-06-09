"""
stt.py ─ STT 상태 엔드포인트

STT 엔진(step6_stt)은 현재 repo에 포함되어 있지 않아 비활성 상태입니다.
이 라우터는 프론트엔드가 STT 가용 여부를 조회할 수 있도록 상태만 노출합니다.
step6_stt 모듈을 추가하면 이 어댑터를 다시 작성해 연동할 수 있습니다.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/status/stt")
async def stt_status():
    """STT 엔진 상태 조회. 현재 step6_stt 모듈 미포함으로 비활성."""
    return {
        "model_loaded": False,
        "model_type": "disabled",
        "reason": "STT 모듈(step6_stt)이 repo에 포함되어 있지 않습니다.",
        "hint": "step6_stt 모듈 추가 후 STT 어댑터를 재작성하세요.",
    }
