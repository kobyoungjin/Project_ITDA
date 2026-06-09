/**
 * video_preloader.js — 수어 영상 사전 캐싱 (IndexedDB + Blob)
 *
 * 페이지 로드 시 85개 투명 webm 영상을 백그라운드에서 일괄 다운로드하여
 * IndexedDB에 영구 저장. 재방문 시 네트워크 없이 즉시 재생.
 *
 * 공개 API:
 *   window.ITDAVideoPreloader.getBlobUrl(word)  → blob URL 또는 null
 *   window.ITDAVideoPreloader.isReady()         → 전체 로드 완료 여부
 *   window.ITDAVideoPreloader.getStatus()       → { total, loaded, fromCache }
 */

const DB_NAME = 'itda-video-cache';
const DB_VERSION = 1;
const STORE_NAME = 'videos';
const CACHE_EXPIRY_DAYS = 7;
const MAX_CONCURRENT = 6;
const API_URL = '/api/sign-language/supabase/video-urls';

// Blob URL 메모리 캐시 (세션 동안 유지)
const _blobUrls = new Map();

let _db = null;
let _status = { total: 0, loaded: 0, fromCache: 0, ready: false };

// ── IndexedDB 열기 ──────────────────────────────────────────
function _openDB() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = (e) => {
      const db = e.target.result;
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        db.createObjectStore(STORE_NAME, { keyPath: 'word' });
      }
    };
    req.onsuccess = (e) => resolve(e.target.result);
    req.onerror = (e) => reject(e.target.error);
  });
}

// ── IndexedDB에서 항목 읽기 ─────────────────────────────────
function _getFromDB(db, word) {
  return new Promise((resolve) => {
    const tx = db.transaction(STORE_NAME, 'readonly');
    const store = tx.objectStore(STORE_NAME);
    const req = store.get(word);
    req.onsuccess = () => resolve(req.result || null);
    req.onerror = () => resolve(null);
  });
}

// ── IndexedDB에 항목 저장 ───────────────────────────────────
function _putToDB(db, word, blob, url) {
  return new Promise((resolve) => {
    const tx = db.transaction(STORE_NAME, 'readwrite');
    const store = tx.objectStore(STORE_NAME);
    store.put({ word, blob, url, cachedAt: Date.now() });
    tx.oncomplete = () => resolve();
    tx.onerror = () => resolve();
  });
}

// ── 만료된 항목 삭제 ────────────────────────────────────────
async function _cleanExpired(db) {
  const expiryMs = CACHE_EXPIRY_DAYS * 24 * 60 * 60 * 1000;
  const cutoff = Date.now() - expiryMs;
  return new Promise((resolve) => {
    const tx = db.transaction(STORE_NAME, 'readwrite');
    const store = tx.objectStore(STORE_NAME);
    const req = store.openCursor();
    req.onsuccess = (e) => {
      const cursor = e.target.result;
      if (cursor) {
        if (cursor.value.cachedAt < cutoff) {
          cursor.delete();
        }
        cursor.continue();
      }
    };
    tx.oncomplete = () => resolve();
    tx.onerror = () => resolve();
  });
}

// ── 병렬 다운로드 (동시 N개 제한) ───────────────────────────
async function _downloadPool(tasks, concurrency) {
  let idx = 0;
  const run = async () => {
    while (idx < tasks.length) {
      const i = idx++;
      await tasks[i]();
    }
  };
  const workers = Array.from({ length: Math.min(concurrency, tasks.length) }, () => run());
  await Promise.all(workers);
}

// ── 메인 초기화 ─────────────────────────────────────────────
async function init() {
  try {
    _db = await _openDB();
    await _cleanExpired(_db);

    // 영상 URL 목록 일괄 조회
    const resp = await fetch(API_URL);
    if (!resp.ok) throw new Error(`API ${resp.status}`);
    const data = await resp.json();
    const videoMap = data.videos || {};
    const words = Object.keys(videoMap);

    _status.total = words.length;
    console.info(`[Preloader] ${words.length}개 수어 영상 캐싱 시작`);

    // IndexedDB에서 이미 있는 항목 로드
    const toDownload = [];
    for (const word of words) {
      const cached = await _getFromDB(_db, word);
      if (cached && cached.blob) {
        _blobUrls.set(word, URL.createObjectURL(cached.blob));
        _status.loaded++;
        _status.fromCache++;
      } else {
        toDownload.push({ word, url: videoMap[word] });
      }
    }

    if (_status.fromCache > 0) {
      console.info(`[Preloader] IndexedDB 캐시 히트: ${_status.fromCache}개 (즉시 사용 가능)`);
    }

    if (toDownload.length === 0) {
      _status.ready = true;
      console.info(`[Preloader] 전체 캐시 완료! (${_status.loaded}개)`);
      window.dispatchEvent(new CustomEvent('itda:preload:complete', { detail: _status }));
      return;
    }

    console.info(`[Preloader] 다운로드 필요: ${toDownload.length}개`);

    // 병렬 다운로드
    const tasks = toDownload.map(({ word, url }) => async () => {
      try {
        const r = await fetch(url);
        if (!r.ok) return;
        const blob = await r.blob();
        _blobUrls.set(word, URL.createObjectURL(blob));
        await _putToDB(_db, word, blob, url);
        _status.loaded++;

        // 진행률 이벤트
        window.dispatchEvent(new CustomEvent('itda:preload:progress', {
          detail: { word, loaded: _status.loaded, total: _status.total }
        }));
      } catch (e) {
        console.warn(`[Preloader] "${word}" 다운로드 실패:`, e.message);
      }
    });

    await _downloadPool(tasks, MAX_CONCURRENT);

    _status.ready = true;
    console.info(`[Preloader] 완료! ${_status.loaded}/${_status.total} (캐시: ${_status.fromCache})`);
    window.dispatchEvent(new CustomEvent('itda:preload:complete', { detail: _status }));

  } catch (e) {
    console.error('[Preloader] 초기화 실패:', e);
  }
}

// ── 공개 API ────────────────────────────────────────────────
window.ITDAVideoPreloader = {
  getBlobUrl(word) { return _blobUrls.get(word) || null; },
  isReady() { return _status.ready; },
  getStatus() { return { ..._status }; },
};

// ── 페이지 로드 2초 후 자동 시작 ────────────────────────────
setTimeout(() => {
  console.info('[Preloader] 수어 영상 사전 캐싱 시작...');
  init();
}, 2000);
