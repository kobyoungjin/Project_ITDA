# ITDA(잇다) 프로젝트 분석 보고서

> **Integrating The Deaf and All** — 청각장애인과 모든 사람을 하나로 잇다  
> AI 기반 실시간 한국수어(KSL) 양방향 통역 플랫폼  
> 2026.06.09 기준

---

## 1. 시스템 아키텍처

```
┌─────────────────────────────────────────────────────────────┐
│                    사용자 입력                                │
│              텍스트 / 음성(STT) / 카메라                      │
└─────────┬──────────────┬───────────────┬────────────────────┘
          │              │               │
          ▼              ▼               ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────────┐
│ translator.js│ │stt-adapter.js│ │    vision.js     │
│ 텍스트→수어  │ │ 음성→텍스트  │ │ 카메라→관절추출  │
└──────┬───────┘ └──────┬───────┘ └────────┬─────────┘
       │                │                   │
       ▼                ▼                   ▼
┌─────────────────────────────────────────────────────────────┐
│                   FastAPI 백엔드 (:8000)                     │
│  ┌────────────────┐ ┌──────────────┐ ┌───────────────────┐  │
│  │sign_language.py│ │   stt.py     │ │  ws_vision.py     │  │
│  │ /search        │ │ /stt/ws      │ │  /ws/vision       │  │
│  │ /tokenize      │ │              │ │  WebSocket        │  │
│  │ /supabase/*    │ │              │ │                   │  │
│  └───────┬────────┘ └──────────────┘ └────────┬──────────┘  │
│          │                                     │             │
│  ┌───────▼────────────────────────────────────▼──────────┐  │
│  │                   서비스 레이어                         │  │
│  │ rag_engine → FAISS 벡터 검색 + 동의어 매핑              │  │
│  │ motion_tokenizer → 문장 분절 (longest-match greedy)     │  │
│  │ supabase_service → DB 조회 (lemma/motion/alias)         │  │
│  │ handshape_analyzer → 수형 분류 (6종)                    │  │
│  │ pose_analyzer → 손목 위치/팔꿈치 각도 분석               │  │
│  │ slm_agent → Rule-based + Ollama 수어 예측               │  │
│  │ vector_db → FAISS + SentenceTransformers 임베딩          │  │
│  │ b2_storage → Backblaze B2 영상 저장/인증 URL             │  │
│  └────────────────────────┬──────────────────────────────┘  │
│                           │                                  │
│  ┌────────────────────────▼──────────────────────────────┐  │
│  │                  데이터 소스                            │  │
│  │  Supabase DB (sign_lemma 4,009 / sign_motion 1,364)    │  │
│  │  Supabase Storage (투명 webm 1,203개 / 941MB)          │  │
│  │  Backblaze B2 (확장 저장소, Private + Auth Token)       │  │
│  │  로컬 JSON (frontend/data/ksl_motions/ 6,008개)         │  │
│  └────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────────┐
│                   프론트엔드 (:5500)                          │
│  motion_loader_v3.js — 영상 재생 엔진                        │
│  avatar.js — Three.js 3D 아바타 (sonyr.glb)                 │
│  retargeting.js — MediaPipe → 아바타 본 매핑 [비활성]        │
│  video_preloader.js — IndexedDB 영상 사전 캐싱 (944개)       │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. 필수 파일 목록

### 2.1 백엔드 — 핵심 (실행에 필수)

| 파일 | 역할 |
|------|------|
| `api/main.py` | FastAPI 앱 진입점, 라우터 등록, CORS, startup |
| `api/core/config.py` | 환경변수 로드 (Supabase/B2/API 키) |
| `api/core/websockets_schema.py` | WebSocket 통신 스키마 (VisionFrame/Ack) |

### 2.2 백엔드 — 라우터 (API 엔드포인트)

| 파일 | 엔드포인트 | 역할 |
|------|-----------|------|
| `api/routers/sign_language.py` | `/api/sign-language/*` | 수어 검색, 토크나이저, Supabase 모션, B2 토큰 |
| `api/routers/ws_vision.py` | `/api/ws/vision` | 카메라 WebSocket, 수형/포즈 분석, SLM 예측 |
| `api/routers/stt.py` | `/api/stt/*` | 음성 인식 어댑터 (Whisper 폴백) |

### 2.3 백엔드 — 서비스 (비즈니스 로직)

| 파일 | 역할 |
|------|------|
| `api/services/supabase_service.py` | DB 조회 (canonical→alias→SYNONYMS→구스키마), 영상 URL |
| `api/services/motion_tokenizer.py` | 문장→단어 분절, 어미/조사 스트리핑, 불규칙 활용 |
| `api/services/rag_engine.py` | NFC 정규화 + 동의어 + FAISS 벡터 검색 |
| `api/services/vector_db.py` | FAISS 인덱스 + SentenceTransformers 임베딩 |
| `api/services/handshape_analyzer.py` | 21개 관절 → 수형 6종 분류 (FIST/PALM/POINT/V/L/OK) |
| `api/services/pose_analyzer.py` | 어깨/팔꿈치/손목 위치 → 얼굴/가슴/허리 구역 분류 |
| `api/services/slm_agent.py` | 수형+위치+이동 → 수어 단어 예측 (15개 Rule + Ollama) |
| `api/services/data_pipeline.py` | 문화데이터광장 API → FAISS 벡터 스토어 구축 |
| `api/services/b2_storage.py` | Backblaze B2 업로드/인증 URL 생성 |

### 2.4 백엔드 — 도구 (배치/파이프라인)

| 파일 | 역할 |
|------|------|
| `api/tools/batch_sldict_bg.py` | sldict mp4 → rembg 배경 제거 → Supabase/B2 업로드 |
| `api/tools/mediapipe_retarget.py` | 영상 → Quaternion keyframe 추출 (V3 파이프라인) |
| `api/tools/keyframe_converter.py` | AI Hub 라벨 → V3 keyframe JSON 변환 |
| `api/tools/run_pipeline.py` | AI Hub 다운로드 → 변환 → 인덱스 생성 총괄 |
| `api/tools/fetch_video_urls.py` | KCISA API로 영상 URL 일괄 조회 |
| `api/tools/sldict_crawler.py` | 한국수어사전 영상 크롤링 |
| `api/services/supabase_ingest.py` | 영상 → MediaPipe 추출 → Supabase 적재 |

### 2.5 프론트엔드 — 핵심

| 파일 | 역할 |
|------|------|
| `frontend/index.html` | 메인 앱 UI, 스크립트 로드, HUD, 이벤트 바인딩 |
| `frontend/js/motion_loader_v3.js` | **핵심 엔진** — Supabase 조회 → 영상/모션 재생, playSequence 큐 |
| `frontend/js/translator.js` | 텍스트 입력 → 토크나이저 → 단어별 prefetch → 순차 재생 |
| `frontend/js/avatar.js` | Three.js 씬/카메라/렌더러, GLB 로드, 본 조작 API |
| `frontend/js/vision.js` | MediaPipe 3모델(Hand/Face/Pose) + WebSocket 전송 |
| `frontend/js/retargeting.js` | Blendshape→Morph + Hand→Bone 실시간 매핑 |
| `frontend/js/video_preloader.js` | IndexedDB 영상 사전 캐싱 (944개) |
| `frontend/js/handshape_loader.js` | 수형 라이브러리 로드 + 본 Quaternion 적용 |
| `frontend/js/stt/stt-adapter.js` | Web Speech / Whisper 이중 경로 음성 인식 |
| `frontend/js/education.js` | 수어 학습 모드 (5개 단어 연습) |

---

## 3. 데이터 흐름 — 3개 핵심 경로

### 경로 A: 텍스트/음성 → 수어 영상

```
사용자: "정말 오래간만이네"
  │
  ▼ translator.js
POST /api/sign-language/tokenize
  │
  ▼ motion_tokenizer.py
tokens: [{word:"정말", canonical:"정말"}, {word:"오래간만", ...}]
  │
  ▼ translator.js (각 단어 prefetch)
GET /api/sign-language/supabase/motion/정말
GET /api/sign-language/supabase/motion/오래간만
  │
  ▼ supabase_service.py
sign_lemma → sign_motion (keyframes) + sign_source_video (video_url)
  │
  ▼ motion_loader_v3.js
영상 우선: video_url → <video> 더블버퍼 크로스페이드 재생
모션 폴백: keyframes → Quaternion SLERP 아바타 재생
```

### 경로 B: 카메라 → 수어 인식 → 텍스트

```
카메라 프레임 (30fps)
  │
  ▼ vision.js
MediaPipe Hand(21관절) + Pose(33관절) + Face(52 blendshape)
  │
  ▼ WebSocket /api/ws/vision (0.5초 간격)
{ hands: [...], pose: {...}, meta_features: { motion_phase: "stable" } }
  │
  ▼ ws_vision.py
handshape_analyzer → "PALM"
pose_analyzer → "얼굴", "위로"
  │
  ▼ slm_agent._rule_based_predict()
RULE_HINTS 매칭: (PALM, 얼굴, 아래) → "안녕하세요"
  │
  ▼ rag_engine.retrieve_with_emotion("안녕하세요")
{ keyword: "안녕하세요", emotions: ["반가움"], warm_translation: "..." }
  │
  ▼ WebSocket 응답 → index.html #slm-output
"✨ 안녕하세요" 표시
```

### 경로 C: 데이터 구축 파이프라인

```
한국수어사전(sldict) / KCISA API / AI Hub
  │
  ▼ sldict_crawler.py / fetch_video_urls.py
영상 URL 수집 → sign_source_video 등록
  │
  ▼ batch_sldict_bg.py
mp4 다운로드 → rembg 배경 제거 → 투명 webm 생성
  │
  ▼ upload_to_storage()
Supabase Storage (960MB 미만) → B2 (초과 시 자동 전환)
  │
  ▼ sign_source_video.video_url 업데이트
프론트엔드에서 즉시 재생 가능
```

---

## 4. 데이터 현황

### 4.1 Supabase DB

| 테이블 | 행 수 | 설명 |
|--------|-------|------|
| `sign_lemma` | 4,009 | 단어 목록 (canonical word) |
| `sign_motion` | 1,364 | 모션 keyframe 데이터 |
| `sign_alias` | 36 | 동의어 매핑 |
| `sign_source_video` | 2,272 | 영상 URL (webm/mp4) |

### 4.2 스토리지

| 저장소 | 사용량 | 용량 |
|--------|--------|------|
| Supabase Storage | 941 MB | 1,000 MB (Free Plan) |
| Backblaze B2 | 0 MB | 10,000 MB (무료, 대기 중) |
| 로컬 ksl_motions | 3,642 MB | 6,008개 JSON 파일 |

### 4.3 영상 재생 가능 단어

| 유형 | 수량 | 상태 |
|------|------|------|
| 투명 webm (즉시 재생) | 1,203개 | Supabase Storage |
| sldict mp4 (배경 있음) | 928개 | 배경 제거 진행 중 |
| **합계** | **2,131개** | 고유 단어 기준 |

### 4.4 카메라 인식 가능 수어 (Rule-based 15개)

| 수형 | 손목 위치 | 이동 | 인식 단어 |
|------|----------|------|----------|
| PALM | 얼굴 | 아래 | 안녕하세요 |
| PALM+PALM | 가슴 | - | 고맙습니다 |
| FIST | 얼굴 | - | 미안합니다 |
| FIST | 가슴 | - | 힘내세요 |
| POINT | 얼굴 | - | 어디에요 |
| POINT | 가슴 | - | 이름이 뭐예요 |
| V | 얼굴 | - | 또 만나요 |
| L | 가슴 | - | 얼마예요 |
| OK | 가슴 | - | 좋아하다 |
| PALM+PALM | 얼굴 | - | 사랑합니다 |
| PALM | 가슴 | 아래 | 괜찮아요 |
| POINT+POINT | 가슴 | - | 수어 |
| POINT | 얼굴 | 위 | 학교 |
| POINT | 얼굴 | 아래 | 어머니 |
| FIST | 얼굴 | 위 | 아버지 |

---

## 5. 토크나이저 처리 로직

### 5.1 분절 알고리즘

```
입력: "안녕하세요 감사합니다"

1. 공백/구두점으로 세그먼트 분리
   → ["안녕하세요", "감사합니다"]

2. 각 세그먼트에 대해:
   a. 사전 통째 매칭 시도 → "안녕하세요" 있으면 완료
   b. 활용어미 스트리핑 → "감사합니다" - "합니다" = "감사" → 사전 검색
   c. longest-match greedy → 글자별 최장 매칭
   d. 불규칙 활용 매핑 → "더워" → "덥다"

3. 결과:
   [{word:"안녕하세요", source:"supabase", canonical:"안녕하세요"},
    {word:"감사합니다", source:"local",    canonical:"감사"}]
```

### 5.2 사전 규모

| 출처 | 단어 수 |
|------|---------|
| 로컬 KSL 인덱스 | 6,010개 |
| Supabase alias | 890개 |
| Supabase SYNONYMS | 223개 |
| **합계** | **7,123개** |

### 5.3 어미 스트리핑 목록 (일부)

- 격식체: `~합니다`, `~습니다`, `~입니다`
- 비격식: `~해요`, `~어요`, `~아요`
- 반말: `~했어`, `~이야`, `~야`
- 과거: `~했다`, `~었다`, `~았다`
- 기본형: `~하다`, `~되다`, `~이다`
- 조사: `~은/는/이/가/을/를/에서/에게` 등

### 5.4 불규칙 활용 매핑

- ㅂ불규칙: `반가` → `반갑다`, `고마` → `고맙다`, `더` → `덥다`
- ㄷ불규칙: `걸` → `걷다`, `들` → `듣다`
- ㅅ불규칙: `나` → `낫다`, `지` → `짓다`
- 르불규칙: `몰` → `모르다`, `빨` → `빠르다`

---

## 6. 기술 스택

### 6.1 화면 (프론트엔드)

| 기술 | 용도 |
|------|------|
| Three.js | 3D 아바타 렌더링 (sonyr.glb) |
| MediaPipe | 손/얼굴/포즈 관절 추출 |
| Web Speech API | 브라우저 음성 인식 (STT) |
| WebSocket | 실시간 카메라 데이터 전송 |
| IndexedDB | 영상 사전 캐싱 (944개) |
| ES Modules | 모듈 기반 코드 구조 |

### 6.2 서버 (백엔드)

| 기술 | 용도 |
|------|------|
| FastAPI | REST API + WebSocket 서버 |
| FAISS | 벡터 유사도 검색 |
| SentenceTransformers | 한국어 텍스트 임베딩 |
| Ollama (qwen3:4b) | SLM 에이전트 (비활성화 상태) |
| rembg (U2-Net) | 영상 배경 제거 |
| MediaPipe Holistic | 서버 측 관절 추출 |

### 6.3 데이터/인프라

| 기술 | 용도 |
|------|------|
| Supabase | PostgreSQL DB + Storage (1GB Free) |
| Backblaze B2 | 확장 영상 저장소 (10GB Free) |
| AI Hub | 수어 데이터셋 (WORD코드 3,000개) |
| KCISA API | 문화데이터광장 영상 URL 조회 |
| sldict.korean.go.kr | 한국수어사전 영상 수집 |

---

## 7. 환경 설정 (.env)

```env
# AI Hub
AIHUB_API_KEY=...         # aihub.or.kr 데이터셋 접근

# 문화데이터광장
CULTURE_API_KEY=...       # 수어 영상 URL 조회 (일일 1,000건 한도)

# Supabase
SUPABASE_URL=...          # 프로젝트 URL
SUPABASE_KEY=...          # anon 키 (프론트엔드용)
SUPABASE_SERVICE_KEY=...  # service role 키 (백엔드 관리용)

# Backblaze B2
B2_KEY_ID=...             # API 키 ID
B2_APP_KEY=...            # 비밀 키
B2_BUCKET_NAME=...        # 버킷 이름
```

---

## 8. 실행 방법

```bash
# 백엔드 서버 시작
python -m uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

# 프론트엔드 서버 시작
cd frontend && python -m http.server 5500

# 접속
http://localhost:5500
```

### 배치 작업

```bash
# 데이터 파이프라인 (AI Hub → 로컬 JSON)
python api/tools/run_pipeline.py --labels-only --limit 50

# 배경 제거 배치 (sldict mp4 → 투명 webm)
python api/tools/batch_sldict_bg.py --resume

# 토크나이저 사전 갱신
curl -X POST http://localhost:8000/api/sign-language/refresh-pipeline
```

---

## 9. 파일 통계

| 분류 | 파일 수 | 비고 |
|------|---------|------|
| Python 필수 (core/routers/services) | 8개 | 서버 구동 + 수어 번역 |
| Python 폴백/startup | 3개 | FAISS, RAG, 파이프라인 |
| Python 부가 (카메라/STT) | 5개 | 카메라 인식, Whisper |
| Python 도구 (tools) | 20개 | 배치, 파이프라인, 크롤러 |
| JavaScript 필수 | 5개 | 재생 엔진, 번역, 아바타, 프리로더, STT |
| JavaScript 부가 | 7개 | 카메라, 리타겟팅(비활성), 교육, 오버레이 |
| JavaScript STT 부가 | 2개 | Whisper 클라이언트, 오디오 캡처 |
| HTML | 3개 | index(필수), landing, handshape_preview |
| **합계** | **53개** | 필수 14개 + 폴백 3개 + 부가/도구 36개 |

---

## 10. 핵심 기능별 파일 분류 (텍스트/음성 → 수어 영상)

> 프로그램의 메인 기능인 **"텍스트/음성 입력 → 수어 영상 재생"** 에  
> 필수적인 파일과 제거 가능한 파일을 분류합니다.

### 10.1 필수 파일 (삭제 불가)

#### 백엔드 — 서버 구동

```
api/main.py                          # FastAPI 앱 진입점
api/core/config.py                   # 환경변수 (.env) 로드
api/core/__init__.py                 # 패키지 초기화
api/__init__.py                      # 패키지 초기화
```

#### 백엔드 — 수어 번역 API

```
api/routers/sign_language.py         # /search, /tokenize, /supabase/motion/{word}
api/routers/__init__.py              # 패키지 초기화
```

#### 백엔드 — 핵심 서비스

```
api/services/supabase_service.py     # Supabase DB 조회 (단어→영상 URL)
api/services/motion_tokenizer.py     # 문장 분절 (longest-match + 어미 스트리핑)
api/services/__init__.py             # 패키지 초기화
```

#### 백엔드 — 폴백/startup 의존 (정상 동작 시 미사용)

```
api/services/rag_engine.py           # RAG 검색 — tokenize 실패 시 폴백, Whisper 사용 시 필수
api/services/vector_db.py            # FAISS 벡터 DB — rag_engine 의존
api/services/data_pipeline.py        # 벡터 스토어 초기 구축 — main.py startup에서 호출
```

> **참고:** `main.py` startup에서 `data_pipeline.process_and_store()`를 호출하므로,
> 위 3개를 제거하려면 startup 로직도 함께 수정해야 합니다.

#### 프론트엔드 — 메인 UI 및 재생 엔진

```
frontend/index.html                  # 메인 앱 (UI + 스크립트 로드)
frontend/js/motion_loader_v3.js      # 영상/모션 재생 엔진 (Supabase 조회 → 재생)
frontend/js/translator.js            # 텍스트 입력 → 토크나이저 → 순차 재생
frontend/js/avatar.js                # Three.js 3D 아바타 (영상 위에 표시)
frontend/js/video_preloader.js       # IndexedDB 영상 사전 캐싱
```

#### 프론트엔드 — 음성 인식 (STT)

```
frontend/js/stt/stt-adapter.js       # Web Speech API / Whisper 어댑터
```

#### 데이터 파일

```
frontend/data/ksl_motions/index.json     # 수어 단어 인덱스 (6,008개)
frontend/data/ksl_motions/_mapping.json  # 한글→WORD코드 매핑
frontend/data/ksl_motions/*.json         # 개별 모션 JSON (2,986개 한글)
frontend/data/handshape_library.json     # 수형 라이브러리
frontend/models/sonyr.glb               # 3D 아바타 모델
```

#### 설정

```
.env                                 # API 키, Supabase/B2 인증정보
```

### 10.2 부가 기능 파일 (메인에 영향 없이 제거 가능)

#### 카메라 수어 인식 (경로 B)

```
api/routers/ws_vision.py             # WebSocket 비전 라우터
api/core/websockets_schema.py        # WebSocket 스키마
api/services/handshape_analyzer.py   # 수형 분류기
api/services/pose_analyzer.py        # 포즈 분석기
api/services/slm_agent.py            # SLM 예측 에이전트
frontend/js/vision.js                # MediaPipe 카메라 엔진
frontend/js/overlay.js               # 카메라 시각화 오버레이
```

#### 비활성 모듈 (로드되지만 자동 실행 안 됨)

```
frontend/js/retargeting.js           # 실시간 미러링 [2026-05-07 비활성화, 이벤트 리스너 주석 처리]
```

#### 교육 모드

```
frontend/js/education.js             # 수어 학습 모드
```

#### STT 백엔드 (Whisper)

```
api/routers/stt.py                   # STT 라우터 어댑터
frontend/js/stt/stt_client.js        # Whisper WebSocket 클라이언트
frontend/js/stt/audio_capture.js     # 오디오 캡처
step6_stt/                           # STT 전체 모듈 (별도 프로젝트)
```

#### 외부 스토리지

```
api/services/b2_storage.py           # Backblaze B2 (확장 저장소)
```

### 10.3 배치/도구 파일 (운영 시 불필요, 개발/구축 시에만 사용)

```
api/tools/batch_sldict_bg.py         # 배경 제거 배치
api/tools/batch_remove_bg.py         # 배경 제거 (Supabase mp4)
api/tools/mediapipe_retarget.py      # 영상→모션 추출
api/tools/keyframe_converter.py      # AI Hub→V3 변환
api/tools/run_pipeline.py            # AI Hub 파이프라인
api/tools/fetch_video_urls.py        # 영상 URL 수집
api/tools/sldict_crawler.py          # 수어사전 크롤러
api/tools/aihub_downloader.py        # AI Hub 다운로더
api/tools/skeleton_extractor.py      # 관절 추출기
api/tools/handshape_mapper.py        # 수형 매퍼
api/tools/generate_handshape_library.py  # 수형 라이브러리 생성
api/tools/sync_local_to_supabase.py  # 로컬→Supabase 동기화
api/tools/map_word_ids.py            # 단어 ID 매핑
api/tools/extract_human_proportions.py   # 인체 비율 추출
api/tools/location_movement_analyzer.py  # 위치/이동 분석
api/tools/fix_thanks_motion.py       # 감사 모션 수정
api/tools/fix_thanks_motion_v2.py    # 감사 모션 수정 v2
api/tools/restore_db.py              # DB 복구
api/tools/restore_db2.py             # DB 복구 v2
api/tools/upload_thanks.py           # 감사 업로드
api/tools/remove_video_bg_test.py    # 배경 제거 테스트
api/services/supabase_ingest.py      # Supabase 인제스트
```

### 10.4 제거 가능 파일 (불필요)

```
api/__pycache__/                     # Python 캐시 (자동 생성)
api/core/__pycache__/                # Python 캐시
api/routers/__pycache__/             # Python 캐시
api/services/__pycache__/            # Python 캐시
api/tools/__pycache__/               # Python 캐시
temp_bg_removal/                     # 배경 제거 임시 파일
analyze_love_motion.py               # 분석 스크립트 (일회성)
frontend/models/female_human.glb     # 미사용 모델
frontend/models/ITDAModel.glb        # 폴백 모델 (sonyr.glb 사용 시 불필요)
```

---

## 11. 핵심 코드 흐름 (텍스트 → 수어 영상)

### 11.1 사용자 입력 처리 — `translator.js`

```javascript
// 68행: 사용자가 텍스트 입력 후 전송
async function sendMessage(text) {
  // [1] 백엔드 토크나이저로 문장 분절
  const resTok = await fetch('/api/sign-language/tokenize', {
    method: 'POST',
    body: JSON.stringify({ text })
  });
  const tokenResult = await resTok.json();
  const playable = tokenResult.playable_words; // ["정말", "오래간만"]

  // [2] 각 단어의 영상을 Supabase에서 prefetch
  const items = await Promise.all(tokensMeta.map(async (t) => {
    const lookupKey = t.word;
    const r = await fetch(`/api/sign-language/supabase/motion/${lookupKey}`);
    const md = (await r.json()).motion_data;
    // 영상 URL → Blob 다운로드 → 즉시 재생 준비
    if (md.video_url) {
      const blob = await (await fetch(md.video_url)).blob();
      md._blobUrl = URL.createObjectURL(blob);
    }
    return { word: lookupKey, motion: md };
  }));

  // [3] 순차 재생
  await window.ITDAMotionV3.playSequence(items, { gapMs: 0 });
}
```

### 11.2 문장 분절 — `motion_tokenizer.py`

```python
# 310행: 핵심 분절 알고리즘
def tokenize(self, text: str) -> list[dict]:
    # 1. 공백/구두점으로 세그먼트 분리
    segments = split_by_boundary(text)

    for seg in segments:
        # 2. 사전 통째 매칭 시도
        if seg in self._dict:
            tokens.append({word: seg, source, canonical})
            continue

        # 3. 활용어미/조사 스트리핑 → 어간 검색
        strip_hit = self._strip_and_lookup(seg)
        if strip_hit:
            tokens.append(...)
            continue

        # 4. longest-match greedy (글자별)
        while i < len(seg):
            hit = self._longest_match(seg, i)
            ...
```

### 11.3 Supabase 모션 조회 — `supabase_service.py`

```python
# 244행: 단어 → 모션 데이터 반환
def get_motion_data(self, word: str):
    # 1. resolve: 캐시 → SYNONYMS → canonical
    canonical = self.resolve(word)
    if not canonical:
        syn = self.SYNONYMS.get(self._norm(word))
        canonical = syn if syn else word

    # 2. 영상 URL 조회 (sign_lemma JOIN sign_source_video)
    video_url = query_video(canonical)

    # 3. 모션 keyframes 조회 (v_sign_canonical 뷰)
    motion = query_motion(canonical)

    return { word, motion_data: { video_url, keyframes, ... } }
```

### 11.4 영상 재생 — `motion_loader_v3.js`

```javascript
// 78행: 단어 → 모션 로드 (Supabase 우선 → 로컬 폴백)
async function loadMotion(word) {
  // 1. Supabase DB 조회
  const supaRes = await fetch(`/api/supabase/motion/${word}`);
  if (supaRes.ok && result.motion_data.video_url) {
    return motion; // 영상 URL 포함
  }

  // 2. 로컬 JSON 폴백
  const localUrl = `./data/ksl_motions/${word}.json`;
  const motion = await fetch(localUrl);
  return motion; // keyframes 포함
}

// 171행: 재생 분기
async function playMotion(word) {
  const motion = await loadMotion(word);

  // 영상 전용 (keyframes 없고 video_url만)
  if (!motion.keyframes?.length && motion.video_url) {
    return _playVideoOnly(motion.video_url, word);
  }

  // 아바타 모션 (keyframes SLERP)
  return _playCore(motion, word);
}

// 229행: 더블 버퍼링 영상 재생
function _playVideoOnly(videoUrl, label) {
  // 두 <video> 엘리먼트를 교대로 사용
  // 크로스페이드 전환으로 끊김 없는 재생
  activeVid.src = videoUrl;
  activeVid.play();
  // ended 이벤트 → 다음 단어로 전환
}
```

### 11.5 API 엔드포인트 — `sign_language.py`

```python
# /tokenize: 문장 → 단어 배열
@router.post("/tokenize")
async def tokenize_sentence(request: TokenizeRequest):
    tokens = motion_tokenizer.tokenize(request.text)
    playable = [t for t in tokens if t['source'] != 'unknown']
    return { tokens, playable_words: [t['word'] for t in playable] }

# /supabase/motion/{word}: 단어 → 모션+영상 데이터
@router.get("/supabase/motion/{word}")
async def get_supabase_motion(word: str):
    data = supabase_service.get_motion_data(word)
    return { status: "success", motion_data: data }

# /search: RAG 감정 검색
@router.post("/search")
async def search_sign_language(request: SearchRequest):
    result = rag_engine.retrieve_with_emotion(request.query)
    return { keyword, warm_translation, video_url, emotions }
```

---

## 12. 실행 최소 요구사항

### 12.1 필수 Python 패키지

```
fastapi, uvicorn            # API 서버
supabase                    # Supabase DB 클라이언트
pydantic-settings           # 환경변수 관리
numpy                       # 수치 계산
```

#### 폴백/Whisper 사용 시 필요

```
sentence-transformers       # 텍스트 임베딩 (FAISS 폴백 사용 시)
faiss-cpu                   # 벡터 검색 (FAISS 폴백 사용 시)
```

### 12.2 필수 환경변수

```
SUPABASE_URL                # 필수
SUPABASE_KEY                # 필수
SUPABASE_SERVICE_KEY        # 필수
```

### 12.3 선택 환경변수

```
B2_KEY_ID, B2_APP_KEY, B2_BUCKET_NAME   # B2 사용 시
AIHUB_API_KEY                           # 데이터 구축 시
CULTURE_API_KEY                         # 영상 URL 수집 시
```

---

## 13. 코드 이슈 및 구조 분석

### 13.1 FAISS는 핵심이 아닌 폴백

문서 10장에서 `rag_engine.py`와 `vector_db.py`를 필수로 분류했으나, 실제 실행 흐름에서는 **폴백 경로**입니다.

```
translator.js sendMessage() 흐름:

77행: if (window.ITDAMotionV3) {
        → tokenize 호출 → playable 단어 있으면 playSequence 실행
151행:  return;  ← 여기서 종료. /search(FAISS)에 도달하지 않음
      }

155행: /search 호출 ← tokenize 실패 또는 ITDAMotionV3 미로드 시에만 진입
        → rag_engine → FAISS 벡터 검색
```

**결론:** 정상 동작 시 `/tokenize → /supabase/motion` 경로만 사용되고, FAISS(`/search`)는 토크나이저 실패 시 폴백입니다. 다만 `data_pipeline.py`가 `main.py` startup에서 호출되어 FAISS 인덱스를 빌드하므로, 제거 시 startup 로직 수정이 필요합니다.

**필수 분류 수정:**
- `api/services/rag_engine.py` → **폴백** (필수는 아니나 startup 연동)
- `api/services/vector_db.py` → **폴백** (위와 동일)
- `api/services/data_pipeline.py` → **startup 의존** (FAISS 제거 시 함께 수정)

### 13.2 동의어 사전 3중 중복

동의어 매핑이 3곳에 분산되어 있어 불일치 위험이 있습니다.

| 위치 | 동의어 수 | 용도 |
|------|----------|------|
| `supabase_service.py` SYNONYMS | 150+개 | DB 조회 시 canonical 변환 |
| `rag_engine.py` synonyms | 6개 | FAISS 검색 전 키워드 확장 |
| `translator.js` SYNONYMS (197행) | 5개 | 백엔드 다운 시 프론트엔드 폴백 |

```python
# supabase_service.py (150+개, 메인)
SYNONYMS = { "안녕": "안녕하세요", "고맙습니다": "감사", ... }

# rag_engine.py (6개, 폴백)
self.synonyms = { "감사": "고맙습니다", "인사": "안녕하세요", ... }

# translator.js (5개, 오프라인 폴백)
const SYNONYMS = { '감사': '고맙습니다', '미안': '미안합니다', ... };
```

**문제:** `rag_engine.py`의 `"감사": "고맙습니다"`와 `supabase_service.py`의 `"감사": "감사"`가 방향이 반대입니다.

**권장:** `supabase_service.py` SYNONYMS를 단일 소스로 통합하고, `rag_engine.py`와 `translator.js`의 중복 사전을 제거하거나 supabase_service에서 가져오도록 변경.

### 13.3 어미/조사 처리 중복

한국어 어미 스트리핑이 2곳에 독립 구현되어 있습니다.

| 위치 | 구현 | 커버리지 |
|------|------|---------|
| `motion_tokenizer.py` | `_VERB_SUFFIXES` (99개) + `_PARTICLES` (30개) + `_IRREGULAR_STEMS` (35개) | 포괄적 |
| `supabase_service.py` SYNONYMS | 활용형 하드코딩 ("반가워": "반갑다" 등) | 수동, 누락 다수 |

**문제:** `motion_tokenizer.py`는 어미를 자동 스트리핑하지만, `supabase_service.py`는 SYNONYMS에 활용형을 수동 나열합니다. 예를 들어 "즐거웠어"는 tokenizer에서 자동 처리되지만, supabase_service에서는 SYNONYMS에 없으면 resolve 실패합니다.

**권장:** `supabase_service.get_motion_data()`에서 resolve 실패 시 `motion_tokenizer._strip_and_lookup()` 로직을 재사용하여 어간 추출.

### 13.4 하드코딩 이슈

| 파일 | 행 | 내용 | 위험 |
|------|------|------|------|
| `sign_language.py` | 169행 | `r"c:\Users\ComHolic\Desktop\ITDA_DB\src\_process_uploaded.py"` | 다른 PC에서 실행 불가 |
| `slm_agent.py` | 96행 | `"http://localhost:11434/api/generate"` | Ollama 주소 하드코딩 |
| `translator.js` | 80행 | `'http://localhost:8000/api/sign-language/tokenize'` | 배포 시 변경 필요 |
| `vision.js` | 137행 | `` `ws://${location.hostname}:8000/api/ws/vision` `` | 포트 하드코딩 (hostname은 동적) |
| `map_word_ids.py` | 26행 | `r"C:/Users/ComHolic/Desktop/data/..."` | 로컬 절대 경로 |

### 13.5 누락된 디렉토리 — step4/5/6/9

프로젝트 루트에 4개의 step 디렉토리가 있으나 문서에서 누락되었습니다.

```
step4_threejs/      → 이전 버전 프론트엔드 (현재 frontend/에 통합됨)
step5_face_sync/    → 이전 버전 얼굴 동기화 (현재 frontend/에 통합됨)
step6_stt/          → STT 모듈 (api/routers/stt.py가 브릿지)
step9_layer/        → 레이어 실험 코드
```

**현재 상태:**
- `step4`, `step5` → `frontend/`에 통합 완료. 제거 가능 (아카이브 용도)
- `step6_stt` → `api/routers/stt.py`가 임포트하여 사용 중. STT 기능 필요 시 유지
- `step9_layer` → 실험 코드. 제거 가능

### 13.6 누락된 프론트엔드 HTML

| 파일 | 용도 | 분류 |
|------|------|------|
| `frontend/landing.html` | 랜딩 페이지 (프로젝트 소개, A4) | 보조 — 제거 가능 |
| `frontend/handshape_preview.html` | 수형 라이브러리 미리보기 (개발용) | 도구 — 제거 가능 |

두 파일 모두 메인 앱(`index.html`)과 독립적이며 삭제해도 기능에 영향 없습니다.

### 13.7 STT 경로에서 FAISS 사용 (13.1 보완)

`stt.py:42-43`에서 `rag_engine.retrieve_with_emotion()`을 직접 호출합니다.

```python
# stt.py:42-43
async def _unified_search(session_id: str, text: str):
    data = rag_engine.retrieve_with_emotion(text)  # ← FAISS 사용
```

따라서 FAISS가 사용되는 경로는 2개입니다:

| 경로 | 조건 | FAISS 사용 |
|------|------|-----------|
| translator.js → `/tokenize` → `/supabase/motion` | 정상 (메인) | 사용 안 함 |
| translator.js → `/search` | 토크나이저 실패 시 폴백 | 사용 |
| **stt.py → `_unified_search`** | **음성 인식 결과 처리** | **사용** |

**FAISS 사용 여부 정리:**

| 상황 | FAISS 사용? |
|------|-----------|
| 텍스트 입력 → tokenize 성공 | 안 함 |
| 텍스트 입력 → tokenize 실패 → /search 폴백 | 사용 |
| 음성 → Web Speech API → sendMessage() | 안 함 (텍스트 경로와 동일) |
| 음성 → Whisper 백엔드 → _unified_search() | 사용 (faster-whisper 설치 시만) |

**결론:** Web Speech API(브라우저 기본)를 사용하면 FAISS 없이도 음성 입력이 정상 작동합니다. FAISS가 필수가 되는 경우는 **Whisper 백엔드를 명시적으로 사용할 때**뿐입니다.

### 13.8 retargeting.js 비활성 상태 (데드코드)

retargeting.js 321-325행의 이벤트 리스너가 **`/* */` 블록 주석으로 비활성화**되어 있습니다:

```javascript
// retargeting.js:320-325
// ── 이벤트 구독 (미러링 비활성화됨) ───────────
/* [2026-05-07] 실시간 미러링 기능 제외 요청으로 비활성화
window.addEventListener('itda:face:results', ...);
window.addEventListener('itda:hands:results', ...);
window.addEventListener('itda:pose:results', ...);
*/
```

`index.html:1188`에서 script 태그는 로드되지만, 리스너가 없으므로 `window.ITDARetargeting5` 객체만 노출될 뿐 **자동 실행되지 않습니다.**

**결론:** 현재 비활성 상태(데드코드). 카메라 미러링 기능을 사용하지 않으므로, 텍스트→수어 전용 시 `retargeting.js` 로드 자체를 제거해도 무방합니다.

### 13.9 handshape_loader.js 필수 여부

`motion_loader_v3.js`에서 수형 라이브러리를 직접 로드하고 사용합니다:

```javascript
// motion_loader_v3.js:62 — 자체 수형 라이브러리 로드
async function _loadHandshapeLib() { ... }

