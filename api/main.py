from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import uvicorn
from pathlib import Path
from api.core.config import settings
from api.routers import sign_language
from api.routers import ws_vision
from api.routers import stt as stt_adapter
from api.routers import collect as collect_router
from api.routers import video_proxy
from api.routers import augmentation as augmentation_router
from api.services.data_pipeline import data_pipeline

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="ITDA Project: 따뜻한 감정이 담긴 수어 데이터 파이프라인 및 RAG 엔진 API",
    version="1.0.0"
)

# 안티그래비티 규칙: 프론트엔드 포트(3000)를 위한 CORS 허용
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:5500", "http://127.0.0.1:5500", "http://localhost:8000", "null"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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

# 수어 영상 프록시 스트리밍
app.include_router(
    video_proxy.router,
    prefix="/api/video",
    tags=["Video Proxy"]
)

# 수어 영상 데이터 증강 (1개 → 100개)
app.include_router(
    augmentation_router.router,
    prefix="/api/augment",
    tags=["Augmentation"]
)

# [P3] 6단계 통합: STT 라우터 (step6_stt 어댑터)
# stt_adapter.router 는 로드 성공 시 step6_stt.stt_router(자체 prefix="/api") 이고,
# 실패 시 /status/stt 만 노출하는 fallback 라우터 → prefix 추가 지정 불필요
app.include_router(
    stt_adapter.router,
    tags=["STT (6단계)"]
)

# 프론트엔드 정적 파일 서비스 (API 라우터보다 뒤에 선언해야 충돌 없음)
_FRONTEND_DIR = Path(__file__).resolve().parents[1] / "frontend"
if _FRONTEND_DIR.exists():
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request as StarletteRequest

    class NoCacheMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: StarletteRequest, call_next):
            response = await call_next(request)
            if request.url.path.startswith("/ui/"):
                response.headers["Cache-Control"] = "no-store"
            return response

    app.add_middleware(NoCacheMiddleware)
    app.mount("/ui", StaticFiles(directory=str(_FRONTEND_DIR)), name="frontend")

@app.on_event("startup")
async def startup_event():
    app.state.is_ready = False
    # 백엔드 서버 시작 시, 문화데이터 수집 및 FAISS 벡터화 진행 (우선은 로컬 목업)
    print("[ITDA Backend] 시스템 시작 중... 데이터 파이프라인 구동 및 FAISS 인덱스 빌드 시작")
    processed_count = data_pipeline.process_and_store()
    print(f"[ITDA Backend] 초기화 완료! {processed_count}개의 따뜻한 수어 데이터가 벡터화되었습니다.")
    app.state.is_ready = True

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
