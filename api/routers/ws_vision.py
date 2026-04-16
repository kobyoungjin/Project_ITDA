from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import json
import logging
import time

from api.core.websockets_schema import VisionFrame, VisionAck
from api.services.rag_engine import rag_engine

logger = logging.getLogger("itda.vision.router")
router = APIRouter()

class ConnectionManager:
    def __init__(self):
        self.active: dict[str, WebSocket] = {}

    async def connect(self, session_id: str, ws: WebSocket):
        self.active[session_id] = ws

    def disconnect(self, session_id: str):
        self.active.pop(session_id, None)

    async def send_ack(self, session_id: str, ack: VisionAck):
        ws = self.active.get(session_id)
        if ws:
            await ws.send_text(ack.model_dump_json())

manager = ConnectionManager()

@router.websocket("/ws/vision")
async def vision_socket(ws: WebSocket):
    await ws.accept()
    session_id: str = f"anon_{int(time.time())}"
    try:
        raw_first = await ws.receive_text()
        data = json.loads(raw_first)
        session_id = data.get("session_id", session_id)
        manager.active[session_id] = ws
        await _handle(session_id, data)

        while True:
            raw = await ws.receive_text()
            await _handle(session_id, json.loads(raw))

    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(session_id)

async def _handle(session_id: str, raw: dict):
    recv_t = time.perf_counter()
    try:
        frame = VisionFrame(**raw)
    except Exception as e:
        ack = VisionAck(frame_id=raw.get("frame_id", -1), status="error", message=str(e))
        await manager.send_ack(session_id, ack)
        return

    # ──────── [3단계: 하이브리드 번역 파이프라인] ────────

    # Track 1: 기기 내 SLM (Ollama) 초고속 1차 예측 진행 (Latency Hiding)
    from api.services.slm_agent import slm_agent
    fast_pred = await slm_agent.predict_fast(raw)
    
    # 1차 예측 결과(Draft) 중간 송출 -> 프론트 UI 즉시 표시
    await manager.send_ack(
        session_id,
        VisionAck(frame_id=frame.frame_id, status="processing", rag_result={"type": "draft", "text": fast_pred}, message="1차 예측 완료"),
    )

    # Track 2: 1단계 RAG 데이터베이스 스캔
    # (실제 구동 시: fast_pred에서 키워드를 추출하여 쿼리로 사용)
    search_keyword = "안녕하세요" 
    rag_data = rag_engine.retrieve_with_emotion(search_keyword)
    
    # Track 3: 1차 예측 + RAG 문맥 합성을 통한 최종 온기 보정
    final_text = await slm_agent.predict_with_rag(fast_pred, rag_data)
    
    rag_result = {
        "type": "final",
        "text": final_text,
        "emotions": rag_data.get('emotions', []),
        "video_url": rag_data.get('video_url', '')
    }

    ms = (time.perf_counter() - recv_t) * 1000
    # 최종 보정 응답 송출 -> 프론트 UI 텍스트 완성
    await manager.send_ack(
        session_id,
        VisionAck(frame_id=frame.frame_id, status="ok", rag_result=rag_result, message=f"최종 RAG 융합 ({ms:.1f}ms)"),
    )
