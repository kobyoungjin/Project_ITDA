/**
 * stt-adapter.js ─ [③ STT] Web Speech API primary + Whisper WS fallback 어댑터
 *
 * 목표: translator.js 의 mic 버튼 하나로 두 경로를 투명하게 처리.
 *
 * 결정 사항(2026-04-22):
 *   - Web Speech API (브라우저 내장) 를 **1순위** 로 사용 (Chrome/Edge 즉시 동작, 추가 설치 0)
 *   - SpeechRecognition 미지원 시 자동으로 Whisper(backend `/api/ws/stt`) 로 폴백
 *     → Firefox/Safari 에서도 음성 입력이 끊기지 않음
 *
 * 발행 이벤트 (window):
 *   itda:stt:transcript — { text, source: 'web-speech'|'whisper' }
 *     translator.js 는 이 단일 이벤트만 구독해 sendMessage(text) 호출
 *   itda:stt:state      — 'idle' | 'listening' | 'error'
 *
 * 공개 API:
 *   window.ITDAStt = { isActive, toggle(), getSource() }
 */

(() => {
  const WS_URL = `ws://${location.hostname}:8000/api/ws/stt`;

  // ── 1순위: Web Speech API ──────────────────────────────────
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  const hasWebSpeech = !!SpeechRecognition;

  let recognition = null;
  let active = false;
  let source = hasWebSpeech ? 'web-speech' : 'whisper';

  // ── Web Speech 경로 ────────────────────────────────────────
  function _initWebSpeech() {
    recognition = new SpeechRecognition();
    recognition.lang = 'ko-KR';
    recognition.continuous = false;
    recognition.interimResults = false;

    recognition.onstart = () => {
      active = true;
      _emitState('listening');
    };
    recognition.onresult = (evt) => {
      const text = evt.results[0][0].transcript;
      _emitTranscript(text, 'web-speech');
    };
    recognition.onerror = (evt) => {
      console.error('[STT Adapter] Web Speech 오류:', evt.error);
      _emitState('error');
      active = false;
    };
    recognition.onend = () => {
      active = false;
      _emitState('idle');
    };
  }

  // ── 2순위: Whisper WebSocket + MediaRecorder 경로 ──────────
  // audio_capture.js / stt_client.js 가 먼저 로드되어 있어야 함
  let whisper = null;  // { client, capture }

  async function _startWhisper() {
    if (!window.STTClient || !window.AudioCapture) {
      console.error('[STT Adapter] STTClient/AudioCapture 미로드');
      _emitState('error');
      return;
    }
    if (whisper) return;

    const client = new STTClient({ wsUrl: WS_URL });
    client.connect();

    // Whisper 응답 수신 → transcript 이벤트로 통일
    window.addEventListener('itda:stt:text', (e) => {
      const txt = (e.detail?.text || '').trim();
      if (txt) _emitTranscript(txt, 'whisper');
    });

    const capture = new AudioCapture({
      chunkMs: 2500,
      onChunk: (blob, meta) => client.sendChunk(blob, meta),
      onStateChange: (st) => {
        if (st === 'capturing') _emitState('listening');
        else if (st === 'error') _emitState('error');
        else _emitState('idle');
      },
    });

    try {
      await capture.start('mic');
      whisper = { client, capture };
      active = true;
    } catch (err) {
      console.error('[STT Adapter] Whisper 경로 시작 실패:', err);
      _emitState('error');
    }
  }

  function _stopWhisper() {
    if (!whisper) return;
    try { whisper.capture.stop(); } catch (_) {}
    try { whisper.client.disconnect(); } catch (_) {}
    whisper = null;
    active = false;
    _emitState('idle');
  }

  // ── 공통 이벤트 ────────────────────────────────────────────
  function _emitState(state) {
    window.dispatchEvent(new CustomEvent('itda:stt:state', { detail: state }));
  }
  function _emitTranscript(text, src) {
    window.dispatchEvent(new CustomEvent('itda:stt:transcript', {
      detail: { text, source: src },
    }));
  }

  // ── 초기화 ─────────────────────────────────────────────────
  if (hasWebSpeech) _initWebSpeech();

  // ── 공개 API ───────────────────────────────────────────────
  window.ITDAStt = {
    get isActive() { return active; },
    getSource()    { return source; },

    toggle() {
      if (source === 'web-speech') {
        if (active) recognition.stop();
        else {
          try { recognition.start(); }
          catch (e) { console.warn('[STT Adapter] Web Speech start 실패:', e); }
        }
      } else {
        if (active) _stopWhisper();
        else _startWhisper();
      }
    },
  };

  console.info(`[STT Adapter] 준비 완료 — 경로: ${source}`);
})();
