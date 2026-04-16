from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from api.core.config import settings
from api.routers import sign_language
from api.routers import ws_vision
from api.services.data_pipeline import data_pipeline

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="ITDA Project: 따뜻한 감정이 담긴 수어 데이터 파이프라인 및 RAG 엔진 API",
    version="1.0.0"
)

# 안티그래비티 규칙: 프론트엔드 포트(3000)를 위한 CORS 허용
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "*"],
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
