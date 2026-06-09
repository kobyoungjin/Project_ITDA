/**
 * motion_loader_v3.js ─ [Option A / V3]
 *
 * MOTION_PROFILES_V3 JSON 로드 및 quaternion keyframe 재생 엔진.
 *
 * V2 와의 차이:
 *   - V2: Euler {x, y, z} 형식 → 엔진에서 Euler→Quaternion 변환 (ZYX order 이슈)
 *   - V3: Quaternion {x, y, z, w} 직접 저장 → 변환 없이 slerp (더 정확)
 *
 * V3 JSON 포맷 (api/data/ksl_motions/{word}.json):
 * {
 *   "id": "안녕하세요",
 *   "version": "v3",
 *   "source": "mediapipe",
 *   "fps": 30.0,
 *   "keyframes": [
 *     { "time": 0.0, "bones": { "RightArm": {x,y,z,w}, ... } },
 *     { "time": 0.2, "bones": { ... } },
 *     ...
 *   ]
 * }
 *
 * 공개 API:
 *   window.ITDAMotionV3 = {
 *     load(word): Promise<motion>       — JSON 로드 및 캐시
 *     play(word): Promise<void>         — 아바타에서 재생 (animateAvatar 대체)
 *     has(word): bool                   — 캐시/서버에 있는지
 *   }
 */

import * as THREE from 'three';

// [Build] 캐시 미반영 디버깅용 — 콘솔에 이 라인이 안 보이면 옛 모듈을 보고 있는 것.
const _MV3_BUILD = '2026-05-08b-wrist-fix';
console.info(`%c[MotionV3 BUILD] ${_MV3_BUILD}`, 'background:#0ff;color:#000;font-weight:bold;padding:2px 6px;');

const CACHE = new Map();
const INDEX_URL = './data/ksl_motions/index.json';
const HANDSHAPE_LIB_URL = './data/handshape_library.json';
let _index = null;
let _handshapeLib = null;
// 세션 idle 자세 — setAsIdle 호출 시 채워짐. 모션 종료 후 복귀 anchor 로 사용한다.
// 비어 있으면 GLB initialBoneQuats(=T-pose) 로 폴백.
let _idlePoseQuats = null;

// ── 서버 index 로드 (있으면 use, 없으면 on-demand 로드) ──────
async function _loadIndex() {
  if (_index !== null) return _index;
  try {
    const res = await fetch(INDEX_URL, { cache: 'no-cache' });
    if (!res.ok) throw new Error(`index HTTP ${res.status}`);
    _index = await res.json();
    console.info(`[MotionV3] 인덱스 로드: ${_index.total}개 단어`);
  } catch (e) {
    console.warn('[MotionV3] 인덱스 없음 (on-demand 로드 모드):', e.message);
    _index = { total: 0, actions: [] };
  }
  return _index;
}

// ── 수형 라이브러리 로드 ───────────────────────────────────
async function _loadHandshapeLib() {
  if (_handshapeLib !== null) return _handshapeLib;
  try {
    const res = await fetch(HANDSHAPE_LIB_URL, { cache: 'no-cache' });
    if (!res.ok) throw new Error(`handshape library HTTP ${res.status}`);
    const data = await res.json();
    _handshapeLib = data.shapes;
    console.info(`[MotionV3] 수형 라이브러리 로드 완료 (${Object.keys(_handshapeLib).length}개)`);
  } catch (e) {
    console.error('[MotionV3] 수형 라이브러리 로드 실패:', e);
    _handshapeLib = {};
  }
  return _handshapeLib;
}

// ── 단일 모션 JSON 로드 + 캐싱 ─────────────────────────────
async function loadMotion(word) {
  if (CACHE.has(word)) return CACHE.get(word);

  // [Preloader] IndexedDB에 사전 캐싱된 Blob이 있으면 즉시 반환 (네트워크 0)
  const preloadedUrl = window.ITDAVideoPreloader?.getBlobUrl(word);
  if (preloadedUrl) {
    const motion = { video_url: preloadedUrl, _blobUrl: preloadedUrl, keyframes: [] };
    CACHE.set(word, motion);
    const sourceEl = document.getElementById('mini-source-output');
    if (sourceEl) sourceEl.innerHTML = '<span class="source-badge cloud" style="background:#22c55e">⚡ Cached</span>';
    console.info(`[MotionV3] Preloader 캐시 히트: ${word}`);
    return motion;
  }

  const sourceEl = document.getElementById('mini-source-output');

  // 1. Supabase 외부 DB 최우선 확인 (최신 데이터)
  console.info(`[MotionV3] Supabase DB 조회 시도: ${word}`);
  if (sourceEl) sourceEl.innerHTML = '<span class="source-badge cloud">📡 Cloud</span>';

  try {
    const supaRes = await fetch(`/api/sign-language/supabase/motion/${encodeURIComponent(word)}`, {
      signal: AbortSignal.timeout(8000)
    });
    if (supaRes.ok) {
      const result = await supaRes.json();
      if (result.status === 'success' && result.motion_data) {
        let motion = result.motion_data;

        // [복구] 데이터가 배열 형태라면 마지막 요소(최신 리비전)를 사용
        if (Array.isArray(motion)) {
          motion = motion[motion.length - 1];
        }

        // [2026-05-26] 영상 우선: video_url이 있으면 영상으로 재생 (아바타보다 영상 우선)
        if (motion && motion.video_url) {
          console.info(`[MotionV3] Supabase 영상 우선: ${word} (${motion.video_url.slice(-40)})`);
          // keyframes를 비워서 영상 전용으로 처리
          motion._hasKeyframes = !!(motion.keyframes?.length);
          motion.keyframes = [];
          CACHE.set(word, motion);
          return motion;
        }
        if (motion && motion.keyframes?.length) {
          console.info(`[MotionV3] Supabase 모션 로드: ${word}`);
          _bakeRetargetCorrection(motion);
          CACHE.set(word, motion);
          return motion;
        }
      }
    }
  } catch (e) {
    console.warn(`[MotionV3] Supabase 조회 실패: ${e.message}`);
  }

  // 2. [Fallback] 로컬 파일 시스템 확인 (구버전)
  const localUrl = `./data/ksl_motions/${encodeURIComponent(word)}.json`;
  try {
    console.info(`[MotionV3] DB 없음 → 로컬 파일 폴백 시도: ${word}`);
    const res = await fetch(localUrl, { cache: 'no-cache', signal: AbortSignal.timeout(5000) });
    if (res.ok) {
      const motion = await res.json();
      _bakeRetargetCorrection(motion);
      CACHE.set(word, motion);
      if (sourceEl) sourceEl.innerHTML = '<span class="source-badge local">🏠 Local</span>';
      return motion;
    }
  } catch (e) {
    console.debug(`[MotionV3] 로컬 파일 조회 실패: ${word}`);
  }

  if (sourceEl) sourceEl.innerHTML = '<span class="source-badge missing">❌ 미등록</span>';
  console.info(`[MotionV3] ${word} 최종 미발견 — 건너뜀`);

  return null;
}

async function hasMotion(word) {
  if (CACHE.has(word)) return true;
  const idx = await _loadIndex();
  return idx.actions?.includes(word) ?? false;
}

// ── Keyframe 재생 (Quaternion slerp) ────────────────────────
async function playMotion(word, opts = {}) {
  const [motion, _lib] = await Promise.all([loadMotion(word), _loadHandshapeLib()]);
  if (!motion) return false;

  // 영상 전용 모션 (keyframes 없고 video_url만 있음) → 영상만 재생
  if (!motion.keyframes?.length && motion.video_url) {
    console.info(`[MotionV3] 영상 전용 재생: "${word}"`);
    return _playVideoOnly(motion.video_url, word);
  }

  if (!motion.keyframes?.length) return false;
  return _playCore(motion, word, opts);
}

/**
 * 큐에서 다음 항목이 영상 전용인지 확인 (look-ahead)
 * playSequence의 prefetch로 CACHE가 이미 채워져 있으므로 동기 조회 안전.
 */
function _isNextItemVideo(currentIdx) {
  const nextIdx = currentIdx + 1;
  if (nextIdx >= signLanguageQueue.length) return false;
  const nextItem = signLanguageQueue[nextIdx];
  const nextWord = typeof nextItem === 'string' ? nextItem : (nextItem?.word || '');
  if (!nextWord) return false;
  const nextMotion = nextItem?.motion || CACHE.get(nextWord);
  if (!nextMotion) return false;
  return !!(nextMotion.video_url && !nextMotion.keyframes?.length);
}

// ── 더블 버퍼링 영상 재생 (회색 화면 전환 방지) ──────────────────
// 두 개의 <video> 엘리먼트를 교대로 사용하여, 현재 영상이 재생 중일 때
// 다음 영상을 숨겨진 video에 미리 로드 → 전환 시 display만 swap.
let _activeVideoIdx = 0;  // 현재 활성 video (0 또는 1)

