"""
main.py - 6단계: FastAPI 메인 서버
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
3대 약속 #3: 포트 8000

실행:
  cd step6_stt/api
  uvicorn main:app --host 0.0.0.0 --port 8000 --reload

엔드포인트:
  GET  /              → 서비스 정보
  GET  /health        → 상태 확인
  GET  /api/status/stt → Whisper 모델 상태
  WS   /api/ws/stt    → 실시간 STT 스트림
  GET  /static/       → 프론트엔드 (index.html)
"""

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from stt_router import stt_router, get_whisper_model

# ── 로거 ─────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("itda.main")

# ── FastAPI 앱 ───────────────────────────────────────────────
app = FastAPI(
    title="ITDA STT Server (6단계)",
    description="Web Audio API 시스템 오디오 캡처 → Whisper STT → RAG 수어 검색",
    version="1.0.0",
)

# CORS — 개발용 전체 허용 (배포 시 도메인 제한)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 라우터 등록
app.include_router(stt_router)

# 정적 파일 (프론트엔드) — /static/ 경로로 서빙
STATIC_DIR = Path(__file__).parent.parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
    logger.info(f"[Main] 정적 파일 서빙: {STATIC_DIR}")
else:
    logger.warning(f"[Main] static 폴더 없음: {STATIC_DIR}")


# ── 앱 시작 이벤트 — Whisper 모델 사전 로드 ────────────────
@app.on_event("startup")
async def startup_event():
    logger.info("[Main] 서버 시작 — Whisper 모델 사전 로딩...")
    get_whisper_model()  # 첫 요청 지연을 막기 위해 미리 로드
    logger.info("[Main] 준비 완료")


# ── 상태 엔드포인트 ──────────────────────────────────────────
@app.get("/health")
async def health():
    return {
        "status": "ok",
        "stage":  "step6_stt",
        "port":   8000,
    }


@app.get("/")
async def root():
    return {
        "service":    "ITDA STT Server",
        "stage":      "6단계 — 외부 미디어 사운드 캡처 + 실시간 수어 레이어",
        "docs":       "/docs",
        "frontend":   "/static/index.html",
        "websocket":  "ws://<host>:8000/api/ws/stt",
        "stt_status": "/api/status/stt",
    }
