/**
 * pip_overlay.js — PIP 플로팅 수어 통역 윈도우
 * ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 * 3대 약속 #2: /static/ 폴더 안에서만 작업
 *
 * 역할:
 *   · itda:stt:text  이벤트 → 실시간 자막(Caption) 표시
 *   · itda:stt:sign  이벤트 → 수어 카드 렌더링
 *   · 4단계(Three.js 아바타) 연동: itda:sign:perform 이벤트 발행
 *
 * 4단계 아바타 연동 방법:
 *   step4_threejs/frontend/js/avatar.js 에서
 *   window.addEventListener('itda:sign:perform', (e) => {
 *     const { word, emotion_weight } = e.detail;
 *     // 아바타 수어 동작 실행
 *   });
 */

class PIPOverlay {
  /**
   * @param {object} opts
   * @param {HTMLElement} opts.container  — PIP 루트 엘리먼트
   */
  constructor({ container } = {}) {
    this._root      = container || document.getElementById('pip-root');
    this._visible   = true;
    this._captions  = [];       // 최근 자막 버퍼 (최대 3줄)
    this._maxCaptions = 3;

    this._captionEl  = null;
    this._signListEl = null;
    this._avatarEl   = null;

    this._build();
    this._listen();
  }

  // ── 공개 API ───────────────────────────────────────────────

  show() {
    this._root.style.display = '';
    this._visible = true;
  }

  hide() {
    this._root.style.display = 'none';
    this._visible = false;
  }

  toggle() {
    this._visible ? this.hide() : this.show();
  }

  /** 자막 직접 추가 (외부 호출용) */
  addCaption(text, confidence = 1.0) {
    if (!text || !text.trim()) return;
    this._pushCaption(text.trim(), confidence);
  }

  /** 수어 카드 직접 렌더링 (외부 호출용) */
  showSignTerms(signTerms, emotionWeight = 0.5) {
    this._renderSignCards(signTerms, emotionWeight);
  }

  // ── DOM 구성 ───────────────────────────────────────────────

  _build() {
    // pip-root 내부를 동적으로 구성
    this._root.innerHTML = `
      <!-- 아바타 뷰포트 (4단계 Three.js 연동) -->
      <div class="pip-avatar" id="pip-avatar-zone">
        <div class="pip-avatar-placeholder">
          <div class="avatar-icon">🤖</div>
          <span class="avatar-hint">4단계 3D 아바타 연동 영역</span>
        </div>
      </div>

      <!-- 실시간 자막 -->
      <div class="pip-captions" id="pip-captions">
        <div class="caption-label">실시간 인식</div>
        <div class="caption-lines" id="caption-lines">
          <div class="caption-empty">소리를 캡처하면 자막이 표시됩니다...</div>
        </div>
      </div>

      <!-- 수어 단어 카드 -->
      <div class="pip-signs" id="pip-signs">
        <div class="signs-label">수어 검색 결과</div>
        <div class="signs-list" id="signs-list">
          <div class="signs-empty">수어 단어를 기다리는 중...</div>
        </div>
      </div>

      <!-- 처리 상태 바 -->
      <div class="pip-status-bar" id="pip-status-bar">
        <span class="status-dot off" id="pip-dot"></span>
        <span id="pip-status-text">대기 중</span>
        <span class="pip-latency" id="pip-latency"></span>
      </div>
    `;

    this._captionLinesEl = this._root.querySelector('#caption-lines');
    this._signsListEl    = this._root.querySelector('#signs-list');
    this._pipDot         = this._root.querySelector('#pip-dot');
    this._pipStatusText  = this._root.querySelector('#pip-status-text');
    this._pipLatency     = this._root.querySelector('#pip-latency');
  }

  // ── 이벤트 수신 ────────────────────────────────────────────

