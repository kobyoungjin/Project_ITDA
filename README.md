# 🤝 잇다(ITDA): AI 기반 수어 번역 및 교육 플랫폼

## 프로젝트 단계별 현황

### [1단계] RAG 기반 수어 지식 베이스 구축 (완료)
- KCISA 수어 API 연동
- FAISS 벡터 DB 및 Gemini RAG 파이프라인 구축

### [2단계] MediaPipe 비전 엔진 (완료)
- 실시간 21개 관절 추출 및 최적화(11개 핵심 관절)
- 고속 WebSocket 통신 (30fps+)

### [3단계] SLM-RAG 하이브리드 번역 엔진 (설계 완료 / 통합 대기)
- **전략**: 로컬 SLM(Phi-3)의 즉각적 1차 예측 + 서버 RAG의 정밀 보정
- **인터페이스**: 아바타 및 UI와의 연동 브릿지 설계 완료

### [4단계] Three.js 3D 캐릭터 및 실시간 리타겟팅 (완료)
- [NEW] Three.js 기반 아바타(`Xbot.glb`) 렌더링
- [NEW] 실시간 관절 리타겟팅(Retargeting) 및 Lerp 보간
- [NEW] PIP 교육 영상 플레이어 및 하이브리드 번역 시각화 UI

---

## 실행 가이드
- **2단계 테스트**: `step2_mediapipe/backend`에서 uvicorn 실행 후 `static/index.html` 접속
- **4단계 테스트**: `step4_threejs/frontend/index.html` 파일을 브라우저로 열기 (CDN 기반으로 즉시 확인 가능)