function _getVideoPair() {
  return [document.getElementById('ref-video-0'), document.getElementById('ref-video-1')];
}

/**
 * 다음 영상을 백그라운드 video에 미리 로드 (preload)
 */
function _preloadNextVideo(nextUrl) {
  const [v0, v1] = _getVideoPair();
  if (!v0 || !v1) return;
  const backVid = _activeVideoIdx === 0 ? v1 : v0;
  backVid.src = nextUrl;
  backVid.load();
}

/**
 * 영상 전용 재생 (더블 버퍼링 + trimEnd)
 * @param {string} videoUrl - Blob URL 또는 원격 URL
 * @param {string} label - 단어 이름 (로그용)
 * @param {object} opts
 * @param {boolean} opts.skipFadeOut - true면 fadeOut 생략 (다음 영상이 이어질 때)
 * @param {number}  opts.trimEnd - 끝에서 잘라낼 초 (기본 0)
 * @param {string}  opts.nextUrl - 다음 영상 URL (preload용)
 */
function _playVideoOnly(videoUrl, label, { skipFadeOut = false, trimEnd = 0, nextUrl = null } = {}) {
  const refPip = document.getElementById('ref-pip');
  const [v0, v1] = _getVideoPair();
  const canvas = document.getElementById('three-canvas');
  if (!refPip || !v0 || !v1) return Promise.resolve(false);

  const activeVid = _activeVideoIdx === 0 ? v0 : v1;
  const backVid = _activeVideoIdx === 0 ? v1 : v0;

  return new Promise((resolve) => {
    let resolved = false;
    const safeResolve = (val) => { if (!resolved) { resolved = true; resolve(val); } };

    // 마지막 영상 종료 — 검정 화면 없이 즉시 전환
    const _fadeOut = () => {
      refPip.style.display = 'none';
      refPip.classList.remove('video-mode-active');
      if (canvas) canvas.style.visibility = 'visible';
      window.translationModeActive = false;
      activeVid.pause();
      safeResolve(true);
    };

    // 전환: 다음 영상이 있으면 크로스페이드, 없으면 즉시 종료
    const CROSSFADE_MS = 350;
    const _finish = () => {
      if (skipFadeOut && nextUrl) {
        // 두 video가 position:absolute로 겹쳐있음
        // backVid를 보이게 하고 play → playing 이벤트 후 크로스페이드
        backVid.style.display = 'block';
        backVid.style.opacity = '0';

        const _onPlaying = () => {
          backVid.removeEventListener('playing', _onPlaying);
          // 크로스페이드: backVid 올리고 activeVid 내리기 (150ms)
          backVid.style.transition = `opacity ${CROSSFADE_MS}ms ease`;
          backVid.style.opacity = '1';
          activeVid.style.transition = `opacity ${CROSSFADE_MS}ms ease`;
          activeVid.style.opacity = '0';

          setTimeout(() => {
            activeVid.pause();
            activeVid.style.display = 'none';
            activeVid.style.transition = '';
            activeVid.style.opacity = '1';
            backVid.style.transition = '';
            _activeVideoIdx = _activeVideoIdx === 0 ? 1 : 0;
            safeResolve(true);
          }, CROSSFADE_MS + 20);
        };
        backVid.addEventListener('playing', _onPlaying, { once: true });
        backVid.playbackRate = 0.9;
        backVid.play().catch(() => safeResolve(true));
      } else if (skipFadeOut) {
        safeResolve(true);
      } else {
        _fadeOut();
      }
    };

    // 이전 핸들러 제거
    for (const vid of [v0, v1]) {
      if (vid._itdaEndedHandler) {
        vid.removeEventListener('ended', vid._itdaEndedHandler);
        vid._itdaEndedHandler = null;
      }
      if (vid._itdaTimeHandler) {
        vid.removeEventListener('timeupdate', vid._itdaTimeHandler);
        vid._itdaTimeHandler = null;
      }
    }

    // ended 핸들러
    const _onEnded = () => _finish();
    activeVid._itdaEndedHandler = _onEnded;
    activeVid.addEventListener('ended', _onEnded, { once: true });

    // trimEnd: 끝 N초 전에 다음 영상으로 전환
    if (trimEnd > 0) {
      const _onTime = () => {
        if (activeVid.duration && activeVid.currentTime >= activeVid.duration - trimEnd) {
          activeVid.removeEventListener('timeupdate', _onTime);
          activeVid._itdaTimeHandler = null;
          activeVid.removeEventListener('ended', _onEnded);
          _finish();
        }
      };
      activeVid._itdaTimeHandler = _onTime;
      activeVid.addEventListener('timeupdate', _onTime);
    }

    // 다음 영상을 백 video에 미리 로드 (숨긴 상태, 앞 0.3초 건너뛰기)
    if (nextUrl) {
      backVid.style.display = 'none';
      backVid.src = nextUrl;
      backVid.load();
      backVid.addEventListener('loadedmetadata', () => {
        backVid.currentTime = 1.0;  // 차렷→동작 시작 구간 건너뛰기
      }, { once: true });
    }

    // 이미 크로스페이드로 재생 중인 영상이면 src 재설정 스킵
    const alreadyPlaying = !activeVid.paused && activeVid.src && activeVid.src === videoUrl;
    if (alreadyPlaying) {
      console.info(`[Video] "${label}" 이미 재생 중 — src 재설정 스킵`);
    } else {
      // 컨테이너는 실제 프레임 렌더 시 표시 (검정 깜빡임 방지)
      refPip.style.opacity = '0';
      refPip.style.display = 'block';
      activeVid.style.display = 'block';
      activeVid.src = videoUrl;
      activeVid.load();
      activeVid.addEventListener('playing', () => {
        refPip.style.opacity = '1';
        if (canvas) canvas.style.visibility = 'hidden';
      }, { once: true });
      activeVid.playbackRate = 0.9;
      activeVid.play().catch(e => console.warn('[Video] Auto-play blocked:', e));
    }
    window.translationModeActive = true;
    refPip.classList.add('video-mode-active');

    // 15초 타임아웃
    setTimeout(() => {
      if (!resolved) {
        if (!skipFadeOut) _fadeOut();
        else safeResolve(false);
      }
    }, 15000);
  });
}

/**
 * 외부에서 가져온 모션 데이터를 직접 주입하여 재생합니다.
 */
async function playDirect(motion, label = "direct", opts = {}) {
  await _loadHandshapeLib();
  if (!motion || !motion.keyframes?.length) return false;
  return _playCore(motion, label, opts);
}

/**
 * 공통 재생 핵심 로직
 *
 * opts:
 *   isPartOfSequence: bool — true 면 (a) 시작 시 translationModeActive 을 건드리지 않고
 *                            (b) 종료 시 returnToInitial 단축 (200ms) 하여 다음 단어로 빠르게 진행.
 *                            시퀀스 entry/exit 는 호출자(playSequence)가 책임.
 *   skipReturn:       bool — returnToInitial 자체를 생략. 시퀀스의 비-마지막 단어용.
 */
