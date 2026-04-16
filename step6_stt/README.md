# 📋 ITDA 6단계 개발 작업 보고서
> 작업일: 2026-04-15  
> 담당자: 6단계 (+ 9단계는 `step9_layer/` 참고)  
> 브랜치: `dodreamai`

---

## 📌 한눈에 보는 6단계 흐름

```
유튜브 / 앱 재생 소리
        │
        ▼
  [브라우저] Web Audio API
  getDisplayMedia("탭 오디오 공유")
        │
        ▼
  MediaRecorder (WebM Opus 2초 청크)
        │
        ▼  WebSocket Binary (포트 8000)
  ┌─────────────────────────────┐
  │        FastAPI 서버          │
  │  ① faster-whisper → 텍스트   │
  │  ② RAG Bridge    → 수어단어  │
  └─────────────────────────────┘
        │
        ▼  WebSocket JSON (STTResponse)
  [브라우저] STTClient 수신
        │
        └──► PIPOverlay: 수어 카드 + 자막 패널 표시
```

> **9단계 (오디오 분석 + 영상 레이어링)** 는 별도 폴더 `step9_layer/` 를 확인하세요.

---

## 🗂️ 폴더 구조 (3대 약속 #2 준수)

```
step6_stt/
├── api/                    ← 🔒 백엔드 전용 (포트 8000)
│   ├── schema.py           ← ⭐ JSON 스키마 기준 파일 (변경 전 팀 합의 필수)
│   ├── main.py             ← FastAPI 앱 진입점
│   ├── stt_router.py       ← WebSocket /api/ws/stt 엔드포인트
│   ├── rag_bridge.py       ← 1단계 RAG 연동 브릿지 (현재: 스텁)
│   └── requirements.txt
│
└── static/                 ← 🔒 프론트엔드 전용
    ├── index.html          ← 메인 UI (PIP 수어 카드 패널)
    └── js/
        ├── audio_capture.js  ← Web Audio API 캡처 (시스템·마이크)
        ├── stt_client.js     ← WebSocket STT 클라이언트
        └── pip_overlay.js    ← 수어 카드 + 자막 PIP 패널
```

---

## ✅ 6단계: 외부 미디어 사운드 캡처 + 실시간 수어 통역

### 무엇을 했나?
유튜브 등 외부 재생 소리를 캡처해서 Whisper STT로 텍스트로 바꾸고,  
RAG 엔진으로 수어 단어를 검색하여 PIP 화면에 보여줍니다.

### 핵심 파일

| 파일 | 설명 |
|------|------|
| `api/schema.py` | **JSON 데이터 기준** — `AudioMeta`, `STTResponse`, `SignTerm` |
| `api/stt_router.py` | WebSocket `/api/ws/stt` — 오디오 청크 수신 → Whisper → RAG → 응답 |
| `api/rag_bridge.py` | 1단계 팀 연동 슬롯 (현재 샘플 데이터로 동작) |
| `static/js/audio_capture.js` | `getDisplayMedia` 로 시스템 오디오 캡처, 2초 청크 생성 |
| `static/js/stt_client.js` | WebSocket 클라이언트, `itda:stt:text` / `itda:stt:sign` 이벤트 발행 |
| `static/js/pip_overlay.js` | 수신 이벤트 → 수어 카드 + 자막 PIP 패널 렌더링 |

### WebSocket 프로토콜 (3대 약속 #1)

```
클라이언트 → 서버 (매 청크마다 2-프레임 전송)
  Frame 1 (JSON 텍스트):
    { session_id, chunk_id, timestamp_ms, source, duration_ms }

  Frame 2 (Binary):
    WebM Opus 오디오 바이트

서버 → 클라이언트 (JSON 텍스트):
  {
    session_id, chunk_id,
    text,        confidence,  language,
    sign_terms:  [{ word, sign_id, description, emotion_tag, confidence }],
    emotion_weight,  rag_status,
    process_ms,  status
  }
```

### 4단계 아바타 연동 방법 (팀장님 확인)
`pip_overlay.js` 가 자동으로 아래 이벤트를 발행합니다.  
**4단계 쪽에서 이 이벤트만 수신하면 연결됩니다. 파일 수정 없음.**

```javascript
// 4단계 avatar.js 에 추가할 코드 (한 줄)
window.addEventListener('itda:sign:perform', (e) => {
  const { sign_terms, emotion_weight, query_text } = e.detail;
  // 아바타 수어 동작 실행
});
```

---

## 🚀 실행 방법

```bash
# 1. 의존성 설치
cd step6_stt/api
pip install -r requirements.txt

# 2. 서버 실행 (포트 8000)
uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# 3. 브라우저 접속
http://localhost:8000/static/index.html
```

---

## 🔌 팀간 연동 포인트

### → 1단계 팀에게 (RAG 백엔드)
`api/rag_bridge.py` 의 `search_sign_language()` 함수만 교체하면 됩니다.

```python
# rag_bridge.py 상단 주석 해제 후 교체
from step1_rag.search_engine import faiss_search

async def search_sign_language(session_id, text):
    results = await faiss_search(text)          # ← 이 줄만 바꾸면 끝
    terms = [SignTerm(**r) for r in results]
    ...
```

### → 4단계 팀에게 (3D 아바타)
`step4_threejs/frontend/js/avatar.js` 에 이벤트 리스너 1개 추가:

```javascript
window.addEventListener('itda:sign:perform', (e) => {
  const { sign_terms, emotion_weight } = e.detail;
  // sign_terms[0].word 로 아바타 수어 동작 재생
  // emotion_weight (0~1) 로 표정 강도 조절
});
```

### → 9단계 팀에게
9단계는 `step9_layer/` 폴더에서 독립적으로 동작합니다.  
6단계 서버(`ws://localhost:8000/api/ws/stt`)에 WebSocket으로 연결해 STT 결과를 수신합니다.  
`step9_layer/README.md` 를 확인하세요.

---

## ⚠️ 주의사항 (3대 약속)

| 약속 | 내용 |
|------|------|
| **#1 JSON 스키마** | `schema.py` 가 유일한 기준. 필드 추가 전 팀 합의 필수 |
| **#2 폴더 분리** | 백엔드는 `api/` 만, 프론트엔드는 `static/` 만 수정 |
| **#3 포트 분리** | 6단계 백엔드 `8000` / 2단계 Vision서버 `8001` / 9단계 `8002` |
