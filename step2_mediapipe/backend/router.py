"""
router.py - 2단계 Vision WebSocket 라우터 (1단계 통합용)

■ 1단계 팀 사용법
  1단계팀이 만든 FastAPI app/main.py 에 아래 두 줄만 추가:

  from step2_mediapipe.backend.router import vision_router
  app.include_router(vision_router)

이렇게 하면 /ws/vision 엔드포인트가 1단계 서버에 자동으로 등록됩니다.
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import json
import logging
import time

from schema import VisionFrame, VisionAck

logger = logging.getLogger("itda.vision.router")

vision_router = APIRouter(prefix="", tags=["Vision (2단계)"])


class _RouterConnectionManager:
    def __init__(self):
        self.active: dict[str, WebSocket] = {}

    async def connect(self, session_id: str, ws: WebSocket):
        await ws.accept()
        self.active[session_id] = ws

    def disconnect(self, session_id: str):
        self.active.pop(session_id, None)

    async def send_ack(self, session_id: str, ack: VisionAck):
        ws = self.active.get(session_id)
        if ws:
            await ws.send_text(ack.model_dump_json())


_mgr = _RouterConnectionManager()


@vision_router.websocket("/ws/vision")
async def vision_socket(ws: WebSocket):
    # ★ accept()를 가장 먼저 호출
    await ws.accept()
    session_id: str = f"anon_{int(time.time())}"
    try:
        raw_first = await ws.receive_text()
        data = json.loads(raw_first)
        session_id = data.get("session_id", session_id)
        _mgr.active[session_id] = ws
        await _handle(session_id, data)

        while True:
            raw = await ws.receive_text()
            await _handle(session_id, json.loads(raw))

    except WebSocketDisconnect:
        pass
    finally:
        _mgr.disconnect(session_id)


async def _handle(session_id: str, raw: dict):
    recv_t = time.perf_counter()
    try:
        frame = VisionFrame(**raw)
    except Exception as e:
        ack = VisionAck(frame_id=raw.get("frame_id", -1), status="error", message=str(e))
        await _mgr.send_ack(session_id, ack)
        return

    logger.info(
        f"[Vision] frame={frame.frame_id}  fps={frame.fps:.1f}  "
        f"hands={len(frame.hands)}  sess={session_id}"
    )

    # ── [1단계 연동 지점] ──────────────────────────────────
    # rag_result = await rag_search(frame)   # 1단계 함수 호출
    rag_result = None

    ms = (time.perf_counter() - recv_t) * 1000
    await _mgr.send_ack(
        session_id,
        VisionAck(frame_id=frame.frame_id, status="ok", rag_result=rag_result,
                  message=f"{ms:.1f}ms"),
    )
