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
        // 마지막 keyframe 값으로 마무리 (motion.space 에 맞춰 world→local 처리)
        const lastBones = keyframes[keyframes.length - 1].bones;
        _applyInterpolated(avatar, lastBones, lastBones, 1.0, targetQuats, motion);
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

      _applyInterpolated(avatar, prev.bones, next.bones, t, targetQuats, motion);

      requestAnimationFrame(update);
    }
    requestAnimationFrame(update);
  });
}

// ── 두 keyframe 사이 보간 (Quaternion slerp) ────────────────
// V3.1: JSON 의 quaternion 이 WORLD space 이면, 각 본에 대해 WORLD 를 먼저 보간한 뒤
//       parent_chain 을 따라 local = inverse(parent_world) * this_world 로 변환.
//       WORLD space slerp 가 수학적으로 정확하기 때문에 관절 chain 이 꼬이지 않음.
function _applyInterpolated(avatar, prevBones, nextBones, t, scratch, motion) {
  const isWorld = motion?.space === 'world';
  const parentChain = motion?.parent_chain || {};
  const allBones = new Set([...Object.keys(prevBones), ...Object.keys(nextBones)]);

  // 1. 각 본의 현재 world quaternion 을 먼저 계산 (parent 순서 무관)
  const worldQuats = new Map();
  for (const bName of allBones) {
    const qp = prevBones[bName];
    const qn = nextBones[bName] || qp;
    if (!qp) continue;
    const qa = scratch.get(bName + '_a') || (scratch.set(bName + '_a', new THREE.Quaternion()).get(bName + '_a'));
    const qb = scratch.get(bName + '_b') || (scratch.set(bName + '_b', new THREE.Quaternion()).get(bName + '_b'));
    qa.set(qp.x, qp.y, qp.z, qp.w);
    qb.set(qn.x, qn.y, qn.z, qn.w);
    const qout = new THREE.Quaternion().copy(qa).slerp(qb, t);
    worldQuats.set(bName, qout);
  }

  // 2. Parent 순서로 local 계산하여 bone 에 적용 (부모부터 자식 순)
  //    간단한 2단계 체인(Arm → ForeArm) 이므로 parent 가 있는 본을 나중에 처리
  const orderedNames = [...worldQuats.keys()].sort((a, b) => {
    const aHasParent = parentChain[a] ? 1 : 0;
    const bHasParent = parentChain[b] ? 1 : 0;
    return aHasParent - bHasParent;
  });

  for (const bName of orderedNames) {
    const bone = avatar.bones[bName] || avatar.bones['mixamorig:' + bName];
    if (!bone) continue;
    const wq = worldQuats.get(bName);
    if (!isWorld) {
      // Legacy: JSON 이 local space. 직접 적용.
      bone.quaternion.copy(wq);
      continue;
    }
    const parentName = parentChain[bName];
    if (!parentName) {
      // Root bone: local = world (부모가 identity 가정)
      bone.quaternion.copy(wq);
    } else {
      const parentWorld = worldQuats.get(parentName);
      if (!parentWorld) {
        bone.quaternion.copy(wq);
        continue;
      }
      // local = inverse(parent_world) * this_world
      const invParent = new THREE.Quaternion().copy(parentWorld).invert();
      bone.quaternion.copy(invParent).multiply(wq);
    }
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
