"""
main.py - 2단계: MediaPipe 좌표 수신 FastAPI 서버

■ 역할
  - 브라우저 MediaPipe 클라이언트에서 WebSocket으로 전송되는 좌표를 수신
  - 데이터 검증(schema) → 로깅 → (1단계 연동 후) RAG 검색 요청

■ 1단계 통합 방법
  - 1단계팀이 만든 FastAPI app에
    `from step2_mediapipe.backend.router import vision_router`
    `app.include_router(vision_router)`  한 줄만 추가하면 됩니다.

■ 실행 (독립 실행)
  uvicorn main:app --host 0.0.0.0 --port 8001 --reload
"""

import json
import logging
import time
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from schema import VisionFrame, VisionAck

# ─── 로거 설정 ────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger("itda.vision")

# ─── FastAPI 앱 초기화 ───────────────────────────────────────
app = FastAPI(
    title="ITDA Vision Server (2단계)",
    description="MediaPipe 기반 실시간 수어 좌표 수신 서버",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # 개발용: 배포 시 도메인 제한 적용
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── 정적 파일 서빙 (프론트엔드) ────────────────────────────
FRONTEND_DIR = Path(__file__).parent.parent / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="static")


# ─── 연결 관리 ───────────────────────────────────────────────
class ConnectionManager:
    """멀티 클라이언트 WebSocket 연결 관리"""

    def __init__(self):
        self.active: dict[str, WebSocket] = {}  # session_id → ws

    async def connect(self, session_id: str, ws: WebSocket):
        # accept()는 엔드포인트에서 이미 호출됨 - 여기선 등록만 수행
        self.active[session_id] = ws
        logger.info(f"[Vision] 클라이언트 연결: {session_id}  (총 {len(self.active)}개)")

    def disconnect(self, session_id: str):
        self.active.pop(session_id, None)
        logger.info(f"[Vision] 클라이언트 해제: {session_id}  (총 {len(self.active)}개)")

    async def send_ack(self, session_id: str, ack: VisionAck):
        ws = self.active.get(session_id)
        if ws:
            await ws.send_text(ack.model_dump_json())


manager = ConnectionManager()


# ─────────────────────────────────────────────────────────────
# WebSocket 엔드포인트
# 클라이언트 URL: ws://<host>:8001/ws/vision
# ─────────────────────────────────────────────────────────────
@app.websocket("/ws/vision")
async def vision_socket(ws: WebSocket):
    """
    MediaPipe 손 관절 좌표 수신 엔드포인트.

    수신 포맷: VisionFrame (schema.py 참조)
    응답 포맷: VisionAck   (schema.py 참조)
    """
    # ★ accept()를 가장 먼저 호출해야 합니다.
    #    이후에 receive_text() 등을 쓸 수 있습니다.
    await ws.accept()
    session_id: str = f"anon_{int(time.time())}"

    try:
        # 첫 프레임 수신 → session_id 확정 → 관리자 등록
        raw_first = await ws.receive_text()
        data_first = json.loads(raw_first)
        session_id = data_first.get("session_id", session_id)

        # accept()가 이미 완료됐으므로 active 딕셔너리에 직접 등록
        manager.active[session_id] = ws
        logger.info(f"[Vision] 클라이언트 연결: {session_id}  (총 {len(manager.active)}개)")

        # 첫 프레임 처리
        await _process_frame(session_id, data_first)

        # 이후 프레임 루프
        while True:
            raw = await ws.receive_text()
            data = json.loads(raw)
            await _process_frame(session_id, data)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"[Vision] 오류: {e}", exc_info=True)
    finally:
        manager.disconnect(session_id)


async def _process_frame(session_id: str, raw_data: dict):
    """
    수신 프레임 처리 파이프라인:
    1. Pydantic 검증
    2. 핵심 지표 로깅 (frame_id, fps, 손 개수)
    3. [1단계 연동 지점] RAG 검색 호출 (현재는 None 반환)
    4. ACK 응답 전송
    """
    recv_time = time.perf_counter()

    # ── 1. Pydantic 스키마 검증 ──────────────────────────────
    try:
        frame = VisionFrame(**raw_data)
    except Exception as e:
        ack = VisionAck(frame_id=raw_data.get("frame_id", -1), status="error", message=str(e))
        await manager.send_ack(session_id, ack)
        logger.warning(f"[Vision] 잘못된 프레임 형식: {e}")
        return

    # ── 2. 로깅 ──────────────────────────────────────────────
    hand_count = len(frame.hands)
    logger.info(
        f"[Vision] frame={frame.frame_id:06d}  fps={frame.fps:.1f}  "
        f"손={hand_count}개  sess={session_id}"
    )

    if hand_count > 0:
        for hand in frame.hands:
            kp = hand.keypoints[0]  # 손목(WRIST) 좌표만 샘플 출력
            logger.debug(
                f"  └─ [{hand.handedness}] 손목: "
                f"x={kp.x:.4f} y={kp.y:.4f} z={kp.z:.4f}"
            )

    # ── 3. [1단계 연동 지점] RAG 검색 ────────────────────────
    # 1단계 팀이 vector_store.py / search_engine.py 를 완성하면
    # 아래 주석을 해제하고 실제 검색 함수를 호출하세요.
    #
    # from app.search_engine import rag_search   # 1단계 모듈 임포트
    # rag_result = await rag_search(frame)       # 비동기 RAG 검색
    rag_result = None  # 현재는 빈 슬롯

    # ── 4. ACK 응답 ──────────────────────────────────────────
    process_ms = (time.perf_counter() - recv_time) * 1000
    ack = VisionAck(
        frame_id=frame.frame_id,
        status="ok",
        rag_result=rag_result,
        message=f"처리 완료 ({process_ms:.1f}ms)",
    )
    await manager.send_ack(session_id, ack)


# ─── 상태 확인 엔드포인트 ────────────────────────────────────
@app.get("/health")
async def health():
    return {
        "status": "ok",
        "stage": "step2_mediapipe",
        "active_sessions": len(manager.active),
    }


@app.get("/")
async def root():
    return {
        "service": "ITDA Vision Server",
        "stage": "2단계 - MediaPipe 실시간 좌표 수신",
        "docs": "/docs",
        "websocket": "ws://<host>:8001/ws/vision",
        "frontend": "/static/index.html",
    }
