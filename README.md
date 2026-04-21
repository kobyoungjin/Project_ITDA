# 🤝 잇다(ITDA): AI 기반 수어 번역 및 교육 플랫폼

**최종 업데이트: 2026-04-21**

## 프로젝트 전체 진행률 (약 65%)
현재 전체 9단계 로드맵 중 6단계(STT 통합) 및 프론트-백엔드 간 AI 데이터 연동 고도화 작업이 활발히 진행 중입니다.

## 단계별 현황 및 주요 성과

### [1단계] RAG 기반 수어 지식 베이스 구축 (완료)
- KCISA 수어 API 연동 및 48종 실생활 필수 수어 데이터셋 확보 완료
- FAISS 벡터 DB 및 검색 파이프라인 정립 완료

### [2단계] MediaPipe 비전 엔진 및 리타겟팅 (완료)
- 실시간 21개 관절 추출 및 최적화(30fps 이상)
- 메타 특성(Meta Features: 손 방향, 움직임 변화량) 프론트엔드 전처리 기능 고도화 작업 중

### [3단계] SLM-RAG 하이브리드 번역 엔진 (진행/고도화)
- **3-Track 파이프라인 시스템 구축**:
  1. `Draft`: 로컬 SLM(`Ollama - Gemma3:4b`)의 초고속 단어 추측
  2. `Search`: FAISS 기반 벡터를 통한 정밀 예측
  3. `Fusion`: 추측과 감정을 융합한 온기 있는 자연어 처리 합성
- 센서 퓨전 가중치(시각 65%, 음향 35%) 및 동적 바인딩 시스템 도입

### [4단계] Three.js 3D 캐릭터 대시보드 (완료)
- ReadyPlayerMe 기반 아바타 렌더링 및 UI 레이아웃 구축 완료

### [5단계] 전문 수어 애니메이션 엔진 및 정밀 리깅 (완료)
- **쿼터니언(Quaternion) Slerp 엔진**: 오일러 각도의 짐벌 락(Gimbal Lock) 한계를 극복한 안정적인 관절 보간 렌더링
- 손가락 전마디 정밀 제어, 자동 복구(Smooth Return) 모션 완비

### [6단계] 실시간 음성 인식(STT) 통합 (진행)
- Whisper 기반 실시간 오디오 분석 및 STT 결합 멀티모달 도입 연동 중

### [9단계] 멀티 레이어 렌더링 및 서버 네트워크 최적화 (진행)
- **통신 제어**: WebSocket 500ms 주기 Throttling 적용
- **서버 부하 방어**: Session Lock 시스템을 통해 동일 세션 내 AI 연산 중복 처리 방지 설계

---

## 주요 기술 스택
- **Frontend**: Three.js, MediaPipe Face/Hand Landmarker, Vanilla JS
- **Backend/AI**: FastAPI, FAISS Vector DB, `gemma3:4b`(Ollama), Sentence-Transformers (MiniLM)
- **3D Assets**: ReadyPlayerMe GLB (Rigged & Morphable)

## 실행 가이드
- **백엔드 실행**: `.\start_backend.bat` 실행 (uvicorn 8000번 포트)
- **프론트엔드 실행**: `.\start_frontend.bat` 실행 (http-server 3000번 포트)
- **사용 방법**: 
    1. 브라우저 접속(http://localhost:3000) 후 웹캠 권한 허용
    2. 데이터가 연동되면 하단 입력창을 통한 메시지 전송 또는 자연스러운 수어 모션 테스트
    3. 아바타 모션 엔진(정밀 리깅)이 실시간 번역된 동작을 수행하는지 확인