async function _playCore(motion, label, opts = {}) {
  const avatar = window.ITDAAvatar5;
  if (!avatar) { console.warn('[MotionV3] 아바타 미로드'); return; }

  const isPartOfSequence = !!opts.isPartOfSequence;
  const skipReturn = !!opts.skipReturn;

  // Idle 간섭 제거. 시퀀스 중에는 호출자가 이미 set 했으므로 건드리지 않음.
  avatar.stopIdle?.();
  if (!isPartOfSequence) window.translationModeActive = true;

  // [추가] 🎥 영상 재생: 로컬 투명 webm 우선 → Supabase 투명 webm → 외부 mp4 폴백
  const refPip = document.getElementById('ref-pip');
  const refVid = document.getElementById('ref-video-0');
  const canvas = document.getElementById('three-canvas');

  // 영상 URL 결정: 로컬 webm > 버킷 webm > 원본 URL
  let videoUrl = motion.video_url || null;
  if (videoUrl) {
    // 로컬 투명 webm 확인 (./videos/{word}.webm)
    const localWebm = `./videos/${encodeURIComponent(label)}.webm`;
    try {
      const localCheck = await fetch(localWebm, { method: 'HEAD' });
      if (localCheck.ok) {
        videoUrl = localWebm;
        console.info(`[Video] 로컬 투명 영상 사용: ${label}`);
      }
    } catch (_) { /* 로컬 없으면 원본 URL 유지 */ }
  }

  if (videoUrl && refPip && refVid) {
    // ── 페이드아웃 후 자동 숨김 헬퍼 ──────────────────────────
    const _fadeOutVideo = () => {
      refPip.style.display = 'none';
      refPip.classList.remove('video-mode-active');
      if (canvas) canvas.style.visibility = 'visible';
      window.translationModeActive = false;
      console.info('[Video] 영상 종료 → 아바타 복귀');
    };

    if (refVid._itdaEndedHandler) {
      refVid.removeEventListener('ended', refVid._itdaEndedHandler);
    }
    refVid._itdaEndedHandler = _fadeOutVideo;
    refVid.addEventListener('ended', refVid._itdaEndedHandler, { once: true });

    refPip.style.opacity = '1';
    refPip.style.transition = '';
    refPip.style.display = 'block';
    refPip.classList.add('video-mode-active');
    if (canvas) canvas.style.visibility = 'hidden';

    if (refVid.src !== videoUrl) {
      refVid.src = videoUrl;
    } else {
      refVid.currentTime = 0;
    }
    refVid.playbackRate = 0.9;
    refVid.play().catch(e => console.warn("[Video] Auto-play blocked:", e));
  } else {
    if (refPip) {
      refPip.style.display = 'none';
      refPip.classList.remove('video-mode-active');
    }
    if (canvas) canvas.style.visibility = 'visible';
  }

  // 손가락 rest 캐시 (한 번만). 수형 offset 합성 시 사용.
  _captureHandRest(avatar);
  // arm/forearm/hand 본의 자체 world rest quat 캐시 (한 번만).
  _captureArmRestWorld(avatar);

  const glbInitial = avatar.initialBoneQuats || {};
  const restPose = (_idlePoseQuats && Object.keys(_idlePoseQuats).length) ? _idlePoseQuats : glbInitial;

  // [1단계 & 5단계: 크로스페이드를 위한 현재 자세 캡처]
  // 애니메이션 시작 시점에 강제로 idle pose로 순간이동(snap)하던 기존 로직을 제거했습니다.
  // 대신, 현재 아바타의 뼈대 상태를 모두 캡처해두고 새로운 동작과 부드럽게 섞습니다(Crossfade).
  const startPoseQuats = new Map();
  for (const [name, bone] of Object.entries(avatar.bones || {})) {
    startPoseQuats.set(name, bone.quaternion.clone());
  }


  const keyframes = motion.keyframes;
  const totalDuration = keyframes[keyframes.length - 1].time;
  console.info(`[MotionV3] 재생 "${label}" (${keyframes.length} keyframes, ${totalDuration.toFixed(2)}s)`);

  const startTime = performance.now();
  const targetQuats = new Map();
  let _adaptiveCrossfade = -1;   // 적응형 크로스페이드: 첫 프레임에서 계산, 이후 재사용

  // 복귀용 initial quat — 시퀀스 중이면 GLB initial(진짜 차렷) 사용,
  // 단독 재생이면 현재 자세(idle 클립 기준) 캡처해 자연스러운 entry/exit.
  const touchedBones = new Set();
  for (const kf of keyframes) for (const bName of Object.keys(kf.bones || {})) touchedBones.add(bName);
  for (const bName of Object.keys(avatar._handshapeRest || {})) touchedBones.add(bName);

  const initialQuats = new Map();
  for (const bName of touchedBones) {
    const bone = _resolveBone(avatar, bName);
    if (!bone) continue;
    // 시퀀스 중이면 idle pose 우선 (T-pose 로 끝나는 어색함 방지),
    // 단독 재생이면 현재 자세 캡처 (idle 클립 위에서 자연스러운 entry/exit).
    const restQ = restPose[bone.name] || restPose[bName];
    initialQuats.set(bName, (isPartOfSequence && restQ) ? restQ.clone() : bone.quaternion.clone());
  }

  return new Promise((resolve) => {
    function update(now) {
      const elapsed = (now - startTime) / 1000;

      if (elapsed >= totalDuration) {
        const lastKF = keyframes[keyframes.length - 1];
        _applyInterpolated(avatar, lastKF, lastKF, 1.0, targetQuats, motion);
        _applyRetargetCorrection(avatar, motion, label);

        const finalize = () => {
          // 시퀀스 중간이면 translationModeActive 는 호출자(playSequence)가 마지막에 풀어줌.
          if (!isPartOfSequence) window.translationModeActive = false;
          window.dispatchEvent(new CustomEvent('itda:motion:played', {
            detail: { keyword: label, source: motion.source || 'v3', sequenced: isPartOfSequence }
          }));
          resolve();
        };

        if (skipReturn) {
          // ── 전환 프레임 삽입: 다음 단어의 시작 포즈로 부드럽게 연결 ──
          const nextMotion = _peekNextMotion();
          if (nextMotion && nextMotion.keyframes?.length) {
            // 현재 아바타 포즈 캡처 (exit pose)
            const exitPose = new Map();
            for (const [name, bone] of Object.entries(avatar.bones || {})) {
              exitPose.set(name, bone.quaternion.clone());
            }
            // 다음 모션의 첫 keyframe → entry pose
            const entryPose = new Map();
            const entryBones = nextMotion.keyframes[0].bones || {};
            for (const [bName, bq] of Object.entries(entryBones)) {
              entryPose.set(bName, new THREE.Quaternion(bq.x, bq.y, bq.z, bq.w));
            }

            const dist = _poseDistance(exitPose, entryPose);
            const transDuration = Math.max(0.08, Math.min(0.35, dist * 1.2));

            const exitVel = _estimateAngularVelocity(keyframes, 'exit');
            const entryVel = _estimateAngularVelocity(nextMotion.keyframes, 'entry');
            const transKFs = _generateTransitionKeyframes(
              exitPose, entryPose, exitVel, entryVel, transDuration
            );

            console.info(
              `[Transition] "${label}"→ 다음 단어 | dist=${dist.toFixed(3)}, ` +
              `duration=${transDuration.toFixed(3)}s, ${transKFs.length} frames`
            );
            _playTransitionFrames(avatar, transKFs, transDuration)
              .then(finalize)
              .catch(e => { console.warn('[Transition] 전환 실패:', e); finalize(); });
          } else {
            finalize();
          }
        } else {
          // 시퀀스의 마지막 단어 또는 단독 재생 — 부드럽게 초기 자세로 복귀.
          // 시퀀스 마지막일 땐 더 빠르게 (지각된 응답성 향상).
          const returnDuration = isPartOfSequence ? 300 : 800;
          _returnToInitial(avatar, initialQuats, returnDuration).then(finalize);
        }
        return;
      }

      let prev = keyframes[0], next = keyframes[0];
      for (let i = 1; i < keyframes.length; i++) {
        if (keyframes[i].time >= elapsed) {
          prev = keyframes[i - 1];
          next = keyframes[i];
          break;
        }
      }
      const span = Math.max(next.time - prev.time, 1e-3);
      const t = Math.min(1, (elapsed - prev.time) / span);

      _applyInterpolated(avatar, prev, next, t, targetQuats, motion);
      // [Retargeting] 모션 재생 중에만 적용 — idle 캐시 오염 방지.
      _applyRetargetCorrection(avatar, motion, label);

      // [5단계: 부드럽게 잇기 (적응형 크로스페이드)]
      // 이전 자세와 첫 keyframe 간 거리가 클수록 크로스페이드를 길게, 가까우면 짧게.
      if (_adaptiveCrossfade < 0) {
        const firstKFPose = new Map();
        for (const [bName, bq] of Object.entries(keyframes[0].bones || {})) {
          firstKFPose.set(bName, new THREE.Quaternion(bq.x, bq.y, bq.z, bq.w));
        }
        const dist = _poseDistance(startPoseQuats, firstKFPose);
        // 거리 → 시간: 가까우면 100ms, 멀면 500ms
        _adaptiveCrossfade = Math.max(0.1, Math.min(0.5, dist * 1.5));
      }
      const crossfadeDuration = _adaptiveCrossfade;
      if (elapsed < crossfadeDuration) {
        const fadeProgress = elapsed / crossfadeDuration; // 0.0 ~ 1.0
        for (const [name, bone] of Object.entries(avatar.bones || {})) {
          const startQ = startPoseQuats.get(name);
          if (startQ) {
            const targetQ = bone.quaternion.clone();
            // 이전 동작에서 현재 뼈대 각도로 보간(slerp)
            bone.quaternion.copy(startQ).slerp(targetQ, fadeProgress);
          }
        }
      }

      requestAnimationFrame(update);
    }
    requestAnimationFrame(update);
  });
}

