---
title: ITDA Backend
emoji: 🤟
colorFrom: blue
colorTo: purple
sdk: docker
app_port: 7860
pinned: false
---

# ITDA Backend — Hugging Face Space

FastAPI 기반 한국 수어 인식·번역·교육 백엔드.

## 엔드포인트
- `GET /api/health` — 헬스체크
- `GET /api/sign-language/list-motions` — 학습된 단어 목록
- `WS /api/ws/vision` — 실시간 손 랜드마크 → KNN 분류
- 정적: `/static/motions/<word>.json` — 아바타 모션 데이터

## 환경 변수
| 변수 | 용도 | 예시 |
|---|---|---|
| `ITDA_CORS_ORIGINS` | 추가 CORS 도메인 | `https://my.app,https://other.app` |
| `ITDA_CORS_ORIGIN_REGEX` | Vercel 자동 패턴 | 기본값: `^https://([a-z0-9-]+\.)*vercel\.app$` |
| `PORT` | 서버 포트 | HF: `7860` |

## 운영 안내
- Hugging Face Space 의 컨테이너 사용자는 UID 1000 (`user`) — Dockerfile 의 권한 설정 일치
- 모션 데이터(`frontend/data/ksl_motions/`)는 Git LFS 로 업로드 권장 (1.8GB)
