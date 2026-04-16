/**
 * video_layer.js — 9단계: Canvas 영상 위 실시간 수어 레이어링
 * ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 * 3대 약속 #2: /static/ 폴더 안에서만 작업
 *
 * 역할:
 *   · MediaStream 의 비디오를 Canvas 에 실시간으로 그립니다.
 *   · itda:stt:sign   → 수어 단어 버블을 영상 위에 플로팅
 *   · itda:stt:text   → 하단 자막 바 표시
 *   · itda:audio:analysis → 상단 에너지 미터 + 파형 시각화
 *
 * 사용법:
 *   const layer = new VideoLayer({ canvas: document.getElementById('layer-canvas') });
 *   layer.attachStream(capture.mediaStream);   // keepVideo=true 로 캡처한 스트림
 *   layer.start();
 *   layer.stop();
 */

class VideoLayer {
  constructor({ canvas } = {}) {
    this._canvas  = canvas;
    this._ctx     = canvas.getContext('2d');
    this._videoEl = document.createElement('video');
    this._videoEl.muted    = true;
    this._videoEl.autoplay = true;
    this._videoEl.playsInline = true;

    this._active   = false;
    this._rafId    = null;

    // ── 버블 시스템 ───────────────────────────────────────
    this._bubbles  = [];      // { word, emotion_tag, x, y, born, lifetime, color }
    this._BUBBLE_LIFETIME = 3500;  // ms

    // ── 자막 ─────────────────────────────────────────────
    this._captionText  = '';
    this._captionAlpha = 0;
    this._captionTimer = null;

    // ── 오디오 분석 상태 ──────────────────────────────────
    this._energy   = 0;
    this._bands    = { bass: 0.33, mid: 0.34, high: 0.33 };
    this._waveform = new Float32Array(128);
    this._soundType  = 'silence';
    this._emotionHint = '중립';

    this._listen();
  }

  // ── 공개 API ───────────────────────────────────────────────

  /** AudioCapture.mediaStream 을 연결 (keepVideo=true 필수) */
  attachStream(stream) {
    const videoTracks = stream ? stream.getVideoTracks() : [];
    if (!videoTracks.length) {
      console.warn('[VideoLayer] 비디오 트랙 없음 — keepVideo:true 로 캡처했는지 확인');
      return;
    }
    this._videoEl.srcObject = stream;
    this._videoEl.play().catch(() => {});
  }

  start() {
    if (this._active) return;
    this._active = true;
    this._resize();
    window.addEventListener('resize', () => this._resize());
    this._renderFrame();
  }

  stop() {
    this._active = false;
    if (this._rafId) cancelAnimationFrame(this._rafId);
    this._rafId = null;
  }

  // ── 이벤트 수신 ────────────────────────────────────────────

  _listen() {
    // 수어 단어 → 버블 생성
    window.addEventListener('itda:stt:sign', (e) => {
      const { sign_terms, emotion_weight } = e.detail;
      if (!sign_terms?.length) return;
      sign_terms.forEach((term, i) => {
        this._spawnBubble(term, i, emotion_weight);
      });
    });

    // STT 텍스트 → 자막
    window.addEventListener('itda:stt:text', (e) => {
      const { text } = e.detail;
      if (text) this._setCaption(text);
    });

    // 오디오 분석 → 에너지 미터 / 파형
    window.addEventListener('itda:audio:analysis', (e) => {
      const { energy, bands, waveform, sound_type, emotion_hint } = e.detail;
      this._energy      = energy      ?? 0;
      this._bands       = bands       ?? this._bands;
      this._waveform    = waveform    ?? this._waveform;
      this._soundType   = sound_type  ?? 'silence';
      this._emotionHint = emotion_hint ?? '중립';
    });
  }

  // ── 버블 생성 ─────────────────────────────────────────────

  _spawnBubble(term, index, emotionWeight) {
    const W = this._canvas.width  || 640;
    const H = this._canvas.height || 360;

    // 버블을 화면 하단 1/3 영역에 가로로 분산 배치
    const cols  = 3;
    const col   = index % cols;
    const xBase = (W / cols) * col + (W / cols) * 0.15;
    const x     = xBase + (Math.random() - 0.5) * (W / cols * 0.3);
    const y     = H * 0.55 + (index % 2) * 60 + Math.random() * 30;

    // 감정 강도에 따른 색상
    const emotionColors = {
      '따뜻함': '#00FFB3', '온기': '#FF9F43', '격려': '#A78BFA',
      '긍정':   '#00FFB3', '동의': '#60A5FA', '중립': '#94A3B8',
      '고민':   '#FBBF24', '활기': '#FF6B6B',
    };
    const color = emotionColors[term.emotion_tag] || '#00FFB3';

    this._bubbles.push({
      word:        term.word,
      emotion_tag: term.emotion_tag || '',
      x, y,
      born:        Date.now(),
      lifetime:    this._BUBBLE_LIFETIME + index * 200,
      color,
      emotionWeight,
    });
  }

