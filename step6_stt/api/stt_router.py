"""
stt_router.py - 6단계: Whisper STT WebSocket 라우터
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
3대 약속 #2: /api/ 폴더 안에서만 작업
3대 약속 #3: 포트 8000 에서 서비스

WebSocket 엔드포인트: ws://<host>:8000/api/ws/stt

프로토콜:
  클라이언트 → 서버:
    [텍스트 JSON] AudioMeta  →  [바이너리] WebM Opus 오디오
  서버 → 클라이언트:
    [텍스트 JSON] STTResponse
"""

import json
import logging
import os
import tempfile
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from rag_bridge import search_sign_language
from schema import AudioMeta, STTResponse

logger = logging.getLogger("itda.stt")

stt_router = APIRouter(prefix="/api", tags=["STT (6단계)"])


# ── Whisper 모델 싱글톤 ───────────────────────────────────────
# 앱 시작 시 한 번만 로드 (요청마다 로드하면 너무 느림)
_whisper_model = None

def get_whisper_model():
    global _whisper_model
    if _whisper_model is None:
        try:
            from faster_whisper import WhisperModel
            logger.info("[Whisper] faster-whisper 모델 로딩 중 (base, cpu, int8) ...")
            _whisper_model = WhisperModel(
                "base",
                device="cpu",
                compute_type="int8",  # CPU 최적화
            )
            logger.info("[Whisper] 모델 로딩 완료")
        except ImportError:
            logger.warning("[Whisper] faster-whisper 미설치 → 더미 모드로 실행")
            _whisper_model = _DummyWhisper()
    return _whisper_model


class _DummyWhisper:
    """faster-whisper 미설치 시 텍스트 없이 동작하는 더미"""
    def transcribe(self, audio_path, **kwargs):
        return [type("seg", (), {"text": "[Whisper 미설치 — pip install faster-whisper]"})()], {}


def _transcribe(audio_path: str) -> tuple[str, float]:
    """
    오디오 파일을 Whisper로 텍스트 변환합니다.

    Returns:
        (text, confidence) — confidence 는 0~1 근사값
    """
    model = get_whisper_model()
    try:
        segments, info = model.transcribe(
            audio_path,
            language="ko",          # 한국어 고정 (자동 감지보다 빠름)
            beam_size=3,            # 실시간용: 속도↑ 정확도 약간↓
            vad_filter=True,        # 묵음 구간 자동 제거
            vad_parameters={
                "min_silence_duration_ms": 500,
            },
        )
        texts = [seg.text.strip() for seg in segments if seg.text.strip()]
        full_text = " ".join(texts)
        # faster-whisper 는 segment 별 avg_logprob 로 신뢰도 근사
        confidence = 0.85 if full_text else 0.0
        return full_text, confidence
    except Exception as e:
        logger.error(f"[Whisper] 전사 오류: {e}")
        return "", 0.0


# ── 연결 관리 ───────────────────────────────────────────────
class STTConnectionManager:
    def __init__(self):
        self.sessions: dict[str, WebSocket] = {}

    def register(self, session_id: str, ws: WebSocket):
        self.sessions[session_id] = ws
        logger.info(f"[STT] 연결: {session_id}  (총 {len(self.sessions)}개)")

    def unregister(self, session_id: str):
        self.sessions.pop(session_id, None)
        logger.info(f"[STT] 해제: {session_id}  (총 {len(self.sessions)}개)")

    async def send(self, session_id: str, response: STTResponse):
        ws = self.sessions.get(session_id)
        if ws:
            await ws.send_text(response.model_dump_json())


_mgr = STTConnectionManager()


# ── WebSocket 엔드포인트 ─────────────────────────────────────
@stt_router.websocket("/ws/stt")
async def stt_websocket(ws: WebSocket):
    """
    오디오 스트림 수신 → Whisper STT → RAG 수어 검색 → 결과 반환

    클라이언트는 매 청크마다:
      1. AudioMeta JSON 텍스트 프레임 전송
      2. WebM Opus 바이너리 프레임 전송
    """
    await ws.accept()
    session_id = f"stt_{int(time.time())}"
    pending_meta: AudioMeta | None = None  # 대기 중인 메타데이터

    try:
        while True:
            message = await ws.receive()

            # ── 텍스트 프레임: AudioMeta ─────────────────────
            if "text" in message:
                try:
                    data = json.loads(message["text"])
                    meta = AudioMeta(**data)
                    session_id = meta.session_id
                    _mgr.register(session_id, ws)
                    pending_meta = meta
                    logger.debug(f"[STT] 메타 수신: chunk={meta.chunk_id} src={meta.source}")
                except Exception as e:
                    logger.warning(f"[STT] 메타 파싱 오류: {e}")

            # ── 바이너리 프레임: 오디오 데이터 ───────────────
            elif "bytes" in message:
                audio_bytes: bytes = message["bytes"]

                if not audio_bytes:
                    continue

                chunk_id   = pending_meta.chunk_id if pending_meta else 0
                t_start    = time.perf_counter()

                # 임시 파일에 WebM 저장 → Whisper 처리
                tmp_path = None
                try:
                    with tempfile.NamedTemporaryFile(
                        suffix=".webm", delete=False
                    ) as tmp:
                        tmp.write(audio_bytes)
                        tmp_path = tmp.name

                    # ① STT
                    text, confidence = _transcribe(tmp_path)

                    # ② RAG 수어 검색
                    if text:
                        sign_terms, emotion_weight = await search_sign_language(
                            session_id, text
                        )
                        rag_status = "ok" if sign_terms else "no_result"
                    else:
                        sign_terms, emotion_weight = [], 0.3
                        rag_status = "no_result"

                    process_ms = (time.perf_counter() - t_start) * 1000

                    logger.info(
                        f"[STT] chunk={chunk_id}  text='{text[:30]}'  "
                        f"signs={len(sign_terms)}  {process_ms:.0f}ms"
                    )

                    # ③ 응답 전송
                    response = STTResponse(
                        session_id=session_id,
                        chunk_id=chunk_id,
                        text=text,
                        confidence=confidence,
                        sign_terms=sign_terms,
                        emotion_weight=emotion_weight,
                        rag_status=rag_status,
                        process_ms=process_ms,
                    )
                    await _mgr.send(session_id, response)

                except Exception as e:
                    logger.error(f"[STT] 처리 오류: {e}", exc_info=True)
                    err_resp = STTResponse(
                        session_id=session_id,
                        chunk_id=chunk_id,
                        status="error",
                        error_msg=str(e),
                    )
                    await _mgr.send(session_id, err_resp)
                finally:
                    # 임시 파일 정리
                    if tmp_path and os.path.exists(tmp_path):
                        try:
                            os.unlink(tmp_path)
                        except OSError:
                            pass

                pending_meta = None  # 메타 소비 후 초기화

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"[STT] WebSocket 오류: {e}", exc_info=True)
    finally:
        _mgr.unregister(session_id)


# ── REST: 모델 상태 확인 ─────────────────────────────────────
@stt_router.get("/status/stt")
async def stt_status():
    model = get_whisper_model()
    return {
        "model_loaded": model is not None and not isinstance(model, _DummyWhisper),
        "model_type":   "faster-whisper base" if not isinstance(model, _DummyWhisper) else "dummy",
        "active_sessions": len(_mgr.sessions),
        "websocket_url": "ws://<host>:8000/api/ws/stt",
    }
