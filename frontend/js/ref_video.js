/**
 * ref_video.js — AI Hub 수어 참조 영상 PIP 제어
 *
 * 단어가 번역/재생될 때 frontend/data/videos/ 에 해당 영상이 있으면
 * #ref-pip 에 자동으로 로드하여 보여줌.
 *
 * 공개 API: window.ITDARefVideo.show(word), .hide()
 */

const VIDEO_INDEX_URL = './data/videos/index.json';
let _videoIndex = null;

async function _loadIndex() {
  if (_videoIndex) return _videoIndex;
  try {
    const res = await fetch(VIDEO_INDEX_URL, { cache: 'no-cache' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    _videoIndex = data.videos || {};
    console.info(`[RefVideo] 영상 인덱스 로드: ${Object.keys(_videoIndex).length}개 단어`);
  } catch (e) {
    console.warn('[RefVideo] 인덱스 로드 실패:', e.message);
    _videoIndex = {};
  }
  return _videoIndex;
}

async function showRefVideo(word) {
  const index = await _loadIndex();
  const filename = index[word];
  if (!filename) return;

  const pip = document.getElementById('ref-pip');
  const vid = document.getElementById('ref-video');
  if (!pip || !vid) return;

  const url = `./data/videos/${encodeURIComponent(filename)}`;

  // 이미 같은 영상이면 처음부터 재생만
  if (vid.src.endsWith(encodeURIComponent(filename))) {
    vid.currentTime = 0;
    pip.style.display = 'block';
    vid.play().catch(() => {});
    return;
  }

  pip.style.display = 'block';
  vid.src = url;
  vid.load();
  vid.play().catch(e => console.warn('[RefVideo] 자동재생 차단:', e.message));
  console.info(`[RefVideo] "${word}" → ${filename}`);
}

function hideRefVideo() {
  const pip = document.getElementById('ref-pip');
  const vid = document.getElementById('ref-video');
  if (pip) pip.style.display = 'none';
  if (vid) { vid.pause(); vid.src = ''; }
}

window.ITDARefVideo = { show: showRefVideo, hide: hideRefVideo };

// itda:motion:played 이벤트 자동 연동
window.addEventListener('itda:motion:played', (e) => {
  const word = e.detail?.keyword;
  if (word) showRefVideo(word);
});

console.info('[RefVideo] 준비됨. ITDARefVideo.show("<단어>") 로 호출 가능.');
