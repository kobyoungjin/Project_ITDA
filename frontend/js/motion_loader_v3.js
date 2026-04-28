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

const CACHE = new Map();
const INDEX_URL = './data/ksl_motions/index.json';
const HANDSHAPE_LIB_URL = './data/handshape_library.json';
let _index = null;
let _handshapeLib = null;

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
  const url = `./data/ksl_motions/${encodeURIComponent(word)}.json`;
  try {
    const res = await fetch(url, { cache: 'no-cache' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const motion = await res.json();
    // v3 또는 v4 지원
    if (motion.version !== 'v3' && motion.version !== 'v4') {
      console.warn(`[MotionV3] ${word}: version=${motion.version} (v3/v4 아님)`);
    }
    CACHE.set(word, motion);
    return motion;
  } catch (e) {
    console.info(`[MotionV3] ${word} 미발견 (${e.message}) — V2 폴백 예정`);
    return null;
  }
}

async function hasMotion(word) {
  if (CACHE.has(word)) return true;
  const idx = await _loadIndex();
  return idx.actions?.includes(word) ?? false;
}

// ── Keyframe 재생 (Quaternion slerp) ────────────────────────
async function playMotion(word) {
  const avatar = window.ITDAAvatar5;
  if (!avatar) { console.warn('[MotionV3] 아바타 미로드'); return; }

  const [motion, _lib] = await Promise.all([loadMotion(word), _loadHandshapeLib()]);
  if (!motion || !motion.keyframes?.length) return false;

  // Idle 간섭 제거
  avatar.stopIdle?.();
  window.translationModeActive = true;

  // 손가락 rest 캐시 (한 번만). 수형 offset 합성 시 사용.
  _captureHandRest(avatar);
  // arm/forearm/hand 본의 자체 world rest quat 캐시 (한 번만).
  _captureArmRestWorld(avatar);

  const keyframes = motion.keyframes;
  const totalDuration = keyframes[keyframes.length - 1].time;
  console.info(`[MotionV3] 재생 "${word}" (${keyframes.length} keyframes, ${totalDuration.toFixed(2)}s)`);

  const startTime = performance.now();
  const targetQuats = new Map();

  // 복귀용 initial quat: arm + 손가락 rest 전부 포함
  const touchedBones = new Set();
  for (const kf of keyframes) for (const bName of Object.keys(kf.bones)) touchedBones.add(bName);
  // 손가락 rest 도 복귀 대상에 포함 (수형이 적용되면 본이 변했으므로 원복 필요)
  for (const bName of Object.keys(avatar._handshapeRest || {})) touchedBones.add(bName);

  const initialQuats = new Map();
  for (const bName of touchedBones) {
    const bone = avatar.bones[bName] || avatar.bones['mixamorig:' + bName];
    if (bone) initialQuats.set(bName, bone.quaternion.clone());
  }

  return new Promise((resolve) => {
    function update(now) {
      const elapsed = (now - startTime) / 1000;  // 초

      if (elapsed >= totalDuration) {
        // 마지막 keyframe 값으로 마무리
        const lastKF = keyframes[keyframes.length - 1];
        _applyInterpolated(avatar, lastKF, lastKF, 1.0, targetQuats, motion);
        _returnToInitial(avatar, initialQuats).then(() => {
          window.translationModeActive = false;
          window.dispatchEvent(new CustomEvent('itda:motion:played', {
            detail: { keyword: word, source: motion.source || 'v3' }
          }));
          resolve();
        });
        return;
      }

      // 현재 시각을 감싸는 두 keyframe 찾기
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

      requestAnimationFrame(update);
    }
    requestAnimationFrame(update);
  });
}

// ── 두 keyframe 사이 보간 (Quaternion slerp) ────────────────
// V3 JSON:  arm/forearm 은 WORLD space slerp → parent_chain 으로 local 변환.
// V4 JSON:  위 + handshape_right/left (수형 이름) → 라이브러리 offset 을 rest 에 합성.
//
// Hand bone 이름은 'Hand(Thumb|Index|Middle|Ring|Pinky)\d' 패턴. 아래 정규식으로 구분.
const HAND_BONE_RE = /Hand(Thumb|Index|Middle|Ring|Pinky)\d/;

function _isHandBone(name) { return HAND_BONE_RE.test(name); }

function _applyInterpolated(avatar, prevKF, nextKF, t, scratch, motion) {
  const isWorld = motion?.space === 'world';
  const parentChain = motion?.parent_chain || {};
  const lib = _handshapeLib || {};

  // 수형 선택 (keyframe override → motion default).
  // 수형 전환은 단어 내에서 드물다는 전제. prev→next 가 다른 수형이면 단순히 next 로 snap.
  const hsRightName = nextKF.handshape_right || motion.handshape_right || null;
  const hsLeftName  = nextKF.handshape_left  || motion.handshape_left  || null;
  const hsRight = hsRightName && lib[hsRightName] ? lib[hsRightName] : null;
  const hsLeft  = hsLeftName  && lib[hsLeftName]  ? lib[hsLeftName]  : null;

  // 1. arm/forearm 류 (keyframe.bones) 만 slerp (손가락은 수형으로 따로 처리)
  const allArmBones = new Set();
  for (const n of Object.keys(prevKF.bones || {})) if (!_isHandBone(n)) allArmBones.add(n);
  for (const n of Object.keys(nextKF.bones || {})) if (!_isHandBone(n)) allArmBones.add(n);

  const worldQuats = new Map();
  for (const bName of allArmBones) {
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
      const bone = avatar.bones[bName] || avatar.bones['mixamorig:' + bName];
      if (bone) bone.quaternion.copy(wq);
    }
  } else {
    const restWorld = avatar._armRestWorld || new Map();
    const _tmpW = new THREE.Quaternion();
    const _tmpP = new THREE.Quaternion();

    // 부모-자식 순서: parent_chain 깊이 기준 (root → forearm → hand)
    const depth = (n) => {
      let d = 0, cur = n;
      while (parentChain[cur]) { d++; cur = parentChain[cur]; if (d > 10) break; }
      return d;
    };
    const ordered = [...worldQuats.keys()].sort((a, b) => depth(a) - depth(b));

    for (const bName of ordered) {
      const bone = avatar.bones[bName] || avatar.bones['mixamorig:' + bName];
      if (!bone) continue;
      const wq = worldQuats.get(bName);
      const Wrest = restWorld.get(bName);

      if (!Wrest) {
        // Rest 캐시 없음 — 단순 적용 (수학적으로 부정확하지만 fallback)
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

  // 3. 수형 적용 — handshape_loader 가 오버라이드 체크 포함 (가상환경 반영)
  if (window.ITDAHandshape) {
    if (hsRightName) window.ITDAHandshape.applyOne(avatar, hsRightName, 'Right');
    if (hsLeftName)  window.ITDAHandshape.applyOne(avatar, hsLeftName,  'Left');
  } else {
    // Fallback: 로더 없으면 rest × offset 직접
    _applyHandshapeOffset(avatar, hsRight, 'Right');
    _applyHandshapeOffset(avatar, hsLeft,  'Left');
  }
}

// ── Fallback: 수형 offset 을 rest 에 합성 ──────────────────
function _applyHandshapeOffset(avatar, shape, side) {
  if (!shape || !avatar?._handshapeRest) return;
  const rest = avatar._handshapeRest;
  const prefix = side + 'Hand';
  const tmp = new THREE.Quaternion();
  for (const [bn, q] of Object.entries(shape)) {
    if (!bn.startsWith(prefix)) continue;
    const bone = avatar.bones[bn] || avatar.bones['mixamorig:' + bn];
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

// arm/forearm/hand 본 자체의 world rest quat 저장.
// 매 프레임 W_new = wq * W_rest_self 로 합성, 부모-자식 순서로 local 변환.
function _captureArmRestWorld(avatar) {
  if (avatar._armRestWorld) return;
  const map = new Map();
  const armBoneNames = ['RightArm','LeftArm','RightForeArm','LeftForeArm','RightHand','LeftHand'];
  for (const name of armBoneNames) {
    const bone = avatar.bones[name] || avatar.bones['mixamorig:' + name];
    if (!bone) continue;
    const wq = new THREE.Quaternion();
    bone.getWorldQuaternion(wq);
    map.set(name, wq);
  }
  avatar._armRestWorld = map;
  console.info(`[MotionV3] arm rest world quats 캐시: ${map.size}개`);
}

// ── 초기 자세로 부드럽게 복귀 (V2 엔진과 동일 톤) ───────────
async function _returnToInitial(avatar, initialQuats) {
  const duration = 800;
  const startTime = performance.now();
  const currentQuats = new Map();
  for (const [bName] of initialQuats) {
    const bone = avatar.bones[bName] || avatar.bones['mixamorig:' + bName];
    if (bone) currentQuats.set(bName, bone.quaternion.clone());
  }
  return new Promise((resolve) => {
    function step(now) {
      const progress = Math.min((now - startTime) / duration, 1);
      for (const [bName, initQ] of initialQuats) {
        const bone = avatar.bones[bName] || avatar.bones['mixamorig:' + bName];
        const from = currentQuats.get(bName);
        if (bone && from) bone.quaternion.copy(from).slerp(initQ, progress);
      }
      if (progress < 1) requestAnimationFrame(step);
      else resolve();
    }
    requestAnimationFrame(step);
  });
}

// ── 공개 API ────────────────────────────────────────────────
window.ITDAMotionV3 = {
  load: loadMotion,
  play: playMotion,
  has: hasMotion,
  _cache: CACHE,
};

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
