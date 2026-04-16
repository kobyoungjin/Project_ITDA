/**
 * audio_analyzer.js — 9단계: 브라우저 실시간 오디오 분석 (Web Audio API)
 * ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 * 3대 약속 #2: /static/ 폴더 안에서만 작업
 *
 * 서버(librosa)와 독립적으로 브라우저에서 실시간 FFT 분석을 수행합니다.
 * 매 200ms 마다 분석 결과를 이벤트로 브로드캐스트합니다.
 *
 * 발행 이벤트:
 *   itda:audio:analysis — {
 *     energy,          // 0~1  전체 에너지
 *     bands: { bass, mid, high },  // 0~1 각 대역 에너지
 *     sound_type,      // 'silence'|'speech'|'music'|'noise'
 *     emotion_hint,    // '차분'|'활기'|'긴장'|'중립'
 *     waveform,        // Float32Array (시각화용 파형 데이터)
 *   }
 *
 * 사용법:
 *   const analyzer = new BrowserAudioAnalyzer({ stream });
 *   analyzer.start();
 *   analyzer.stop();
 */

class BrowserAudioAnalyzer {
  /**
   * @param {object}      opts
   * @param {MediaStream} opts.stream       — 분석할 오디오 스트림
   * @param {number}      [opts.intervalMs=200] — 분석 주기 (ms)
   * @param {number}      [opts.fftSize=2048]   — FFT 크기
   */
  constructor({ stream, intervalMs = 200, fftSize = 2048 } = {}) {
    this._stream     = stream;
    this._intervalMs = intervalMs;
    this._fftSize    = fftSize;

    this._ctx        = null;
    this._analyser   = null;
    this._source     = null;
    this._timer      = null;
    this._active     = false;

    // 분석 버퍼
    this._freqData   = null;   // Uint8Array — 주파수 데이터
    this._timeData   = null;   // Uint8Array — 파형 데이터
  }

  // ── 공개 API ───────────────────────────────────────────────

  start() {
    if (this._active) return;
    this._setup();
    this._active = true;
    this._timer  = setInterval(() => this._analyze(), this._intervalMs);
  }

  stop() {
    this._active = false;
    clearInterval(this._timer);
    this._timer = null;

    if (this._source) { try { this._source.disconnect(); } catch {} }
    if (this._ctx)    { try { this._ctx.close();          } catch {} }
    this._ctx = this._analyser = this._source = null;
  }

  // ── Web Audio API 초기화 ──────────────────────────────────

  _setup() {
    try {
      this._ctx      = new (window.AudioContext || window.webkitAudioContext)();
      this._analyser = this._ctx.createAnalyser();

      this._analyser.fftSize             = this._fftSize;
      this._analyser.smoothingTimeConstant = 0.8;  // 부드러운 애니메이션

      this._source   = this._ctx.createMediaStreamSource(this._stream);
      this._source.connect(this._analyser);
      // 스피커 출력 없이 분석만 — 연결 끊음

      this._freqData = new Uint8Array(this._analyser.frequencyBinCount);
      this._timeData = new Uint8Array(this._fftSize);

    } catch (err) {
      console.error('[AudioAnalyzer] Web Audio API 초기화 오류:', err);
    }
  }

  // ── 분석 루프 ─────────────────────────────────────────────

  _analyze() {
    if (!this._analyser) return;

    this._analyser.getByteFrequencyData(this._freqData);
    this._analyser.getByteTimeDomainData(this._timeData);

    const sr      = this._ctx.sampleRate;          // 보통 44100 또는 48000
    const binHz   = sr / this._fftSize;            // Hz/bin
    const N       = this._freqData.length;

    // ── 주파수 대역 경계 빈 인덱스 ────────────────────────
    const bassEnd  = Math.floor(300   / binHz);
    const midEnd   = Math.floor(4000  / binHz);
    const highEnd  = Math.min(Math.floor(8000 / binHz), N - 1);

    const bassE = this._bandEnergy(0,        bassEnd);
    const midE  = this._bandEnergy(bassEnd,  midEnd);
    const highE = this._bandEnergy(midEnd,   highEnd);
    const total = bassE + midE + highE + 1e-9;

    const bands = {
      bass: bassE / total,
      mid:  midE  / total,
      high: highE / total,
    };

    // ── 전체 에너지 (RMS 근사) ────────────────────────────
    let sumSq = 0;
    for (let i = 0; i < N; i++) {
      const v = (this._freqData[i] / 255);
      sumSq += v * v;
    }
    const energy = Math.min(Math.sqrt(sumSq / N) * 3.5, 1.0);

    // ── 소리 유형 분류 ────────────────────────────────────
    const sound_type   = this._classifySoundType(energy, bands);
    const emotion_hint = this._emotionHint(sound_type, energy);

    // ── 파형 데이터 (Float32, -1~1) ───────────────────────
    const waveform = new Float32Array(128);   // 다운샘플
    const step     = Math.floor(this._fftSize / 128);
    for (let i = 0; i < 128; i++) {
      waveform[i] = (this._timeData[i * step] / 128.0) - 1.0;
    }

    window.dispatchEvent(new CustomEvent('itda:audio:analysis', {
      detail: { energy, bands, sound_type, emotion_hint, waveform },
    }));
  }

  // ── 대역 에너지 평균 ──────────────────────────────────────
  _bandEnergy(startBin, endBin) {
    let sum = 0;
    const count = endBin - startBin;
    if (count <= 0) return 0;
    for (let i = startBin; i < endBin; i++) {
      sum += this._freqData[i] / 255;
    }
    return sum / count;
  }

  // ── 소리 유형 분류 (브라우저 측 경량 버전) ────────────────
  _classifySoundType(energy, bands) {
    if (energy < 0.05) return 'silence';
    // 음악: 저음 비중 높고 에너지 고름
    if (bands.bass > 0.35 && energy > 0.15) return 'music';
    // 음성: 중음 비중 높음
    if (bands.mid > 0.45) return 'speech';
    return 'noise';
  }

  _emotionHint(soundType, energy) {
    if (soundType === 'silence') return '중립';
    if (energy < 0.15) return '차분';
    if (energy < 0.50) return (soundType === 'music') ? '활기' : '차분';
    return '긴장';
  }
}

window.BrowserAudioAnalyzer = BrowserAudioAnalyzer;
