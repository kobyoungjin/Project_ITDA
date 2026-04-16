/**
 * audio_capture.js — Web Audio API 시스템/마이크 오디오 캡처
 * ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 * 3대 약속 #2: /static/ 폴더 안에서만 작업
 *
 * 두 가지 소스 지원:
 *   · SYSTEM — getDisplayMedia() : 유튜브·앱 등 PC 재생 소리
 *   · MIC    — getUserMedia()    : 사용자 마이크
 *
 * 사용법:
 *   const cap = new AudioCapture({ onChunk, onStateChange });
 *   await cap.start('system');   // 또는 'mic'
 *   cap.stop();
 *
 * onChunk(blob, meta):
 *   blob — WebM Opus 오디오 청크 (2초)
 *   meta — { chunk_id, timestamp_ms, source, duration_ms }
 */

class AudioCapture {
  /**
   * @param {object}  opts
   * @param {function(Blob, object):void} opts.onChunk       — 청크 준비 콜백
   * @param {function(string):void}       opts.onStateChange — 'idle'|'capturing'|'error'
   * @param {number}                      [opts.chunkMs=2000] — 청크 길이(ms)
   * @param {boolean}                     [opts.keepVideo=false] — 비디오 트랙 유지 (9단계 VideoLayer 용)
   */
  constructor({ onChunk, onStateChange, chunkMs = 2000, keepVideo = false } = {}) {
    this._onChunk       = onChunk       || (() => {});
    this._onStateChange = onStateChange || (() => {});
    this._chunkMs       = chunkMs;
    this._keepVideo     = keepVideo;   // 9단계: 비디오 트랙 유지 여부

    this._stream        = null;
    this._recorder      = null;
    this._chunkId       = 0;
    this._source        = 'system';
    this._state         = 'idle';   // 'idle' | 'capturing' | 'error'
  }

  // ── 공개 API ───────────────────────────────────────────────

  /** 캡처 시작
   * @param {'system'|'mic'} source
   */
  async start(source = 'system') {
    if (this._state === 'capturing') return;
    this._source  = source;
    this._chunkId = 0;

    try {
      this._stream = source === 'system'
        ? await this._getSystemAudio()
        : await this._getMicAudio();

      this._startRecorder();
      this._setState('capturing');
    } catch (err) {
      this._setState('error');
      console.error('[AudioCapture] 시작 오류:', err);
      throw err;
    }
  }

  /** 캡처 중지 */
  stop() {
    if (this._recorder && this._recorder.state !== 'inactive') {
      this._recorder.stop();
    }
    if (this._stream) {
      this._stream.getTracks().forEach(t => t.stop());
      this._stream = null;
    }
    this._recorder = null;
    this._setState('idle');
  }

  get state()       { return this._state;   }
  get source()      { return this._source;  }
  /** 9단계 VideoLayer 가 비디오 트랙을 꺼내 쓸 수 있도록 스트림 노출 */
  get mediaStream() { return this._stream;  }

  // ── 오디오 소스 획득 ──────────────────────────────────────

  /** 시스템 오디오 (유튜브 등 PC 재생 소리) */
  async _getSystemAudio() {
    // Chrome: getDisplayMedia 로 탭/시스템 오디오 캡처
    // 사용자가 "탭 오디오 공유" 선택 시 소리 캡처 가능
    const stream = await navigator.mediaDevices.getDisplayMedia({
      audio: {
        echoCancellation:  false,
        noiseSuppression:  false,
        autoGainControl:   false,
        sampleRate:        44100,
      },
      video: {
        width:  { ideal: 1 },    // 최소 해상도 (영상은 필요 없음)
        height: { ideal: 1 },
        frameRate: { ideal: 1 },
      },
    });

    // keepVideo=false(기본): 비디오 트랙 제거 — 오디오만 전송
    // keepVideo=true  (9단계): 비디오 트랙 유지 — VideoLayer 가 사용
    if (!this._keepVideo) {
      stream.getVideoTracks().forEach(t => {
        t.stop();
        stream.removeTrack(t);
      });
    }

    if (stream.getAudioTracks().length === 0) {
      throw new Error(
        '시스템 오디오 트랙이 없습니다.\n' +
        '"탭 오디오 공유" 또는 "전체 화면 공유 + 오디오 공유"를 선택해 주세요.'
      );
    }
    return stream;
  }

  /** 마이크 오디오 */
  async _getMicAudio() {
    return navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl:  true,
        sampleRate:       44100,
        channelCount:     1,   // 모노
      },
      video: false,
    });
  }

  // ── MediaRecorder 설정 ────────────────────────────────────

  _startRecorder() {
    // 지원 MIME 타입 우선순위 탐색
    const mimeType = this._getSupportedMime();
    const options  = { mimeType, audioBitsPerSecond: 32000 };

    this._recorder = new MediaRecorder(this._stream, options);

    this._recorder.ondataavailable = (e) => {
      if (e.data && e.data.size > 0) {
        this._emitChunk(e.data);
      }
    };

    this._recorder.onerror = (e) => {
      console.error('[AudioCapture] MediaRecorder 오류:', e.error);
      this._setState('error');
    };

    this._recorder.onstop = () => {
      this._setState('idle');
    };

    // timeslice: 매 N ms 마다 ondataavailable 발생
    this._recorder.start(this._chunkMs);
  }

  _getSupportedMime() {
    const candidates = [
      'audio/webm;codecs=opus',
      'audio/webm',
      'audio/ogg;codecs=opus',
    ];
    return candidates.find(m => MediaRecorder.isTypeSupported(m)) || '';
  }

  _emitChunk(blob) {
    const meta = {
      chunk_id:     this._chunkId++,
      timestamp_ms: performance.now(),
      source:       this._source,
      duration_ms:  this._chunkMs,
    };
    this._onChunk(blob, meta);
  }

  _setState(state) {
    this._state = state;
    this._onStateChange(state);
  }
}

// 전역 노출
window.AudioCapture = AudioCapture;