// ── 전환(Transition) 유틸리티 ─────────────────────────────────
// 두 포즈 간 평균 각도 거리 (라디안). 전환 duration 적응형 계산에 사용.
function _poseDistance(poseA, poseB) {
  let totalAngle = 0, count = 0;
  const _qa = new THREE.Quaternion();
  const _qb = new THREE.Quaternion();
  const allKeys = new Set([...poseA.keys(), ...poseB.keys()]);
  for (const name of allKeys) {
    const a = poseA.get(name);
    const b = poseB.get(name);
    if (!a || !b) continue;
    _qa.copy(a);
    _qb.copy(b);
    let dot = Math.abs(_qa.dot(_qb));
    if (dot > 1) dot = 1;
    totalAngle += 2 * Math.acos(dot);
    count++;
  }
  return count > 0 ? totalAngle / count : 0;
}

// 모션 keyframe 경계에서 각속도(delta quaternion / dt) 추정.
// boundaryType: 'exit' (마지막 2프레임) | 'entry' (처음 2프레임)
function _estimateAngularVelocity(keyframes, boundaryType) {
  const vel = new Map();
  if (!keyframes || keyframes.length < 2) return vel;

  const kf0 = boundaryType === 'exit' ? keyframes[keyframes.length - 2] : keyframes[0];
  const kf1 = boundaryType === 'exit' ? keyframes[keyframes.length - 1] : keyframes[1];
  const dt = kf1.time - kf0.time;
  if (dt < 1e-4) return vel;

  const _q0 = new THREE.Quaternion();
  const _q1 = new THREE.Quaternion();
  const allBones = new Set([...Object.keys(kf0.bones || {}), ...Object.keys(kf1.bones || {})]);
  for (const bName of allBones) {
    const b0 = kf0.bones?.[bName];
    const b1 = kf1.bones?.[bName];
    if (!b0 || !b1) continue;
    _q0.set(b0.x, b0.y, b0.z, b0.w);
    _q1.set(b1.x, b1.y, b1.z, b1.w);
    // delta = q1 * q0^-1  →  "q0 에서 q1 으로의 회전"
    const delta = _q1.clone().multiply(_q0.clone().invert());
    vel.set(bName, { delta, dt });
  }
  return vel;
}

// Hermite 스플라인 기반 전환 keyframe 생성.
// exitPose/entryPose: Map<boneName, THREE.Quaternion>
// exitVel/entryVel: Map<boneName, {delta: Quaternion, dt: number}>
// duration(초), fps (기본 30)
function _generateTransitionKeyframes(exitPose, entryPose, exitVel, entryVel, duration, fps) {
  fps = fps || 30;
  const numFrames = Math.max(2, Math.round(duration * fps));
  const kfs = [];
  const allBones = new Set([...exitPose.keys(), ...entryPose.keys()]);
  const _p0 = new THREE.Quaternion();
  const _p1 = new THREE.Quaternion();

  for (let i = 0; i < numFrames; i++) {
    const rawT = i / (numFrames - 1);                    // 0 → 1
    // smoothstep ease-in-out: 3t² - 2t³
    const t = rawT * rawT * (3 - 2 * rawT);
    const bones = {};

    for (const bName of allBones) {
      const q0 = exitPose.get(bName);
      const q1 = entryPose.get(bName);
      if (!q0 && !q1) continue;
      _p0.copy(q0 || q1);
      _p1.copy(q1 || q0);

      // 기본 slerp
      const out = _p0.clone().slerp(_p1, t);

      // 속도 접선 보정: 앞 30% 구간에서 exit 방향 모멘텀, 뒤 30% 구간에서 entry 방향 모멘텀
      const ev = exitVel.get(bName);
      const nv = entryVel.get(bName);
      if (rawT < 0.3 && ev) {
        // exit 모멘텀: delta 를 rawT 비율만큼 축소 적용
        const blend = (0.3 - rawT) / 0.3;            // 1→0
        const scaledDelta = new THREE.Quaternion().slerp(ev.delta, rawT * blend * 0.4);
        out.multiply(scaledDelta);
        out.normalize();
      }
      if (rawT > 0.7 && nv) {
        const blend = (rawT - 0.7) / 0.3;            // 0→1
        const scaledDelta = new THREE.Quaternion().slerp(nv.delta.clone().invert(), (1 - rawT) * blend * 0.4);
        out.multiply(scaledDelta);
        out.normalize();
      }

      bones[bName] = { x: out.x, y: out.y, z: out.z, w: out.w };
    }
    kfs.push({ time: i / fps, bones });
  }
  return kfs;
}

// 전환 keyframe 배열을 rAF 기반 micro-animation 으로 재생.
async function _playTransitionFrames(avatar, transKFs, durationSec) {
  if (!transKFs || transKFs.length < 2) return;
  const durationMs = durationSec * 1000;
  const totalTime = transKFs[transKFs.length - 1].time;
  const startTime = performance.now();

  return new Promise((resolve) => {
    function step(now) {
      const progress = Math.min((now - startTime) / durationMs, 1);
      const t = progress * totalTime;

      // 전후 keyframe 탐색
      let prev = transKFs[0], next = transKFs[0];
      for (let i = 1; i < transKFs.length; i++) {
        if (transKFs[i].time >= t) { prev = transKFs[i - 1]; next = transKFs[i]; break; }
        prev = transKFs[i]; next = transKFs[i]; // 마지막까지 도달 시
      }
      const span = Math.max(next.time - prev.time, 1e-4);
      const localT = Math.min(1, (t - prev.time) / span);

      const _qa = new THREE.Quaternion();
      const _qb = new THREE.Quaternion();
      for (const bName of Object.keys(next.bones)) {
        const bone = _resolveBone(avatar, bName);
        if (!bone) continue;
        const bp = prev.bones[bName] || next.bones[bName];
        const bn = next.bones[bName];
        _qa.set(bp.x, bp.y, bp.z, bp.w);
        _qb.set(bn.x, bn.y, bn.z, bn.w);
        bone.quaternion.copy(_qa).slerp(_qb, localT);
      }

      if (progress < 1) requestAnimationFrame(step);
      else resolve();
    }
    requestAnimationFrame(step);
  });
}

// 큐에서 다음 단어의 캐시된 모션을 미리보기 (peek).
function _peekNextMotion() {
  if (!isPlayingQueue) return null;
  const nextIdx = currentIndex + 1;
  if (nextIdx >= signLanguageQueue.length) return null;
  const nextItem = signLanguageQueue[nextIdx];
  const nextWord = typeof nextItem === 'string' ? nextItem : (nextItem?.word || '');
  return nextItem?.motion || CACHE.get(nextWord) || null;
}

// ── 두 keyframe 사이 보간 (Quaternion slerp) ────────────────
// V3 JSON:  arm/forearm 은 WORLD space slerp → parent_chain 으로 local 변환.
// V4 JSON:  위 + handshape_right/left (수형 이름) → 라이브러리 offset 을 rest 에 합성.
//
// Hand bone 이름은 'Hand(Thumb|Index|Middle|Ring|Pinky)\d' 패턴. 아래 정규식으로 구분.
const HAND_BONE_RE = /Hand(Thumb|Index|Middle|Ring|Pinky)\d/;

function _isHandBone(name) { return HAND_BONE_RE.test(name); }

// 데이터 측 본 이름이 'mixamorig:' 접두어 유무 어느 쪽이든 모델 본을 찾도록 양방향 lookup.
function _resolveBone(avatar, name) {
  const b = avatar.bones[name];
  if (b) return b;
  if (name.startsWith('mixamorig:')) {
    const stripped = name.slice('mixamorig:'.length);
    return avatar.bones[stripped] || null;
  }
  return avatar.bones['mixamorig:' + name] || null;
}

