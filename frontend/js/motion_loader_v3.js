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
let _index = null;

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

// ── 단일 모션 JSON 로드 + 캐싱 ─────────────────────────────
async function loadMotion(word) {
  if (CACHE.has(word)) return CACHE.get(word);
  const url = `./data/ksl_motions/${encodeURIComponent(word)}.json`;
  try {
    const res = await fetch(url, { cache: 'no-cache' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const motion = await res.json();
    if (motion.version !== 'v3') {
      console.warn(`[MotionV3] ${word}: version=${motion.version} (v3 아님)`);
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

  const motion = await loadMotion(word);
  if (!motion || !motion.keyframes?.length) return false;

  // Idle 간섭 제거
  avatar.stopIdle?.();
  window.translationModeActive = true;

  const keyframes = motion.keyframes;
  const totalDuration = keyframes[keyframes.length - 1].time;
  console.info(`[MotionV3] 재생 "${word}" (${keyframes.length} keyframes, ${totalDuration.toFixed(2)}s)`);

  const startTime = performance.now();
  const targetQuats = new Map();  // bone → THREE.Quaternion (reused)

  // 사용된 모든 본 이름 수집 + 초기 quaternion 저장 (복귀용)
  const touchedBones = new Set();
  for (const kf of keyframes) {
    for (const bName of Object.keys(kf.bones)) touchedBones.add(bName);
  }
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
        _applyKeyframe(avatar, keyframes[keyframes.length - 1].bones, 1.0, null);
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

      _applyInterpolated(avatar, prev.bones, next.bones, t, targetQuats);

      requestAnimationFrame(update);
    }
    requestAnimationFrame(update);
  });
}

// ── 두 keyframe 사이 보간 (Quaternion slerp) ────────────────
function _applyInterpolated(avatar, prevBones, nextBones, t, scratch) {
  const allBones = new Set([...Object.keys(prevBones), ...Object.keys(nextBones)]);
  for (const bName of allBones) {
    const bone = avatar.bones[bName] || avatar.bones['mixamorig:' + bName];
    if (!bone) continue;
    const qp = prevBones[bName];
    const qn = nextBones[bName] || qp;
    if (!qp) continue;
    // Scratch quaternion to avoid garbage
    const qa = scratch.get(bName + '_a') || (scratch.set(bName + '_a', new THREE.Quaternion()).get(bName + '_a'));
    const qb = scratch.get(bName + '_b') || (scratch.set(bName + '_b', new THREE.Quaternion()).get(bName + '_b'));
    qa.set(qp.x, qp.y, qp.z, qp.w);
    qb.set(qn.x, qn.y, qn.z, qn.w);
    bone.quaternion.copy(qa).slerp(qb, t);
  }
}

// ── 단일 keyframe 직접 적용 (마지막 프레임 고정) ────────────
function _applyKeyframe(avatar, bones, alpha = 1.0) {
  for (const [bName, q] of Object.entries(bones)) {
    const bone = avatar.bones[bName] || avatar.bones['mixamorig:' + bName];
    if (!bone) continue;
    const target = new THREE.Quaternion(q.x, q.y, q.z, q.w);
    if (alpha >= 1.0) bone.quaternion.copy(target);
    else bone.quaternion.slerp(target, alpha);
  }
}

// ── 초기 자세로 부드럽게 복귀 (V2 엔진과 동일 톤) ───────────
async function _returnToInitial(avatar, initialQuats) {
  const duration = 800;
  const startTime = performance.now();
  const currentQuats = new Map();
  for (const [bName, q] of initialQuats) {
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
