# ITDA Backend — Hugging Face Spaces (Docker SDK) 용 Dockerfile
# 사용처: 백엔드 + 모션 정적 파일(frontend/data/ksl_motions/) 통합 서빙
FROM python:3.11-slim

# 시스템 의존성 — OpenCV/MediaPipe 의 네이티브 라이브러리 요구사항 포함
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libgomp1 \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    libgthread-2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Hugging Face Spaces 는 컨테이너를 사용자 1000 으로 실행
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PYTHONUNBUFFERED=1

WORKDIR /home/user/app

# 의존성 먼저 — 캐시 효율
COPY --chown=user:user backend-requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# 백엔드 + 프론트엔드(모션 데이터) 복사
# .dockerignore 가 무거운 파일 제외
COPY --chown=user:user api ./api
COPY --chown=user:user frontend ./frontend

# Hugging Face Spaces 는 7860 포트를 외부에 노출
ENV PORT=7860
EXPOSE 7860

# Uvicorn 으로 FastAPI 서버 기동 (Vercel 프론트엔드와 통신)
CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-7860}"]