function _applyInterpolated(avatar, prevKF, nextKF, t, scratch, motion) {
  const isWorld = motion?.space === 'world';
  const parentChain = motion?.parent_chain || {};
  const hasParentChain = Object.keys(parentChain).length > 0;
  const lib = _handshapeLib || {};

  // 수형 선택 (keyframe override → motion default → 자동 보완).
  // 수형 전환은 단어 내에서 드물다는 전제. prev→next 가 다른 수형이면 단순히 next 로 snap.
  let hsRightName = nextKF.handshape_right || motion.handshape_right || null;
  let hsLeftName = nextKF.handshape_left || motion.handshape_left || null;

  // [2026-05-22] Supabase 등 손가락 본이 누락된 모션 자동 보완:
  // keyframe 에 손가락 본이 하나도 없고 handshape 도 미지정이면 기본 수형('5지')으로 채움.
  if (!hsRightName) {
    const kfBones = Object.keys(nextKF.bones || {});
    const hasRightFinger = kfBones.some(n => /RightHand(Thumb|Index|Middle|Ring|Pinky)\d/.test(n));
    if (!hasRightFinger && kfBones.some(n => n.includes('Right'))) {
      hsRightName = motion._autoHandshapeR || '5지';
    }
  }
  if (!hsLeftName) {
    const kfBones = Object.keys(nextKF.bones || {});
    const hasLeftFinger = kfBones.some(n => /LeftHand(Thumb|Index|Middle|Ring|Pinky)\d/.test(n));
    if (!hasLeftFinger && kfBones.some(n => n.includes('Left'))) {
      hsLeftName = motion._autoHandshapeL || '5지';
    }
  }

  const hsRight = hsRightName && lib[hsRightName] ? lib[hsRightName] : null;
  const hsLeft = hsLeftName && lib[hsLeftName] ? lib[hsLeftName] : null;

  // 1. 키프레임의 본을 모두 수집. 손가락 본은 해당 손에 handshape이 지정된 경우에만 제외
  //    (그 손은 handshape 라이브러리가 별도로 덮어쓸 것이므로). 그 외엔 raw quaternion 슬러프.
  const skipFingerForSide = (n) => {
    if (!_isHandBone(n)) return false;
    if (hsRightName && n.includes('Right')) return true;
    if (hsLeftName && n.includes('Left')) return true;
    return false;
  };
  const allBones = new Set();
  for (const n of Object.keys(prevKF.bones || {})) if (!skipFingerForSide(n)) allBones.add(n);
  for (const n of Object.keys(nextKF.bones || {})) if (!skipFingerForSide(n)) allBones.add(n);

  const worldQuats = new Map();
  for (const bName of allBones) {
    const qp = prevKF.bones[bName];
    const qn = nextKF.bones[bName] || qp;
    if (!qp) continue;
    const qa = scratch.get(bName + '_a') || (scratch.set(bName + '_a', new THREE.Quaternion()).get(bName + '_a'));
    const qb = scratch.get(bName + '_b') || (scratch.set(bName + '_b', new THREE.Quaternion()).get(bName + '_b'));
    qa.set(qp.x, qp.y, qp.z, qp.w);
    qb.set(qn.x, qn.y, qn.z, qn.w);
    const qout = new THREE.Quaternion().copy(qa).slerp(qb, t);
    worldQuats.set(bName, qout);
  }

  // 2. arm bone 에 적용 — 정확한 world→local 변환
  //
  //  핵심 수식 (본 자체 W_rest 사용):
  //    W_new = wq * W_rest_self           [bone 의 새 world quat]
  //    bone.quaternion = inverse(parent.getWorldQuaternion()) * W_new
  //
  //  Parent 의 world quat 은 three.js 가 제공 (이미 갱신된 부모 반영).
  //  따라서 부모-자식 순서로 적용 + bone.updateMatrixWorld() 로 자식에게 전파.
  if (!isWorld) {
    // Legacy local space: 그냥 적용
    for (const [bName, wq] of worldQuats) {
      const bone = _resolveBone(avatar, bName);
      if (bone) bone.quaternion.copy(wq);
    }
  } else {
    const restWorld = avatar._armRestWorld || new Map();
    const _tmpW = new THREE.Quaternion();
    const _tmpP = new THREE.Quaternion();

    // 부모-자식 순서 결정:
    //   - motion.parent_chain 이 있으면 그 깊이를 사용 (root → forearm → hand → finger)
    //   - 비어 있으면 (Supabase v26 등) 실제 본 트리에서 Bone parent 카운트로 폴백
    const skeletalDepth = (bName) => {
      const bone = _resolveBone(avatar, bName);
      if (!bone) return 0;
      let d = 0, cur = bone.parent;
      while (cur && cur.isBone) { d++; cur = cur.parent; if (d > 30) break; }
      return d;
    };
    const depth = (n) => {
      if (hasParentChain) {
        let d = 0, cur = n;
        while (parentChain[cur]) { d++; cur = parentChain[cur]; if (d > 30) break; }
        return d;
      }
      return skeletalDepth(n);
    };
    const ordered = [...worldQuats.keys()].sort((a, b) => depth(a) - depth(b));

    for (const bName of ordered) {
      const bone = _resolveBone(avatar, bName);
      if (!bone) continue;

      const wq = worldQuats.get(bName);
      // restWorld 에는 'mixamorig:'이 있든 없든 실제 bone.name 으로 저장되어 있음
      const Wrest = restWorld.get(bone.name);

      if (!Wrest) {
        bone.quaternion.copy(wq);
      } else {
        // W_new = wq * W_rest
        _tmpW.copy(wq).multiply(Wrest);
        // 부모의 현재 world quat (three.js 에서 직접)
        bone.parent.getWorldQuaternion(_tmpP);
        // bone.quaternion = inverse(parentWorld) * W_new
        bone.quaternion.copy(_tmpP).invert().multiply(_tmpW);
      }
      // 자식이 부모 world 를 다시 읽을 때 최신값 보이도록 강제 갱신
      bone.updateMatrixWorld(true);
    }
  }

  // 3. 수형 적용 — keyframe 에 raw 손가락 quat 가 있으면 위에서 이미 처리됨.
  //     handshape_right/left 가 명시된 경우에만 라이브러리 offset 으로 덮어씀.
  if (window.ITDAHandshape) {
    if (hsRightName) window.ITDAHandshape.applyOne(avatar, hsRightName, 'Right');
    if (hsLeftName) window.ITDAHandshape.applyOne(avatar, hsLeftName, 'Left');
  } else {
    // Fallback: 로더 없으면 rest × offset 직접
    _applyHandshapeOffset(avatar, hsRight, 'Right');
    _applyHandshapeOffset(avatar, hsLeft, 'Left');
  }

  // 4. 표정(Morph Targets) 적용 — Mediapipe keyframe 의 morphs 가 있으면 반영
  const morphs = nextKF.morphs || {};
  if (Object.keys(morphs).length > 0) {
    for (const [mName, val] of Object.entries(morphs)) {
      // 보간 적용: prevKF 에도 같은 morph 가 있으면 slerp 처럼 가중치 적용 가능하나,
      // 대부분 next 값으로 snap 해도 시각적으로 무난함. 필요 시 lerp 로 확장 가능.
      avatar.setMorphTarget(mName, val);
    }
  }

  // 5. [Retargeting 보정] — _applyInterpolated 안에서 부르지 않는다.
  //    setAsIdle 도 _applyInterpolated 를 호출하므로 여기서 부르면 idle pose 캡처에
  //    보정이 들어가 손목이 영구적으로 뒤틀린 상태로 저장된다. 보정은 _playCore 의
  //    update() 루프에서만 호출 — idle 영향 없음.
}

// ── 손목 좌표계 보정 (로드 시 일괄 적용) ─────────────────────
// [2026-05-22 리팩터] 기존: 매 프레임 재생 시 _applyRetargetCorrection 호출
//   → 단어별 예외('감사'), 소스 누락 시 보정 누락 등 불안정.
// 변경: 모션 로드 직후 keyframe 의 Hand 쿼터니언에 보정을 미리 곱함 (1회).
//   재생 시에는 보정 없이 순수 slerp 만 수행 → 안정적이고 일관됨.
const _retargetCfg = {
  enabled: true,
  appliesTo: ['all'],
  'openpose-aihub': {
    right: { axis: 'z', deg: -90 },
    left: { axis: 'z', deg: 90 },
  },
  'mediapipe-v27': {
    right: { axis: 'x', deg: 180 },
    left: { axis: 'x', deg: 180 },
  },
  'v27.3-twist': {
    right: { axis: 'x', deg: 180 },
    left: { axis: 'x', deg: 180 },
  },
  'v27.4-spine': {
    right: { axis: 'x', deg: 180 },
    left: { axis: 'x', deg: 180 },
  },
  'v26.0-master': {
    right: { axis: 'x', deg: 180 },
    left: { axis: 'x', deg: 180 },
  }
};
const _AXIS_VEC = {
  x: new THREE.Vector3(1, 0, 0),
  y: new THREE.Vector3(0, 1, 0),
  z: new THREE.Vector3(0, 0, 1),
};

// 콘솔 디버깅용 API 노출
window.ITDARetarget = {
  set: (source, side, axis, deg) => {
    if (!_retargetCfg[source]) _retargetCfg[source] = {};
    _retargetCfg[source][side] = { axis, deg };
    console.log(`[ITDARetarget] ${source} ${side} = ${axis} ${deg}°`);
  },
  disable: () => { _retargetCfg.enabled = false; console.log('[ITDARetarget] Disabled'); },
  enable: () => { _retargetCfg.enabled = true; console.log('[ITDARetarget] Enabled'); }
};

/**
 * 로드된 모션 데이터의 keyframe 에 wrist 보정을 미리 적용 (1회, in-place).
 * 이미 보정된 모션은 _retargetApplied 플래그로 중복 방지.
 */
