import os
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import anyio
import uvicorn
from api.core.config import settings
from api.routers import sign_language
from api.routers import ws_vision
from api.routers import stt as stt_adapter
from api.routers import collect as collect_router
from api.services.data_pipeline import data_pipeline


@asynccontextmanager
async def lifespan(app: FastAPI):
    """서버 수명주기. 기동 시 데이터 파이프라인을 빌드하고 FAISS 인덱스를 준비한다."""
    app.state.is_ready = False
    print("[ITDA Backend] 시스템 시작 중... 데이터 파이프라인 구동 및 FAISS 인덱스 빌드 시작")
    try:
        # CPU 집약적인 파이프라인 빌드를 스레드에서 실행해 기동 중 이벤트 루프를 막지 않는다.
        processed_count = await anyio.to_thread.run_sync(data_pipeline.process_and_store)
        print(f"[ITDA Backend] 초기화 완료! {processed_count}개의 따뜻한 수어 데이터가 벡터화되었습니다.")
        app.state.is_ready = True
    except Exception as e:
        # 파이프라인 빌드가 실패해도 서버 자체는 기동시켜 /api/health 로 상태를 알린다.
        print(f"[ITDA Backend] 초기화 실패 - 서버는 기동하되 RAG 기능이 제한됩니다: {e}")
    yield


app = FastAPI(
    title=settings.PROJECT_NAME,
    description="ITDA Project: 따뜻한 감정이 담긴 수어 데이터 파이프라인 및 RAG 엔진 API",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — 로컬 개발(3000/5500/8000) + 운영 도메인(환경변수로 확장)
# 사용 예: ITDA_CORS_ORIGINS="https://project-itda.vercel.app,https://*.vercel.app"
_default_origins = [
    "http://localhost:3000", "http://127.0.0.1:3000",
    "http://localhost:5500", "http://127.0.0.1:5500",
    "http://localhost:8000",
]
_env_origins = [o.strip() for o in os.environ.get("ITDA_CORS_ORIGINS", "").split(",") if o.strip()]
# Vercel 프리뷰/프로덕션 도메인은 와일드카드 패턴으로 일괄 허용 (정규식)
_origin_regex = os.environ.get(
    "ITDA_CORS_ORIGIN_REGEX",
    r"^https://([a-z0-9-]+\.)*vercel\.app$",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_default_origins + _env_origins,
    allow_origin_regex=_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 정적 파일 — 모션 JSON(1.8GB)을 프론트엔드(Vercel)에서 직접 fetch 할 수 있게 마운트
# /static/motions/<word>.json → frontend/data/ksl_motions/<word>.json
_motions_dir = Path(__file__).resolve().parent.parent / "frontend" / "data" / "ksl_motions"
if _motions_dir.exists():
    app.mount("/static/motions", StaticFiles(directory=str(_motions_dir)), name="motions")
    print(f"[ITDA Backend] 모션 정적 마운트: /static/motions → {_motions_dir}")
else:
    print(f"[ITDA Backend] ⚠️ 모션 디렉토리 없음 — /static/motions 마운트 스킵: {_motions_dir}")

# 모듈화된 라우터 붙이기
app.include_router(
    sign_language.router,
    prefix="/api/sign-language",
    tags=["Sign Language Process"]
)

# 2단계 통합: Vision WebSocket 라우터
app.include_router(
    ws_vision.router,
    prefix="/api",
    tags=["Vision WebSocket"]
)

# [학습 데이터 수집 & KNN 훈련 라우터]
app.include_router(
    collect_router.router,
    prefix="/api/collect",
    tags=["KSL Data Collection"]
)

# STT 상태 라우터 (step6_stt 모듈 미포함으로 /status/stt 만 노출)
app.include_router(
    stt_adapter.router,
    tags=["STT"]
)

@app.get("/api/health")
def health_check():
    """프론트엔드 연결 전용 헬스체크 API: 서버가 AI 모델과 벡터DB를 로드했는지 상태 제공"""
    if getattr(app.state, "is_ready", False):
        return {"status": "ok", "message": "Backend models and data index are fully loaded."}
    else:
        return {"status": "loading", "message": "Backend is loading AI models and preparing vector index..."}

@app.get("/")
def read_root():
    return {"message": "Welcome to ITDA Backend Pipeline (Port 8000)"}

if __name__ == "__main__":
    uvicorn.run("api.main:app", host="0.0.0.0", port=settings.PORT, reload=True)
