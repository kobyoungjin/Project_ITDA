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

let _library = null;
let _loading = null;

async function load() {
  if (_library) return _library;
  if (_loading) return _loading;
  _loading = (async () => {
    const res = await fetch(LIBRARY_URL, { cache: 'no-cache' });
    if (!res.ok) throw new Error(`handshape library HTTP ${res.status}`);
    _library = await res.json();
    const n = Object.keys(_library.shapes || {}).length;
    console.info(`[Handshape] 라이브러리 로드 완료: ${n}개 수형`);
    return _library;
  })();
  return _loading;
}

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

/** 양손 수형 적용. avatar 는 bones dict 를 가지고 있어야 함. */
function apply(avatar, name) {
  if (!avatar?.bones) { console.warn('[Handshape] avatar.bones 없음'); return false; }
  const shape = _library?.shapes?.[name];
  if (!shape) { console.warn(`[Handshape] 미발견: ${name}`); return false; }
  const rest = _ensureRest(avatar);

  for (const [bn, q] of Object.entries(shape)) {
    const bone = avatar.bones[bn] || avatar.bones['mixamorig:' + bn];
    const restQ = rest[bn];
    if (!bone || !restQ) continue;
    _tmpQ.set(q.x, q.y, q.z, q.w);
    bone.quaternion.copy(restQ).multiply(_tmpQ);
  }
  return true;
}

/** 한 손만 수형 적용. */
function applyOne(avatar, name, side) {
  if (!avatar?.bones) return false;
  const shape = _library?.shapes?.[name];
  if (!shape) return false;
  const rest = _ensureRest(avatar);
  const prefix = side + 'Hand';

  for (const [bn, q] of Object.entries(shape)) {
    if (!bn.startsWith(prefix)) continue;
    const bone = avatar.bones[bn] || avatar.bones['mixamorig:' + bn];
    const restQ = rest[bn];
    if (!bone || !restQ) continue;
    _tmpQ.set(q.x, q.y, q.z, q.w);
    bone.quaternion.copy(restQ).multiply(_tmpQ);
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
};

// 자동 로드
load().catch(err => console.warn('[Handshape] 초기 로드 실패:', err));