// motion_loader_v3.js:875-877 — handshape_loader.js의 ITDAHandshape 사용
if (window.ITDAHandshape) {
    if (hsRightName) window.ITDAHandshape.applyOne(avatar, hsLeftName, 'Right');
    if (hsLeftName) window.ITDAHandshape.applyOne(avatar, hsLeftName, 'Left');
}
```

`window.ITDAHandshape`는 **optional chaining**으로 호출되므로 `handshape_loader.js`가 없어도 크래시하지 않습니다. 하지만 **아바타 모션 재생 시 손가락 포즈가 적용되지 않습니다.**

**분류 수정:**
- 영상 전용 재생 → 불필요 (영상에 손가락이 이미 포함)
- 아바타 모션 재생 → 필수 (손가락 포즈 누락 시 어색한 동작)

### 13.10 `__pycache__` git tracked 문제

`.gitignore`에 `__pycache__/`가 이미 있지만, **34개 `.pyc` 파일이 이미 git에 추적**되고 있습니다. `.gitignore`는 새로 추가되는 파일만 무시하고, 이미 tracked된 파일은 영향받지 않습니다.

**근본 해결:**
```bash
git rm -r --cached **/__pycache__/
git commit -m "Remove tracked __pycache__ files"
```

### 13.11 루트 임시/기록 파일 누락

프로젝트 루트에 다음 파일들이 분류되지 않았습니다:

**임시 파일 (제거 가능):**

```
temp_thanks.json                     # 감사 모션 임시 데이터
temp_idle.json                       # 아이들 모션 임시 데이터
output_transparent.webm              # 배경 제거 테스트 출력
sample.mp4                           # 테스트 영상
화면 녹화 중 2026-05-27 092510.mp4    # 화면 녹화
db_words.json                        # DB 단어 덤프
human_proportions.json               # 인체 비율 데이터
모델변경.json                         # 모델 변경 기록
temp_bg_removal/                     # 배경 제거 작업 디렉토리 (progress 파일 유지 필요)
analyze_love_motion.py               # 일회성 분석 스크립트
```

**문서/기록물:**

```
개발진행서2026.05.22.md              # 개발 기록
개발진행서2026.05.26.md              # 개발 기록
개발진행서 2026.05.27.md             # 개발 기록
개발진행서 2026.06.01.md             # 개발 기록
ksl_word_categories.md               # 수어 단어 분류표
번역역할.md                          # 번역 역할 정의
```

**`temp_bg_removal/` 내 보존 필요 파일:**

```
progress_sldict.json                 # 배경 제거 진행 상황 (--resume용)
progress.json                        # 기존 배치 진행 상황
```

나머지 `.mp4`, `.webm`, `frames/` 등은 제거 가능.