function _bakeRetargetCorrection(motion) {
  if (!_retargetCfg.enabled) return;
  if (motion._retargetBaked) return;

  const src = motion?.source ?? '';
  let cfgSrc = _retargetCfg[src];
  if (!cfgSrc && src.startsWith('v27.')) {
    cfgSrc = { right: { axis: 'x', deg: 180 }, left: { axis: 'x', deg: 180 } };
  }
  if (!cfgSrc) { motion._retargetBaked = true; return; }

  const flipQuats = {};
  for (const side of ['right', 'left']) {
    const cfg = cfgSrc[side];
    if (!cfg || cfg.axis === 'none' || !cfg.deg) continue;
    const boneName = side === 'right' ? 'RightHand' : 'LeftHand';
    const axisVec = _AXIS_VEC[cfg.axis];
    if (!axisVec) continue;
    flipQuats[boneName] = new THREE.Quaternion().setFromAxisAngle(axisVec, cfg.deg * Math.PI / 180);
  }

  if (Object.keys(flipQuats).length === 0) { motion._retargetBaked = true; return; }

  const tmpQ = new THREE.Quaternion();
  for (const kf of (motion.keyframes || [])) {
    if (!kf.bones) continue;
    for (const [boneName, flipQ] of Object.entries(flipQuats)) {
      const bq = kf.bones[boneName];
      if (!bq) continue;
      tmpQ.set(bq.x, bq.y, bq.z, bq.w).multiply(flipQ);
      bq.x = tmpQ.x; bq.y = tmpQ.y; bq.z = tmpQ.z; bq.w = tmpQ.w;
    }
  }
  motion._retargetBaked = true;
  console.info(`[MotionV3] 손목 보정 baked (source="${src}", bones=${Object.keys(flipQuats).join(',')})`);

  // [2026-05-22] 손가락 본 부재 감지 → linguistic_features 수형으로 자동 보완 힌트 설정.
  // _applyInterpolated 에서 '5지' 폴백 전에 이 힌트가 있으면 우선 사용.
  const kf0 = (motion.keyframes || [])[0];
  if (kf0?.bones) {
    const boneNames = Object.keys(kf0.bones);
    const hasRFinger = boneNames.some(n => /RightHand(Thumb|Index|Middle|Ring|Pinky)\d/.test(n));
    const hasLFinger = boneNames.some(n => /LeftHand(Thumb|Index|Middle|Ring|Pinky)\d/.test(n));
    const lf = motion.linguistic_features?.handshape;
    if (!hasRFinger && lf?.right) {
      motion._autoHandshapeR = lf.right;
      console.info(`[MotionV3] 오른손 손가락 본 없음 → 수형 "${lf.right}" 자동 적용 예정`);
    }
    if (!hasLFinger && lf?.left) {
      motion._autoHandshapeL = lf.left;
      console.info(`[MotionV3] 왼손 손가락 본 없음 → 수형 "${lf.left}" 자동 적용 예정`);
    }
  }
}

// Legacy: 재생 시 호출용 (이제 no-op — bake 로 대체)
function _applyRetargetCorrection(_avatar, _motion, _word) {
  // 보정이 로드 시점에서 bake 되었으므로 재생 시에는 아무것도 하지 않음.
}





// ── Fallback: 수형 offset 을 rest 에 합성 ──────────────────
function _applyHandshapeOffset(avatar, shape, side) {
  if (!shape || !avatar?._handshapeRest) return;
  const rest = avatar._handshapeRest;
  const prefix = side + 'Hand';
  const tmp = new THREE.Quaternion();
  for (const [bn, q] of Object.entries(shape)) {
    if (!bn.startsWith(prefix)) continue;
    const bone = _resolveBone(avatar, bn);
    const r = rest[bn];
    if (!bone || !r) continue;
    tmp.set(q.x, q.y, q.z, q.w);
    bone.quaternion.copy(r).multiply(tmp);
  }
}

// playMotion 시작 시 손가락 본 rest 저장
function _captureHandRest(avatar) {
  if (avatar._handshapeRest) return;
  const rest = {};
  for (const name of Object.keys(avatar.bones || {})) {
    if (_isHandBone(name)) rest[name] = avatar.bones[name].quaternion.clone();
  }
  avatar._handshapeRest = rest;
}

// 본 자체의 world rest quat 저장 (모든 본 커버 — Spine/Neck/Arm/ForeArm/Hand/손가락 5×3).
// 매 프레임 W_new = wq * W_rest_self 로 합성, 부모-자식 순서로 local 변환.
//
// Idle 클립이 본을 변형해 놓은 상태에서 캡처하면 rest 가 아닌 애니메이팅 포즈가 박히므로,
// 캡처 직전에 모든 본을 GLB initial local quat 으로 임시 복원했다가 캡처 후 원상태로 되돌린다.
function _captureArmRestWorld(avatar) {
  if (avatar._armRestWorld) return;
  const initialQuats = avatar.initialBoneQuats || {};
  const bonesObj = avatar.bones || {};

  // 1) 현재 quat 저장 + initial 로 복원
  const saved = new Map();
  for (const [name, bone] of Object.entries(bonesObj)) {
    saved.set(name, bone.quaternion.clone());
    const init = initialQuats[name];
    if (init) bone.quaternion.copy(init);
  }
  // 2) matrixWorld 갱신 (자식이 부모의 새 quat 을 보도록)
  for (const bone of Object.values(bonesObj)) bone.updateMatrixWorld(true);

  // 3) 모든 본의 world quat 캡처 — bone.name(접두어 포함) 기준
  const map = new Map();
  for (const bone of Object.values(bonesObj)) {
    const wq = new THREE.Quaternion();
    bone.getWorldQuaternion(wq);
    map.set(bone.name, wq);
  }

  // 4) 원상복구 + matrixWorld 재갱신
  for (const [name, bone] of Object.entries(bonesObj)) {
    const s = saved.get(name);
    if (s) bone.quaternion.copy(s);
  }
  for (const bone of Object.values(bonesObj)) bone.updateMatrixWorld(true);

  avatar._armRestWorld = map;
  console.info(`[MotionV3] rest-world quat 캐시 완료: ${map.size}개 본 (전체)`);
}

// ── 초기 자세로 부드럽게 복귀 (V2 엔진과 동일 톤) ───────────
async function _returnToInitial(avatar, initialQuats, duration = 800) {
  const startTime = performance.now();
  const currentQuats = new Map();
  for (const [bName] of initialQuats) {
    const bone = _resolveBone(avatar, bName);
    if (bone) currentQuats.set(bName, bone.quaternion.clone());
  }
  return new Promise((resolve) => {
    function step(now) {
      const progress = Math.min((now - startTime) / duration, 1);
      for (const [bName, initQ] of initialQuats) {
        const bone = _resolveBone(avatar, bName);
        const from = currentQuats.get(bName);
        if (bone && from) bone.quaternion.copy(from).slerp(initQ, progress);
      }
      if (progress < 1) requestAnimationFrame(step);
      else resolve();
    }
    requestAnimationFrame(step);
  });
}

/**
 * ── 순차 재생 대기열 (Queue System) ─────────────────────────────────────
 * [3단계 & 4단계: 바구니(Queue) 생성 및 조건문 연결]
 */
// 1. 수어 애니메이션들을 차례대로 담아둘 대기열(바구니)입니다.
let signLanguageQueue = [];
let currentIndex = 0;
let isPlayingQueue = false;
let queueOptions = {};
let queueStats = { played: 0, skipped: 0, failed: 0 };
let queueResolve = null;