  // ── 자막 설정 ─────────────────────────────────────────────

  _setCaption(text) {
    this._captionText  = text;
    this._captionAlpha = 1.0;
    clearTimeout(this._captionTimer);
    this._captionTimer = setTimeout(() => {
      this._captionText  = '';
      this._captionAlpha = 0;
    }, 4000);
  }

  // ── 메인 렌더 루프 ────────────────────────────────────────

  _renderFrame() {
    if (!this._active) return;
    this._rafId = requestAnimationFrame(() => this._renderFrame());

    const ctx = this._ctx;
    const W   = this._canvas.width;
    const H   = this._canvas.height;

    // ① 비디오 프레임 그리기
    if (this._videoEl.readyState >= 2) {
      ctx.drawImage(this._videoEl, 0, 0, W, H);
    } else {
      ctx.fillStyle = '#060A18';
      ctx.fillRect(0, 0, W, H);
      ctx.fillStyle = '#1E293B';
      ctx.font = `${W * 0.025}px sans-serif`;
      ctx.textAlign = 'center';
      ctx.fillText('화면 공유 대기 중...', W / 2, H / 2);
    }

    // ② 상단: 에너지 미터 + 파형
    this._drawTopBar(ctx, W, H);

    // ③ 수어 버블
    this._drawBubbles(ctx, W, H);

    // ④ 하단: 자막 바
    if (this._captionText) {
      this._drawCaption(ctx, W, H);
    }

    // ⑤ 좌상단: 소리 유형 배지
    this._drawSoundBadge(ctx, W);
  }

  // ── ① 상단 에너지 바 + 파형 ────────────────────────────

  _drawTopBar(ctx, W, H) {
    const barH = Math.max(H * 0.045, 24);

    // 반투명 배경
    ctx.save();
    ctx.fillStyle = 'rgba(6, 10, 24, 0.65)';
    ctx.fillRect(0, 0, W, barH);

    // 파형
    const wH   = barH * 0.7;
    const midY = barH / 2;
    ctx.beginPath();
    ctx.strokeStyle = `rgba(0, 255, 179, ${0.3 + this._energy * 0.7})`;
    ctx.lineWidth   = 1.5;
    const step = W / this._waveform.length;
    for (let i = 0; i < this._waveform.length; i++) {
      const y = midY + this._waveform[i] * wH;
      i === 0 ? ctx.moveTo(0, y) : ctx.lineTo(i * step, y);
    }
    ctx.stroke();

    // 에너지 게이지 (우측)
    const gaugeW = W * 0.15;
    const gaugeX = W - gaugeW - 10;
    const gaugeY = barH * 0.25;
    const gaugeH = barH * 0.5;

    ctx.fillStyle = 'rgba(255,255,255,0.1)';
    ctx.beginPath();
    this._roundRect(ctx, gaugeX, gaugeY, gaugeW, gaugeH, 3);
    ctx.fill();

    const fillW = gaugeW * this._energy;
    const hue   = 120 * (1 - this._energy);   // 초록→빨강
    ctx.fillStyle = `hsla(${hue}, 100%, 60%, 0.9)`;
    ctx.beginPath();
    this._roundRect(ctx, gaugeX, gaugeY, fillW, gaugeH, 3);
    ctx.fill();

    ctx.restore();
  }

  // ── ③ 수어 버블 ──────────────────────────────────────────

  _drawBubbles(ctx, W, H) {
    const now = Date.now();
    this._bubbles = this._bubbles.filter(b => now - b.born < b.lifetime);

    for (const b of this._bubbles) {
      const age     = (now - b.born) / b.lifetime;         // 0→1
      const alpha   = age < 0.08
        ? age / 0.08
        : age > 0.75 ? 1 - (age - 0.75) / 0.25
        : 1;
      const floatY  = b.y - age * 80;     // 위로 떠오름

      // 버블 크기
      const fontSize = Math.max(W * 0.022, 14);
      const pad      = fontSize * 0.6;
      ctx.font       = `700 ${fontSize}px 'Noto Sans KR', sans-serif`;
      const wordW    = ctx.measureText(b.word).width;
      const bw       = wordW + pad * 2 + 16;
      const bh       = fontSize * 2.4;
      const bx       = Math.max(4, Math.min(b.x, W - bw - 4));
      const by       = floatY;

      ctx.save();
      ctx.globalAlpha = alpha;

      // 배경
      ctx.fillStyle = 'rgba(6, 10, 30, 0.82)';
      ctx.beginPath();
      this._roundRect(ctx, bx, by, bw, bh, 10);
      ctx.fill();

      // 테두리 (감정 색상)
      ctx.strokeStyle = b.color + 'CC';
      ctx.lineWidth   = 1.8;
      ctx.stroke();

      // 감정 색상 글로우
      ctx.shadowColor  = b.color;
      ctx.shadowBlur   = 8 * b.emotionWeight;

      // 단어
      ctx.fillStyle   = b.color;
      ctx.textAlign   = 'left';
      ctx.textBaseline = 'middle';
      ctx.fillText(b.word, bx + pad + 6, by + bh * 0.45);

      // 감정 태그 (작은 글씨)
      if (b.emotion_tag) {
        ctx.shadowBlur  = 0;
        ctx.font        = `${fontSize * 0.65}px 'Noto Sans KR', sans-serif`;
        ctx.fillStyle   = 'rgba(167, 139, 250, 0.9)';
        ctx.fillText(b.emotion_tag, bx + pad + 6, by + bh * 0.78);
      }

      ctx.restore();
    }
  }