  _listen() {
    window.addEventListener('itda:stt:text', (e) => {
      const { text, confidence, process_ms } = e.detail;
      if (text) {
        this._pushCaption(text, confidence);
        this._setStatus('인식됨', true, `${Math.round(process_ms)}ms`);
      }
    });

    window.addEventListener('itda:stt:sign', (e) => {
      const { sign_terms, emotion_weight, query_text } = e.detail;
      this._renderSignCards(sign_terms, emotion_weight);

      // ── 4단계 아바타 연동 이벤트 발행 ────────────────────
      if (sign_terms && sign_terms.length > 0) {
        window.dispatchEvent(new CustomEvent('itda:sign:perform', {
          detail: {
            sign_terms,
            emotion_weight,
            query_text,
          },
        }));
      }
    });

    window.addEventListener('itda:stt:error', (e) => {
      this._setStatus('오류: ' + (e.detail.error_msg || '알 수 없음'), false);
    });

    window.addEventListener('itda:ws:open',  () => this._setStatus('연결됨',  true));
    window.addEventListener('itda:ws:close', () => this._setStatus('연결 끊김', false));
  }

  // ── 자막 렌더링 ────────────────────────────────────────────

  _pushCaption(text, confidence) {
    this._captions.push({ text, confidence, ts: Date.now() });
    if (this._captions.length > this._maxCaptions) {
      this._captions.shift();
    }
    this._renderCaptions();
  }

  _renderCaptions() {
    if (!this._captionLinesEl) return;
    const html = this._captions.map((c, i) => {
      const isLatest = i === this._captions.length - 1;
      const opacity  = 0.4 + 0.6 * ((i + 1) / this._captions.length);
      const confPct  = Math.round(c.confidence * 100);
      return `
        <div class="caption-line ${isLatest ? 'latest' : ''}"
             style="opacity:${opacity}">
          <span class="caption-text">${this._escHtml(c.text)}</span>
          <span class="caption-conf">${confPct}%</span>
        </div>`;
    }).join('');
    this._captionLinesEl.innerHTML = html || '<div class="caption-empty">인식 대기 중...</div>';
  }

  // ── 수어 카드 렌더링 ─────────────────────────────────────

  _renderSignCards(signTerms, emotionWeight) {
    if (!this._signsListEl) return;

    if (!signTerms || signTerms.length === 0) {
      this._signsListEl.innerHTML = '<div class="signs-empty">수어 단어 없음</div>';
      return;
    }

    const emotionBar = Math.round(emotionWeight * 100);
    const html = `
      <div class="emotion-bar-wrap">
        <span class="emotion-label">감정 강도</span>
        <div class="emotion-bar">
          <div class="emotion-fill" style="width:${emotionBar}%"></div>
        </div>
        <span class="emotion-val">${emotionBar}%</span>
      </div>
      ${signTerms.map(term => `
        <div class="sign-card">
          <div class="sign-word">${this._escHtml(term.word)}</div>
          ${term.emotion_tag
            ? `<span class="sign-emotion">${this._escHtml(term.emotion_tag)}</span>`
            : ''}
          ${term.description
            ? `<div class="sign-desc">${this._escHtml(term.description)}</div>`
            : ''}
          <div class="sign-conf-bar">
            <div class="sign-conf-fill"
                 style="width:${Math.round((term.confidence || 0) * 100)}%"></div>
          </div>
        </div>
      `).join('')}`;

    this._signsListEl.innerHTML = html;
  }

  // ── 상태 바 ───────────────────────────────────────────────

  _setStatus(text, active, latency = '') {
    if (this._pipStatusText) this._pipStatusText.textContent = text;
    if (this._pipDot) {
      this._pipDot.className = 'status-dot' + (active ? ' on' : ' off');
    }
    if (this._pipLatency) this._pipLatency.textContent = latency;
  }

  // ── 유틸 ─────────────────────────────────────────────────

  _escHtml(str) {
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }
}

// 전역 노출
window.PIPOverlay = PIPOverlay;
