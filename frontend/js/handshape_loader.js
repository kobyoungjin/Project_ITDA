/**
 * handshape_loader.js  ─  2단계: 수형 라이브러리 로더
 *
 * [역할]
 *   - handshape_library.json 을 한 번 로드하고 캐시
 *   - 수형 이름으로 아바타 손 본에 quaternion 적용 (rest × offset 합성)
 *   - motion_loader_v3 / 콘솔 디버그 / preview 에서 공통 사용
 *
 * [공개 API — window.ITDAHandshape]
 *   await ITDAHandshape.load()                : 라이브러리 초기 로드 (자동 호출됨)
 *   ITDAHandshape.apply(avatar, name)         : 양손에 수형 즉시 적용
 *   ITDAHandshape.applyOne(avatar, name, side): 한 손만 적용 ('Right'|'Left')
 *   ITDAHandshape.has(name)                   : 해당 수형 존재 여부
 *   ITDAHandshape.list()                      : 수형 이름 배열
 *   ITDAHandshape.getQuats(name, side)        : raw quaternion 맵 반환 (motion_loader 용)
 *
 * [수형 적용 공식]
 *   bone.quaternion = rest_quaternion * offset_quaternion
 *   → rest 는 rig 해부학 각도 유지, offset 만 추가 회전
 */

import * as THREE from 'three';

const LIBRARY_URL = './data/handshape_library.json';
const LS_PREFIX = 'itda.handshape.override.';

let _library = null;
let _loading = null;
let _overrides = {};   // name → { bone: {x,y,z,w} } ABSOLUTE quaternions (from preview save)

function _loadOverrides() {
  const map = {};
  let count = 0;
  try {
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (k && k.startsWith(LS_PREFIX)) {
        const name = k.slice(LS_PREFIX.length);
        try { map[name] = JSON.parse(localStorage.getItem(k)); count++; } catch {}
      }
    }
  } catch (e) { console.warn('[Handshape] localStorage 읽기 실패:', e); }
  if (count > 0) console.info(`[Handshape] localStorage 오버라이드 ${count}개 병합 (허브 반영)`);
  return map;
}

async function load() {
  if (_library) return _library;
  if (_loading) return _loading;
  _loading = (async () => {
    const res = await fetch(LIBRARY_URL, { cache: 'no-cache' });
    if (!res.ok) throw new Error(`handshape library HTTP ${res.status}`);
    _library = await res.json();
    _overrides = _loadOverrides();
    const n = Object.keys(_library.shapes || {}).length;
    console.info(`[Handshape] 라이브러리 로드 완료: ${n}개 수형 (+ 오버라이드 ${Object.keys(_overrides).length})`);
    return _library;
  })();
  return _loading;
}

/** 해당 수형에 localStorage 절대값 오버라이드가 있으면 true. */
function hasOverride(name) { return !!_overrides[name]; }
function getOverride(name) { return _overrides[name] || null; }

function has(name) {
  return !!(_library?.shapes?.[name]);
}

function list() {
  return Object.keys(_library?.shapes || {});
}

/** 특정 수형·특정 손의 quaternion offset map 반환 (bone → {x,y,z,w}). */
function getQuats(name, side = null) {
  const shape = _library?.shapes?.[name];
  if (!shape) return null;
  if (!side) return shape;
  const filtered = {};
  const prefix = side + 'Hand';
  for (const [bn, q] of Object.entries(shape)) {
    if (bn.startsWith(prefix)) filtered[bn] = q;
  }
  return filtered;
}

/** avatar.bones 의 손가락 본 rest quaternion 캐시.
 *  필요 시 apply 호출 전에 avatar 객체에 초기 quat 을 저장해 두면 재사용. */
function _ensureRest(avatar) {
  if (avatar._handshapeRest) return avatar._handshapeRest;
  const rest = {};
  for (const name of Object.keys(avatar.bones || {})) {
    if (/Hand(Thumb|Index|Middle|Ring|Pinky)\d/.test(name)) {
      rest[name] = avatar.bones[name].quaternion.clone();
    }
  }
  avatar._handshapeRest = rest;
  return rest;
}

const _tmpQ = new THREE.Quaternion();

/** 양손 수형 적용.
 *  localStorage 오버라이드 있으면 절대값 직접 적용 (rest 불필요).
 *  없으면 파일 라이브러리 값을 rest × offset 으로 합성. */
function apply(avatar, name) {
  if (!avatar?.bones) { console.warn('[Handshape] avatar.bones 없음'); return false; }
  const override = _overrides[name];
  const shape = override || _library?.shapes?.[name];
  if (!shape) { console.warn(`[Handshape] 미발견: ${name}`); return false; }
  const rest = _ensureRest(avatar);
  const useAbsolute = !!override;   // 오버라이드는 최종 local quat 이므로 rest 곱셈 불필요

  for (const [bn, q] of Object.entries(shape)) {
    const bone = avatar.bones[bn] || avatar.bones['mixamorig:' + bn];
    if (!bone) continue;
    _tmpQ.set(q.x, q.y, q.z, q.w);
    if (useAbsolute) {
      bone.quaternion.copy(_tmpQ);
    } else {
      const restQ = rest[bn];
      if (!restQ) continue;
      bone.quaternion.copy(restQ).multiply(_tmpQ);
    }
  }
  return true;
}

/** 한 손만 수형 적용. */
function applyOne(avatar, name, side) {
  if (!avatar?.bones) return false;
  const override = _overrides[name];
  const shape = override || _library?.shapes?.[name];
  if (!shape) return false;
  const rest = _ensureRest(avatar);
  const prefix = side + 'Hand';
  const useAbsolute = !!override;

  for (const [bn, q] of Object.entries(shape)) {
    if (!bn.startsWith(prefix)) continue;
    const bone = avatar.bones[bn] || avatar.bones['mixamorig:' + bn];
    if (!bone) continue;
    _tmpQ.set(q.x, q.y, q.z, q.w);
    if (useAbsolute) {
      bone.quaternion.copy(_tmpQ);
    } else {
      const restQ = rest[bn];
      if (!restQ) continue;
      bone.quaternion.copy(restQ).multiply(_tmpQ);
    }
  }
  return true;
}

/** 손을 rest 자세로 되돌림 (양손). */
function resetHands(avatar) {
  const rest = avatar?._handshapeRest;
  if (!rest) return;
  for (const [bn, q0] of Object.entries(rest)) {
    const bone = avatar.bones[bn];
    if (bone) bone.quaternion.copy(q0);
  }
}

window.ITDAHandshape = {
  load,
  apply,
  applyOne,
  resetHands,
  has,
  list,
  getQuats,
  hasOverride,
  getOverride,
  reloadOverrides: () => { _overrides = _loadOverrides(); },
};

// 자동 로드
load().catch(err => console.warn('[Handshape] 초기 로드 실패:', err));
