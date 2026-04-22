/**
 * stt_client.js — WebSocket STT 클라이언트
 * ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 * 3대 약속 #2: /static/ 폴더 안에서만 작업
 * 3대 약속 #1: 서버와 주고받는 JSON 구조 = schema.py 기준
 *
 * 역할:
 *   · AudioCapture 의 onChunk 콜백을 받아 WebSocket 으로 서버 전송
 *   · 서버 응답(STTResponse)을 파싱해 커스텀 이벤트로 브로드캐스트
 *
 * 발행 이벤트 (window):
 *   itda:stt:text   — { text, confidence, language, chunk_id }
 *   itda:stt:sign   — { sign_terms, emotion_weight, rag_status, chunk_id }
 *   itda:stt:error  — { error_msg }
 *   itda:ws:open    — WebSocket 연결됨
 *   itda:ws:close   — WebSocket 끊김
 *
 * 사용법:
 *   const client = new STTClient({ wsUrl: 'ws://localhost:8000/api/ws/stt' });
 *   client.connect();
 *   // AudioCapture 와 연결
 *   const cap = new AudioCapture({ onChunk: (blob, meta) => client.sendChunk(blob, meta) });
 */

class STTClient {
  /**
   * @param {object} opts
   * @param {string} opts.wsUrl        — WebSocket URL
   * @param {string} [opts.sessionId]  — 세션 ID (미지정 시 자동 생성)
   */
  constructor({ wsUrl, sessionId } = {}) {
    this._wsUrl     = wsUrl || `ws://${location.host}/api/ws/stt`;
    this._sessionId = sessionId || `web_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`;
    this._ws        = null;
    this._connected = false;
    this._reconnectTimer = null;
    this._reconnectDelay = 3000;  // ms
  }

  // ── 공개 API ───────────────────────────────────────────────

  get sessionId()  { return this._sessionId; }
  get connected()  { return this._connected; }

  /** WebSocket 연결 */
  connect() {
    if (this._ws && this._ws.readyState === WebSocket.OPEN) return;
    this._openWS();
  }

  /** WebSocket 해제 */
  disconnect() {
    clearTimeout(this._reconnectTimer);
    if (this._ws) {
      this._ws.onclose = null;  // 재연결 방지
      this._ws.close();
      this._ws = null;
    }
    this._connected = false;
  }

  /**
   * 오디오 청크 전송
   * schema.py 프로토콜:
   *   Frame-1 (JSON text) : AudioMeta
   *   Frame-2 (binary)    : WebM Opus
   *
   * @param {Blob}   blob — MediaRecorder 오디오 청크
   * @param {object} meta — { chunk_id, timestamp_ms, source, duration_ms }
   */
  async sendChunk(blob, meta) {
    if (!this._connected || !this._ws) {
      console.warn('[STTClient] 연결되지 않음 — 청크 건너뜀');
      return;
    }

    try {
      // Frame-1: 메타데이터 JSON
      const audioMeta = {
        session_id:   this._sessionId,
        chunk_id:     meta.chunk_id,
        timestamp_ms: meta.timestamp_ms,
        source:       meta.source || 'system',
        duration_ms:  meta.duration_ms || 2000,
      };
      this._ws.send(JSON.stringify(audioMeta));

      // Frame-2: 바이너리 오디오
      const arrayBuffer = await blob.arrayBuffer();
      this._ws.send(arrayBuffer);

    } catch (err) {
      console.error('[STTClient] 전송 오류:', err);
    }
  }

  // ── WebSocket 내부 ─────────────────────────────────────────

  _openWS() {
    try {
      this._ws = new WebSocket(this._wsUrl);
      this._ws.binaryType = 'arraybuffer';

      this._ws.onopen = () => {
        this._connected = true;
        clearTimeout(this._reconnectTimer);
        console.log(`[STTClient] 연결됨: ${this._wsUrl}`);
        window.dispatchEvent(new CustomEvent('itda:ws:open', {
          detail: { sessionId: this._sessionId },
        }));
      };

      this._ws.onmessage = (e) => {
        if (typeof e.data === 'string') {
          this._handleResponse(e.data);
        }
      };

      this._ws.onerror = (e) => {
        console.error('[STTClient] WebSocket 오류:', e);
      };

      this._ws.onclose = () => {
        this._connected = false;
        console.warn('[STTClient] 연결 끊김 — 재연결 시도...');
        window.dispatchEvent(new CustomEvent('itda:ws:close'));
        // 자동 재연결
        this._reconnectTimer = setTimeout(() => this._openWS(), this._reconnectDelay);
      };

    } catch (err) {
      console.error('[STTClient] WebSocket 생성 오류:', err);
    }
  }

  _handleResponse(jsonText) {
    let resp;
    try {
      resp = JSON.parse(jsonText);
    } catch {
      console.warn('[STTClient] JSON 파싱 오류:', jsonText);
      return;
    }

    if (resp.status === 'error') {
      window.dispatchEvent(new CustomEvent('itda:stt:error', {
        detail: { error_msg: resp.error_msg },
      }));
      return;
    }

    // ① STT 텍스트 이벤트
    if (resp.text !== undefined) {
      window.dispatchEvent(new CustomEvent('itda:stt:text', {
        detail: {
          text:       resp.text,
          confidence: resp.confidence,
          language:   resp.language,
          chunk_id:   resp.chunk_id,
          process_ms: resp.process_ms,
        },
      }));
    }

    // ② 수어 검색 이벤트
    if (Array.isArray(resp.sign_terms)) {
      window.dispatchEvent(new CustomEvent('itda:stt:sign', {
        detail: {
          sign_terms:    resp.sign_terms,
          emotion_weight: resp.emotion_weight,
          rag_status:    resp.rag_status,
          chunk_id:      resp.chunk_id,
          query_text:    resp.text,
        },
      }));
    }
  }
}

// 전역 노출
window.STTClient = STTClient;
