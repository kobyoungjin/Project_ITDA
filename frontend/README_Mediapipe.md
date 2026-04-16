# 2단계: MediaPipe 기반 실시간 수어 좌표 추출 엔진

## 개요
- 브라우저 WebRTC 카메라 → MediaPipe Hands → 21개 관절 중 수어 핵심 좌표 추출
- JSON 정규화 후 WebSocket으로 FastAPI 서버(1단계)에 전송
- 30fps 이상 최적화

## 구조
```
step2_mediapipe/
├── backend/
│   ├── main.py          # FastAPI WebSocket 수신 서버
│   ├── schema.py        # Pydantic 데이터 모델
│   └── requirements.txt
└── frontend/
    ├── index.html       # 카메라 + MediaPipe 클라이언트
    └── js/
        ├── vision.js    # 좌표 추출·정규화·전송 로직
        └── overlay.js   # 관절 시각화 오버레이
```

## 1단계와의 연동 포인트
- WebSocket 메시지 포맷: `POST /api/search` 와 호환되는 JSON 스키마
- 추후 1단계 FastAPI 서버의 `main.py`에 `/ws/vision` 라우터 통합 시 `backend/main.py`의 라우터만 가져다 붙이면 됩니다.