// 3. 다음 수어 동작을 판단하고 연결하는 핵심 함수
async function playNextSign() {
  // 바구니에 담긴 단어가 더 이상 없으면 종료 처리
  if (currentIndex >= signLanguageQueue.length) {
    // [2단계 분리] 모든 문장이 끝났을 때만 최종 처리를 진행
    window.translationModeActive = false;
    window.dispatchEvent(new CustomEvent('itda:sequence:played', {
      detail: { count: signLanguageQueue.length, ...queueStats }
    }));
    console.info(`[MotionV3 Queue] 모두 완료 (총 ${queueStats.played}단어 재생)`);
    isPlayingQueue = false;
    if (queueResolve) queueResolve(queueStats);
    queueResolve = null;
    return;
  }

  const it = signLanguageQueue[currentIndex];
  const word = typeof it === 'string' ? it : (it.word || '');
  const inlineMotion = typeof it === 'object' ? it.motion : null;
  const isLast = (currentIndex === signLanguageQueue.length - 1);
  const gapMs = Number.isFinite(queueOptions.gapMs) ? queueOptions.gapMs : 0; // 전환 애니메이션이 갭을 대체

  if (queueOptions.onWord) queueOptions.onWord(word, currentIndex, signLanguageQueue.length);
  console.log(`[Queue] "${word}" 수어 동작을 실행합니다.`);

  let wasSeamlessVideo = false;
  try {
    let motion = inlineMotion;
    if (!motion) motion = await loadMotion(word);
    if (motion && !motion.keyframes?.length && motion.video_url) {
      const nextIsVideo = _isNextItemVideo(currentIndex);
      const videoSrc = motion._blobUrl || motion.video_url;
      // 적응형 trimEnd: 영상 길이의 40% 이하, 최대 1.8초
      const dur = motion.duration_s || 4.0;
      const trimEnd = Math.min(1.8, dur * 0.3);

      // 다음 영상 URL 확보 (더블 버퍼링 preload용)
      let nextVideoUrl = null;
      if (nextIsVideo) {
        const ni = currentIndex + 1;
        const nextIt = signLanguageQueue[ni];
        const nw = typeof nextIt === 'string' ? nextIt : (nextIt?.word || '');
        const nm = nextIt?.motion || CACHE.get(nw);
        if (nm) nextVideoUrl = nm._blobUrl || nm.video_url;
      }

      console.info(`[MotionV3 Queue] "${word}" 영상 재생 (skipFadeOut=${nextIsVideo}, trimEnd=${trimEnd}s)`);
      await _playVideoOnly(videoSrc, word, { skipFadeOut: nextIsVideo, trimEnd, nextUrl: nextVideoUrl });
      queueStats.played++;
      wasSeamlessVideo = nextIsVideo;
    } else if (!motion || !motion.keyframes?.length) {
      console.warn(`[MotionV3 Queue] "${word}" 모션 데이터 없음`);
      queueStats.skipped++;
    } else {
      // [핵심] 현재 단어 애니메이션 실행
      // skipReturn: !isLast 를 통해 마지막 단어가 아니면 기본자세 원복 생략 (2단계, 4단계)
      await _playCore(motion, word, {
        isPartOfSequence: true,
        skipReturn: !isLast,
      });
      queueStats.played++;
    }
  } catch (e) {
    console.error(`[MotionV3 Queue] "${word}" 재생 에러 — 다음 단어로 계속:`, e);
    queueStats.failed++;
  }

  // 애니메이션 종료 직후
  currentIndex++; // 다음 단어 번호로 넘어가기

  if (currentIndex < signLanguageQueue.length) {
    // 연속 영상일 때는 gap도 생략 (src 교체만으로 즉시 연결)
    if (gapMs > 0 && !wasSeamlessVideo) await new Promise(r => setTimeout(r, gapMs));
    console.log(`[Queue] 다음 단어로 연결 (seamless=${wasSeamlessVideo})`);
    playNextSign();
  } else {
    // 진짜 마지막 단어라면 대기열을 끝내기 위해 재생 함수를 다시 부름 (안에서 종료 조건에 걸러짐)
    playNextSign();
  }
}

// playNextSign의 최상위 에러 보호 — 어떤 에러든 translationModeActive 리셋 보장
const _originalPlayNextSign = playNextSign;
playNextSign = async function () {
  try {
    await _originalPlayNextSign();
  } catch (e) {
    console.error('[MotionV3 Queue] 치명적 에러 — 시퀀스 강제 종료:', e);
    window.translationModeActive = false;
    isPlayingQueue = false;
    if (queueResolve) queueResolve(queueStats);
    queueResolve = null;
  }
};

// 2. 문장 전체를 읽어서 단어별 애니메이션을 준비하는 함수
async function playSequence(items, opts = {}) {
  if (!Array.isArray(items) || items.length === 0) return { played: 0, skipped: 0, failed: 0 };

  // [사전 동시 로딩(Preload)]
  // 재생 중간에 데이터를 불러오느라 캐릭터가 멈칫하거나 기본 자세로 풀려버리는 것을 방지하기 위해,
  // 문장에 포함된 모든 단어 모션을 백그라운드에서 동시에(병렬로) 미리 전부 가져옵니다.
  console.info(`[MotionV3 Queue] 문장 내 전체 단어 사전 로딩(Preload) 시작...`);
  const prefetchPromises = items.map(it => {
    const word = typeof it === 'string' ? it : (it.word || '');
    const inlineMotion = typeof it === 'object' ? it.motion : null;
    // inline motion이 이미 있으면 CACHE에 직접 넣고 loadMotion 건너뜀
    if (inlineMotion) {
      CACHE.set(word, inlineMotion);
      return Promise.resolve();
    }
    return word ? loadMotion(word) : Promise.resolve();
  });
  await Promise.all(prefetchPromises);

  // [영상 Blob 사전 다운로드] 네트워크 지연 없이 즉시 재생하기 위해
  // 모든 영상 URL을 Blob으로 미리 받아 로컬 URL로 교체
  const blobPromises = items.map(async (it) => {
    const word = typeof it === 'string' ? it : (it.word || '');
    const motion = CACHE.get(word);
    if (!motion?.video_url || motion._blobUrl) return;
    try {
      const resp = await fetch(motion.video_url);
      if (resp.ok) {
        const blob = await resp.blob();
        motion._blobUrl = URL.createObjectURL(blob);
        console.info(`[Preload] 영상 Blob 캐시: "${word}" (${(blob.size / 1024).toFixed(0)}KB)`);
      }
    } catch (e) {
      console.warn(`[Preload] 영상 다운로드 실패: "${word}"`, e.message);
    }
  });
  await Promise.all(blobPromises);
  console.info(`[MotionV3 Queue] 문장 사전 로딩 완료! 즉시 재생 시작.`);

  // 바구니에 단어 셋팅
  signLanguageQueue = items;
  currentIndex = 0;
  isPlayingQueue = true;
  queueOptions = opts;
  queueStats = { played: 0, skipped: 0, failed: 0 };

  window.translationModeActive = true;
  await _loadHandshapeLib();

  return new Promise((resolve) => {
    queueResolve = resolve;
    // 첫 번째 단어 수어 시작 (이제 끊김 없이 즉시 캐시에서 꺼내어 재생됨)
    playNextSign();
  });
}


