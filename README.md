# 🤝 잇다(ITDA): AI 기반 수어 번역 및 교육 플랫폼

**최종 업데이트: 2026-04-16**

## 프로젝트 단계별 현황

### [1단계] RAG 기반 수어 지식 베이스 구축 (완료)
- KCISA 수어 API 연동 및 48종 실생활 필수 수어 데이터셋 확보
- FAISS 벡터 DB 및 SentenceTransformer 기반 검색 파이프라인 구축

### [2단계] MediaPipe 비전 엔진 및 리타겟팅 (완료)
- 실시간 21개 관절 추출 및 최적화(11개 핵심 관절)
- 고속 WebSocket 통신 (30fps+) 및 Lerp 보간 렌더링

### [3단계] SLM-RAG 하이브리드 번역 엔진 (완료)
- **전략**: 로컬 SLM(Phi-3)의 즉각적 1차 예측 + 서버 RAG의 정밀 보정
- **최적화**: 경량 임베딩 모델(`MiniLM`) 전환으로 분석 속도 70% 단축 및 인덱스 캐싱 적용

### [4단계] Three.js 3D 캐릭터 대시보드 (완료)
- ReadyPlayerMe 기반 고품질 아바타(`female_human.glb`) 렌더링
- PIP 교육 영상 플레이어 및 하이브리드 번역 시각화 UI 고도화

### [5단계] 전문 수어 애니메이션 엔진 및 정밀 리깅 (완료 - 2026-04-16) ✨
- **쿼터니언(Quaternion) Slerp 엔진**: 오일러 각도의 한계를 극복한 안정적 관절 보간 시스템
- **정밀 리깅 시스템**: 손가락 전마디(30개 이상), 척추, 목, 어깨 등 전신 관절 정교화
- **지능형 복구**: 수어 동작 종료 후 부드러운 자동 복구(Smooth Return) 및 웹캠 제어권 자동 반환
- **모션 라이브러리**: 국립수어박물관 지침을 준수하는 48개 핵심 전문 수어 동작 프로필 구축

---

## 주요 기술 스택
- **Frontend**: Three.js, MediaPipe Face/Hand Landmarker, Vanilla JS
- **Backend**: FastAPI, FAISS Vector DB, Sentence-Transformers (MiniLM)
- **3D Assets**: ReadyPlayerMe GLB (Rigged & Morphable)

## 실행 가이드
- **백엔드 실행**: `.\start_backend.bat` 실행 (uvicorn 8000번 포트)
- **프론트엔드 실행**: `.\start_frontend.bat` 실행 (http-server 8080번 포트)
- **사용 방법**: 
    1. 브라우저 접속 후 웹캠 권한 허용
    2. 하단 입력창에 '안녕하세요', '고맙습니다' 등 입력 또는 음성 인식
    3. 아바타가 웹캠 제어를 멈추고 전문 수어 동작을 수행하는지 확인