  // ── ④ 하단 자막 바 ───────────────────────────────────────

  _drawCaption(ctx, W, H) {
    const fontSize = Math.max(W * 0.024, 15);
    const padV     = fontSize * 0.9;
    const padH     = fontSize * 1.2;
    const barH     = fontSize + padV * 2;
    const y        = H - barH - Math.max(H * 0.015, 8);

    ctx.save();
    ctx.globalAlpha = this._captionAlpha;

    // 배경
    ctx.fillStyle = 'rgba(0, 0, 0, 0.72)';
    ctx.beginPath();
    this._roundRect(ctx, W * 0.05, y, W * 0.9, barH, 8);
    ctx.fill();

    // 텍스트
    ctx.fillStyle    = '#FFFFFF';
    ctx.font         = `${fontSize}px 'Noto Sans KR', sans-serif`;
    ctx.textAlign    = 'center';
    ctx.textBaseline = 'middle';

    // 긴 텍스트 자르기
    const maxW = W * 0.88;
    let   text = this._captionText;
    while (ctx.measureText(text).width > maxW && text.length > 0) {
      text = text.slice(0, -1);
    }
    if (text !== this._captionText) text += '…';
    ctx.fillText(text, W / 2, y + barH / 2);

    ctx.restore();
  }

  // ── ⑤ 소리 유형 배지 ─────────────────────────────────────

  _drawSoundBadge(ctx, W) {
    const icons = {
      speech:  '🗣',
      music:   '🎵',
      noise:   '📢',
      silence: '🔇',
    };
    const colors = {
      speech:  'rgba(0,255,179,0.85)',
      music:   'rgba(251,191,36,0.85)',
      noise:   'rgba(255,107,107,0.85)',
      silence: 'rgba(148,163,184,0.6)',
    };
    const icon  = icons[this._soundType]  || '🔇';
    const color = colors[this._soundType] || 'rgba(148,163,184,0.6)';

    const fs = Math.max(W * 0.018, 12);
    const px = 10, py = Math.max(W * 0.045, 28);

    ctx.save();
    ctx.font         = `600 ${fs}px 'Noto Sans KR', sans-serif`;
    ctx.textBaseline = 'middle';
    ctx.textAlign    = 'left';

    const label  = `${icon} ${this._soundType}`;
    const lw     = ctx.measureText(label).width + 16;
    ctx.fillStyle = 'rgba(6,10,24,0.65)';
    ctx.beginPath();
    this._roundRect(ctx, px, py, lw, fs * 1.8, 6);
    ctx.fill();

    ctx.fillStyle = color;
    ctx.fillText(label, px + 8, py + fs * 0.9);
    ctx.restore();
  }

  // ── 유틸: 캔버스 크기 맞춤 ──────────────────────────────

  _resize() {
    const parent = this._canvas.parentElement;
    if (!parent) return;
    this._canvas.width  = parent.clientWidth;
    this._canvas.height = parent.clientHeight;
  }

  // ── 유틸: 둥근 사각형 ────────────────────────────────────

  _roundRect(ctx, x, y, w, h, r) {
    if (ctx.roundRect) {
      ctx.roundRect(x, y, w, h, r);
    } else {
      ctx.beginPath();
      ctx.moveTo(x + r, y);
      ctx.lineTo(x + w - r, y);
      ctx.quadraticCurveTo(x + w, y, x + w, y + r);
      ctx.lineTo(x + w, y + h - r);
      ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
      ctx.lineTo(x + r, y + h);
      ctx.quadraticCurveTo(x, y + h, x, y + h - r);
      ctx.lineTo(x, y + r);
      ctx.quadraticCurveTo(x, y, x + r, y);
      ctx.closePath();
    }
  }
}

window.VideoLayer = VideoLayer;