// ── 공개 API ────────────────────────────────────────────────
window.ITDAMotionV3 = {
  load: loadMotion,
  play: playMotion,
  playDirect: playDirect,
  playSequence: playSequence,
  has: hasMotion,
  setAsIdle: async function (word) {
    const motion = await loadMotion(word);
    if (!motion || !motion.keyframes?.length) return false;
    if (window.ITDAAvatar5) {
      window.ITDAAvatar5.stopIdle?.();
      _captureHandRest(window.ITDAAvatar5);
      _captureArmRestWorld(window.ITDAAvatar5);
      const kf = motion.keyframes[0];
      const scratch = new Map();
      _applyInterpolated(window.ITDAAvatar5, kf, kf, 1.0, scratch, motion);
      // [2026-05-07d] avatar.initialBoneQuats(GLB bind=T-pose) 는 절대 덮지 않는다.
      //   대신 _idlePoseQuats 별도 캡처 — 이게 모션 종료 후 복귀 anchor 가 된다.
      //   결과: 모션이 끝나면 T-pose 가 아니라 자연스러운 차렷/감사 자세로 마무리.
      _idlePoseQuats = {};
      for (const bone of Object.values(window.ITDAAvatar5.bones || {})) {
        _idlePoseQuats[bone.name] = bone.quaternion.clone();
      }
      console.info(`[MotionV3] Idle pose 캡처 완료 ("${word}" 시작 자세, 본 ${Object.keys(_idlePoseQuats).length}개)`);
    }
  },
  _cache: CACHE,
  _build: _MV3_BUILD,

  /**
   * [Debug] 손목 좌표계 보정을 콘솔에서 즉석 시험.
   *   ITDARetarget.show()                          현재 설정 확인
   *   ITDARetarget.set('right','y',180)            오른손 Y축 180°
   *   ITDARetarget.set('right','x',180)            오른손 X축 180° (손바닥 위↔아래)
   *   ITDARetarget.set('right','z',180)            오른손 Z축 180° (손가락 앞↔뒤)
   *   ITDARetarget.set('right','none',0)           보정 끔
   *   ITDARetarget.set('left','y',180)             왼손도 같이
   *   ITDARetarget.disable() / enable()            전체 보정 ON/OFF
   * 변경 후 다음 단어 재생 시 즉시 반영. 같은 단어를 다시 재생하려면 캐시 미사용.
   */
  retarget: {
    show: () => { console.table(_retargetCfg); return _retargetCfg; },
    set: (side, axis, deg) => {
      if (!['right', 'left'].includes(side)) return console.warn('side: right|left');
      if (!['x', 'y', 'z', 'none'].includes(axis)) return console.warn('axis: x|y|z|none');
      _retargetCfg[side] = { axis, deg: Number(deg) || 0 };
      console.info(`[Retarget] ${side} = ${axis} ${deg}°`);
    },
    enable: () => { _retargetCfg.enabled = true; console.info('[Retarget] enabled'); },
    disable: () => { _retargetCfg.enabled = false; console.info('[Retarget] disabled'); },
    appliesTo: (sources) => {
      _retargetCfg.appliesTo = Array.isArray(sources) ? sources : [sources];
      console.info(`[Retarget] appliesTo:`, _retargetCfg.appliesTo);
    },
    /**
     * [자동 시험] 보정 후보를 단어 1개에 대해 순환 재생.
     * 각 후보를 적용하고 word 를 재생 → 다음 후보 진행 (단어 끝나면 0.8초 휴식).
     *
     * 사용:
     *   ITDARetarget.cycle('감사')              모든 후보 (0~7)
     *   ITDARetarget.cycle('감사', [0,2,7])     선택 후보만
     *   ITDARetarget.cycle('감사', [2,7], { keepMarkers: true })  본 마커 표시 유지
     *
     * 시작 시 본 마커(어깨/상완/손 컬러 sphere) 자동 숨김 → 종료 시 복원.
     */
    cycle: async (word = '감사', indices = null, opts = {}) => {
      const candidates = [
        { side: 'right', axis: 'none', deg: 0, label: '0) 보정 OFF (raw)' },
        { side: 'right', axis: 'x', deg: 180, label: '1) RH X 180' },
        { side: 'right', axis: 'y', deg: 180, label: '2) RH Y 180' },
        { side: 'right', axis: 'z', deg: 180, label: '3) RH Z 180' },
        { side: 'right', axis: 'x', deg: 90, label: '4) RH X +90' },
        { side: 'right', axis: 'x', deg: -90, label: '5) RH X -90' },
        { side: 'right', axis: 'z', deg: 90, label: '6) RH Z +90' },
        { side: 'right', axis: 'z', deg: -90, label: '7) RH Z -90' },
      ];
      const selected = Array.isArray(indices) && indices.length
        ? indices.map(i => candidates[i]).filter(Boolean)
        : candidates;

      const avatar = window.ITDAAvatar5;
      const markersWereShown = !opts.keepMarkers && avatar?.setBoneMarkersVisible;
      if (markersWereShown) avatar.setBoneMarkersVisible(false);

      // [WEBCAM 미러링 차단] cycle 진행 중 webcam→아바타 retargeting 이 끼어들지 않도록 lock.
      // _playCore 가 단독 재생 종료 시 false 로 풀므로, isPartOfSequence=true 로 호출하여 그것도 방지.
      const prevTranslationMode = window.translationModeActive;
      window.translationModeActive = true;

      console.group(`[Retarget Cycle] 시작 — ${selected.length}개 후보 순환. 정답 번호 기억하세요.`);
      for (const c of selected) {
        _retargetCfg[c.side] = { axis: c.axis, deg: c.deg };
        console.info(`▶ ${c.label}`);
        await window.ITDAMotionV3.play(word, { isPartOfSequence: true });
        await new Promise(r => setTimeout(r, 800));
      }
      console.info('완료. 정답 번호 알려주시면 코드 디폴트로 적용합니다.');
      console.groupEnd();

      window.translationModeActive = prevTranslationMode;
      if (markersWereShown) avatar.setBoneMarkersVisible(true);
    },
    /**
     * webcam → 아바타 미러링 영구 ON/OFF 토글 (cycle 외에도 수동으로 끄고 싶을 때).
     *   ITDARetarget.lockMirror()    미러링 차단 (translationModeActive=true 고정)
     *   ITDARetarget.unlockMirror()  미러링 재개
     */
    lockMirror: () => {
      window.translationModeActive = true;
      window.__retargetMirrorLocked = true;
      console.info('[Retarget] webcam 미러링 차단됨 (lockMirror)');
    },
    unlockMirror: () => {
      window.translationModeActive = false;
      window.__retargetMirrorLocked = false;
      console.info('[Retarget] webcam 미러링 재개됨');
    },
  },

  /**
   * [Debug] 진단 헬퍼 — 콘솔에서 ITDAMotionV3.diagnose('감사') 로 호출.
   * 빌드 버전, motion 구조, rest-world 캐시 크기, 본 매칭 상태를 출력.
   */
  diagnose: async function (word = '감사') {
    const avatar = window.ITDAAvatar5;
    console.group(`[MotionV3 Diagnose] "${word}"`);
    console.info('build =', _MV3_BUILD);
    console.info('avatar bones =', Object.keys(avatar?.bones || {}).length);
    console.info('rest-world cache size =', avatar?._armRestWorld?.size ?? 'NOT-CAPTURED');
    const motion = await loadMotion(word);
    if (!motion) { console.warn('motion 로드 실패'); console.groupEnd(); return; }
    console.info('motion source =', motion.source, '/ space =', motion.space);
    console.info('parent_chain entries =', Object.keys(motion.parent_chain || {}).length);
    console.info('keyframe count =', motion.keyframes?.length);
    const kf0 = motion.keyframes?.[0];
    if (kf0) {
      const boneNames = Object.keys(kf0.bones || {});
      const fingerNames = boneNames.filter(n => /Hand(Thumb|Index|Middle|Ring|Pinky)\d/.test(n));
      console.info('kf0 bone count =', boneNames.length, '/ finger bones =', fingerNames.length);
      // 각 keyframe 본이 실제 avatar 본에 매칭되는지 검사
      const missing = [];
      for (const n of boneNames) {
        const b = _resolveBone(avatar, n);
        if (!b) missing.push(n);
      }
      if (missing.length) console.warn('avatar 에 매칭 안 되는 본:', missing);
      else console.info('모든 keyframe 본이 avatar 에 매칭됨 ✓');
    }
    console.groupEnd();
  },
};

// 짧은 alias 노출 — 콘솔에서 ITDARetarget.cycle('감사') 로 바로 호출 가능
window.ITDARetarget = window.ITDAMotionV3.retarget;

console.info('[MotionV3] 로더 준비됨. ITDAMotionV3.play("<단어>") 로 호출 가능.');

// ── URL 쿼리 파라미터 ?autoplay=WORD0001 로 자동 재생 (검증 편의 기능) ──
(function _autoplay() {
  const params = new URLSearchParams(location.search);
  const target = params.get('autoplay');
  if (!target) return;
  console.info(`[MotionV3] autoplay 요청: ${target} (아바타 로드 후 재생 예약)`);
  // 아바타가 로드된 후에만 가능. 준비 이벤트가 이미 지났을 수 있으므로 폴링.
  let attempts = 0;
  const timer = setInterval(() => {
    attempts++;
    if (window.ITDAAvatar5?.bones && Object.keys(window.ITDAAvatar5.bones).length > 0) {
      clearInterval(timer);
      console.info(`[MotionV3] 아바타 준비됨 → ${target} 재생 시작`);
      window.ITDAAvatar5.stopIdle?.();
      setTimeout(() => playMotion(target), 500);   // 렌더 안정화 후 재생
    } else if (attempts > 60) {
      clearInterval(timer);
      console.warn('[MotionV3] 아바타 로드 타임아웃');
    }
  }, 500);
})();

// ── [검증 편의] WORD 번호 순회 재생 ────────────────────────
// 사용법: ITDAMotionV3.browse(start=1, end=10)
// 각 WORD 를 재생하고 자동으로 다음으로 넘김. Console 에서 품질 스팟 체크용.
async function browseRange(start = 1, end = 10) {
  for (let n = start; n <= end; n++) {
    const word = `WORD${String(n).padStart(4, '0')}`;
    const exists = await hasMotion(word);
    if (!exists && !CACHE.has(word)) {
      // 시도: 파일이 실제로 존재하는지 직접 체크
      const m = await loadMotion(word);
      if (!m) { console.info(`[browse] ${word} 없음, 스킵`); continue; }
    }
    console.info(`[browse] ▶ ${word} (${n - start + 1}/${end - start + 1})`);
    await playMotion(word);
    await new Promise(r => setTimeout(r, 500));  // 간격
  }
  console.info('[browse] 완료');
}
window.ITDAMotionV3.browse = browseRange;

// ── 기본 Idle 자세 설정 (감사 시작 자세) ────────────────────
(function _setDefaultIdle() {
  let attempts = 0;
  const timer = setInterval(() => {
    attempts++;
    if (window.ITDAAvatar5?.bones && Object.keys(window.ITDAAvatar5.bones).length > 0) {
      clearInterval(timer);
      const params = new URLSearchParams(location.search);
      // 만약 autoplay 중이 아니라면 기본 Idle 자세를 설정
      if (!params.get('autoplay')) {
        // '감사' 동작의 첫 프레임으로 정중한 인사 자세 설정
        setTimeout(() => {
          window.ITDAMotionV3.setAsIdle('감사');
          console.info('[MotionV3] 초기 자세 설정 완료: 감사');
        }, 1200); // 렌더링 안정화를 위해 충분한 시간 부여
      }
    } else if (attempts > 60) {
      clearInterval(timer);
    }
  }, 500);
})();
