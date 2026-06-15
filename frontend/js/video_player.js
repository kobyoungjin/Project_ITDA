/**
 * video_player.js — Supabase 수어 영상 플레이어
 *
 * 백엔드 /api/video/url/{keyword} 를 통해
 * Supabase Storage 공개 URL을 받아 <video>에 재생합니다.
 * MP4 로컬 저장 없음. 첫 검색 시 자동 업로드, 이후 Supabase CDN 재생.
 *
 * 공개 API: window.ITDAVideoPlayer = { play(keyword), hide() }
 */

const VIDEO_URL_API = 'http://localhost:8000/api/video/url';

function _els() {
  return {
    vid: document.getElementById('sign-video'),
    placeholder: document.getElementById('video-placeholder'),
    wordLabel: document.getElementById('video-word-label'),
  };
}

function _setMsg(text) {
  const p = document.getElementById('video-placeholder');
  if (p) p.querySelector('.placeholder-msg').textContent = text;
}

function _showVideo(url, label) {
  const { vid, placeholder, wordLabel } = _els();
  if (!vid) return;

  if (placeholder) placeholder.style.display = 'none';
  vid.style.display = 'block';

  if (vid.src !== url) {
    vid.src = url;
    vid.load();
  }
  vid.currentTime = 0;
  vid.play().catch(e => console.warn('[VideoPlayer] 자동재생 차단:', e.message));

  if (wordLabel) {
    wordLabel.textContent = label || '';
    wordLabel.style.display = label ? 'block' : 'none';
  }
}

function _showPlaceholder(msg) {
  const { vid, placeholder, wordLabel } = _els();
  if (vid) { vid.pause(); vid.src = ''; vid.style.display = 'none'; }
  if (wordLabel) wordLabel.style.display = 'none';
  if (placeholder) {
    placeholder.style.display = 'flex';
    _setMsg(msg);
  }
}

async function play(keyword) {
  if (!keyword) return;

  _setMsg(`"${keyword}" 영상 로딩 중...`);
  const { vid, placeholder } = _els();
  if (vid) vid.style.display = 'none';
  if (placeholder) placeholder.style.display = 'flex';

  try {
    const res = await fetch(`${VIDEO_URL_API}/${encodeURIComponent(keyword)}`);
    if (!res.ok) {
      _showPlaceholder(`"${keyword}" 영상이 없습니다`);
      return;
    }
    const { url } = await res.json();
    _showVideo(url, keyword);
  } catch (e) {
    console.error('[VideoPlayer] 오류:', e);
    _showPlaceholder('영상을 불러올 수 없습니다');
  }
}

function hide() {
  _showPlaceholder('수어를 입력하면 영상이 재생됩니다');
}

window.ITDAVideoPlayer = { play, hide };

console.info('[VideoPlayer] Supabase 모드 준비됨.');
