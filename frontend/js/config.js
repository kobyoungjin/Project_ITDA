/**
 * config.js ─ 백엔드 엔드포인트 중앙 설정 (글로벌 객체)
 *
 * 사용 방식:
 *   HTML 의 다른 모든 스크립트보다 먼저 로드되어야 함:
 *     <script src="./js/config.js"></script>
 *
 *   이후 모든 곳에서 동일하게 접근:
 *     fetch(`${ITDAConfig.API_HTTP}/api/...`)
 *     new WebSocket(`${ITDAConfig.API_WS}/api/...`)
 *     fetch(ITDAConfig.motionUrl('안녕하세요'))
 *
 * 환경 감지 우선순위:
 *   1) window.__ITDA_BACKEND_URL — HTML <script> 에서 명시적 주입
 *   2) localStorage('itda:backend_url') — 사용자 브라우저 설정 (개발용 오버라이드)
 *   3) 호스트가 localhost/127.0.0.1/사설 IP → 로컬 개발 (8000 포트)
 *   4) 그 외 (vercel.app 등 운영) → 운영 백엔드 (HF Spaces)
 */
(function () {
  // ── 운영 백엔드 URL ─────────────────────────────────────────
  // Hugging Face Space: goma1124/itda-backend
  const PROD_BACKEND_HTTP = 'https://goma1124-itda-backend.hf.space';

  function _isLocalHost(host) {
    if (!host) return true;
    return (
      host === 'localhost' ||
      host === '127.0.0.1' ||
      host === '0.0.0.0' ||
      host.endsWith('.local') ||
      /^192\.168\./.test(host) ||
      /^10\./.test(host) ||
      /^172\.(1[6-9]|2[0-9]|3[01])\./.test(host)
    );
  }

  function _resolveBackendHttp() {
    if (window.__ITDA_BACKEND_URL) return window.__ITDA_BACKEND_URL.replace(/\/$/, '');
    try {
      const stored = localStorage.getItem('itda:backend_url');
      if (stored) return stored.replace(/\/$/, '');
    } catch (e) {}
    const host = (location && location.hostname) || 'localhost';
    if (_isLocalHost(host)) {
      return `http://${host}:8000`;
    }
    return PROD_BACKEND_HTTP.replace(/\/$/, '');
  }

  const API_HTTP = _resolveBackendHttp();
  // http→ws, https→wss 자동 매핑
  const API_WS = API_HTTP.replace(/^http/, 'ws');

  window.ITDAConfig = {
    API_HTTP,
    API_WS,
    // 모션 데이터 — 백엔드 정적 마운트의 /static/motions/<word>.json
    motionUrl: function (word) {
      return `${API_HTTP}/static/motions/${encodeURIComponent(word)}.json`;
    },
  };

  console.info('[ITDA Config] backend =', API_HTTP);
})();
