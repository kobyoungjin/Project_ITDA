# step6_stt/static/js/ — 🗂️ 보관용

> **2026-04-22: 이 디렉토리의 JS 는 더 이상 canonical 경로가 아닙니다.**

## canonical 위치

프로덕션 프론트엔드에서 사용되는 STT 자산은 모두 아래 경로에 있습니다:

```
frontend/js/stt/
  ├─ audio_capture.js   ← 이 파일의 최신 사본
  ├─ stt_client.js      ← 이 파일의 최신 사본
  └─ stt-adapter.js     ← (신규) Web Speech / Whisper 통합 게이트웨이
```

`frontend/index.html` 이 `./js/stt/*.js` 를 직접 로드하며,
`translator.js` 는 `window.ITDAStt.toggle()` 을 통해 두 경로를 투명하게 사용합니다.

## 이 디렉토리를 유지하는 이유

- step6_stt 는 원래 포트 8000 독립 실행용 프로젝트로 개발됨
- 연구/테스트용 `step6_stt/static/index.html` 데모가 아직 이 경로를 참조
- 파일 자체를 삭제하면 과거 브랜치/PR에서 깨질 수 있어 **보관**

## 수정 시 주의사항

`audio_capture.js` 또는 `stt_client.js` 를 **절대 여기서 편집하지 마세요**.
편집은 `frontend/js/stt/` 에서 진행하고, 필요 시 여기로 복사하세요.

## 제거 조건

- `step6_stt/static/index.html` 데모를 더 이상 사용하지 않기로 결정
- 또는 `step6_stt/static/` 전체를 `archive/` 로 이동 결정

## 관련 의사결정 기록

- **ADR-2026-04-22**: Web Speech API 를 1순위로 유지, Whisper (backend `/api/ws/stt`) 는 폴백.
  → 근거: Chrome/Edge 에서 추가 설치 없이 즉시 동작, 대역폭 0.
  → Firefox/Safari: SpeechRecognition 미지원이므로 자동으로 Whisper 로 폴백.
