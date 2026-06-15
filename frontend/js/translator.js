/**
 * translator.js
 *
 * 텍스트/음성 입력 → 백엔드 검색 → 수어 영상 재생
 */

const chatInput = document.getElementById('chat-input');
const btnMic = document.getElementById('btn-mic');
const btnSend = document.getElementById('btn-send');
const slmOutput = document.getElementById('slm-output');

btnMic.addEventListener('click', () => {
  if (!window.ITDAStt) { console.warn('[STT] 어댑터 미로드'); return; }
  chatInput.value = '';
  window.ITDAStt.toggle();
});

window.addEventListener('itda:stt:state', (e) => {
  const state = e.detail;
  if (state === 'listening') {
    btnMic.classList.add('recording');
    chatInput.placeholder = '말씀해 주세요...';
  } else {
    btnMic.classList.remove('recording');
    chatInput.placeholder = '번역할 내용을 입력하세요...';
    if (state === 'error' && slmOutput) {
      slmOutput.innerHTML = '<span style="color:#ff4757">음성 인식 오류</span>';
    }
  }
});

window.addEventListener('itda:stt:transcript', (e) => {
  const { text } = e.detail || {};
  if (!text) return;
  chatInput.value = text;
  sendMessage(text);
});

btnSend.addEventListener('click', () => {
  const text = chatInput.value.trim();
  if (text) sendMessage(text);
});

chatInput.addEventListener('keypress', (e) => {
  if (e.key === 'Enter') {
    const text = chatInput.value.trim();
    if (text) sendMessage(text);
  }
});

async function sendMessage(text) {
  chatInput.value = '';
  if (slmOutput) {
    slmOutput.innerHTML = `<em style="color:var(--text-muted); font-weight:400; font-size:0.9rem;">🔍 "${text}" 검색 중...</em>`;
  }

  try {
    const res = await fetch('http://localhost:8000/api/sign-language/search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query: text, context: '' })
    });
    if (!res.ok) throw new Error(`서버 응답 오류 (코드: ${res.status})`);

    const result = await res.json();
    const data = result.data;

    if (data) {
      const emotionsHtml = (data.emotions || [])
        .map(em => `<span class="t-emotion-badge" style="background:rgba(0,242,254,0.1);border:1px solid var(--accent-cyan);color:var(--accent-cyan);">${em}</span>`)
        .join(' ');

      if (slmOutput) {
        slmOutput.innerHTML = `<span style="color:var(--accent-cyan);font-weight:800;font-size:1.1rem;">✨ ${data.keyword}</span> ${emotionsHtml}`;
      }

      window.ITDAVideoPlayer?.play(data.keyword);
    }
  } catch (err) {
    console.error('[Search Error]', err);
    if (slmOutput) {
      slmOutput.innerHTML = `<span style="color:#ffb8b8">"${text}"에 해당하는 수어 영상을 찾지 못했어요.</span>`;
    }
    window.ITDAVideoPlayer?.play(text);
  }
}

window.ITDATranslator = {
  replay(keyword) { window.ITDAVideoPlayer?.play(keyword); }
};
