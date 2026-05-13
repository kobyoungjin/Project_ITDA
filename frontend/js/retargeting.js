/**
 * retargeting.js - [아바타 뷰 전신 안정화 및 머리 보정 버전]
 * 머리가 과도하게 꺾이는 현상을 방지하고 아바타의 자세를 직립 상태로 고정함
 */

import * as THREE from 'three';

const MP = {
  POSE: { 
    NOSE: 0,
    L_S: 11, R_S: 12, L_E: 13, R_E: 14, L_W: 15, R_W: 16, 
    L_H: 23, R_H: 24
  },
  HAND: { 
    L_B: 33, R_B: 54, 
    TIPS: [4, 8, 12, 16, 20], 
    NAMES: ['Thumb', 'Index', 'Middle', 'Ring', 'Pinky'] 
  }
};

const BONE_MAP = {
  // 눕거나 꺾이는 현상을 방지하기 위해 몸통 관련 관절 매핑을 최소화
  Hips:          ['Hips', 'Pelvis'], 
  RightUpperArm: ['mixamorig:RightArm', 'RightArm', 'RightUpperArm'],
  RightForeArm:  ['mixamorig:RightForeArm', 'RightForeArm', 'RightForearm'],
  RightHand:     ['mixamorig:RightHand', 'RightHand'],
  LeftUpperArm:  ['mixamorig:LeftArm', 'LeftArm', 'LeftUpperArm'],
  LeftForeArm:   ['mixamorig:LeftForeArm', 'LeftForeArm', 'LeftForearm'],
  LeftHand:      ['mixamorig:LeftHand', 'LeftHand'],
};

// ── 유틸리티 ────────────────────────────────────────────────
function findBone(bones, cands) {
  if (!cands) return null;
  // 1. 정확히 일치하는 이름 우선 검색
  for (const c of cands) if (bones[c]) return c;
  
  // 2. 대소문자 구분 없는 부분 일치
  const boneNames = Object.keys(bones);
  for (const c of cands) {
    const found = boneNames.find(n => n.toLowerCase() === c.toLowerCase());
    if (found) return found;
  }
  
  // 3. 포함 관계 확인 (Shoulder 오매칭 방지)
  for (const c of cands) {
    const found = boneNames.find(n => {
        const ln = n.toLowerCase();
        const lc = c.toLowerCase();
        if (lc.includes('arm') && ln.includes('shoulder')) return false;
        return ln.includes(lc);
    });
    if (found) return found;
  }
  return null;
}

function getRotation(p1, p2, baseVector) {
  if (!p1 || !p2) return new THREE.Quaternion();
  // MediaPipe(Y down) -> Three.js(Y up) 좌표계 변환
  const dir = new THREE.Vector3(
    (p2.x - p1.x), 
    -(p2.y - p1.y), 
    -(p2.z - p1.z)
  ).normalize();
  return new THREE.Quaternion().setFromUnitVectors(baseVector, dir);
}

// ── 메인 리타겟팅 로직 ───────────────────────────────────────
function apply75Landmarks(lms) {
  const avatar = window.ITDAAvatar5;
  if (!avatar || !avatar.bones || !lms || lms.length < 225) return;

  const pts = [];
  for (let i = 0; i < 75; i++) pts.push({ x: lms[i*3], y: lms[i*3+1], z: lms[i*3+2] });

  // joint_cache 데이터는 어깨 Y ≈ 0.87~1.06 (화면 하단)으로 기록되어
  // 위치 동기화 공식이 맞지 않아 아바타를 y≈-1.1로 밀어냄.
  // 아바타를 중앙에 고정하고 팔/손가락 리깅만 적용.
  const lS = pts[MP.POSE.L_S], rS = pts[MP.POSE.R_S];

  // 2. 상체 관절 리깅
  rigUpperBody(pts, avatar);

  // 3. 팔 리깅
  rigSide('Right', pts, avatar, 'Left');
  rigSide('Left', pts, avatar, 'Right');
}

function rigUpperBody(pts, avatar) {
  // 현재 모델 좌표계 이슈로 머리가 비정상적으로 꺾이므로 리깅을 비활성화하여 정면을 보게 함
  return;
}

function rigSide(side, pts, avatar, dataSide) {
  const bones = avatar.bones;
  const m = {
    u: findBone(bones, BONE_MAP[side + 'UpperArm']),
    f: findBone(bones, BONE_MAP[side + 'ForeArm']),
    h: findBone(bones, BONE_MAP[side + 'Hand'])
  };

  const isR = (dataSide === 'Right');
  const s = pts[isR ? MP.POSE.R_S : MP.POSE.L_S];
  const e = pts[isR ? MP.POSE.R_E : MP.POSE.L_E];
  const w = pts[isR ? MP.POSE.R_W : MP.POSE.L_W];

  const baseArm = (side === 'Right') ? new THREE.Vector3(1, 0, 0) : new THREE.Vector3(-1, 0, 0);
  const isZero = p => !p || (p.x === 0 && p.y === 0 && p.z === 0);

  // 팔 리깅 - 포즈 랜드마크가 0이면 건너뜀 (NaN 쿼터니언 방지)
  if (s && e && m.u && !isZero(s) && !isZero(e)) {
    avatar.updateBone(m.u, getRotation(s, e, baseArm), 0.3);
  }
  if (e && w && m.f && !isZero(e) && !isZero(w)) {
    avatar.updateBone(m.f, getRotation(e, w, baseArm), 0.3);
  }
  if (m.h && e && w && !isZero(e) && !isZero(w)) {
    avatar.updateBone(m.h, getRotation(e, w, baseArm), 0.1);
  }

  // 손가락 리깅
  const bIdx = isR ? MP.HAND.R_B : MP.HAND.L_B;
  const basePoint = pts[bIdx];
  // 좌표계 판별: z 절댓값이 0.15 초과면 월드좌표(단위:미터) → 임계값 스케일 조정
  const isWorldCoord = basePoint && Math.abs(basePoint.z) > 0.15;
  const curlThreshold = isWorldCoord ? 0.08 : 0.12;
  const curlScale     = isWorldCoord ? 20   : 15;
  if (basePoint && !isZero(basePoint)) {
    MP.HAND.TIPS.forEach((off, i) => {
      const tip = pts[bIdx + off];
      if (tip) {
        const d = Math.sqrt(Math.pow(tip.x-basePoint.x,2)+Math.pow(tip.y-basePoint.y,2)+Math.pow(tip.z-basePoint.z,2));
        const curl = Math.max(0, Math.min(1.2, (curlThreshold - d) * curlScale));
        for (let j = 1; j <= 3; j++) {
          const bn = findBone(bones, [`${side}${MP.HAND.NAMES[i]}${j}`, `mixamorig:${side}Hand${MP.HAND.NAMES[i]}${j}`]);
          if (bn) avatar.updateBone(bn, { x: curl, y: 0, z: 0 }, 0.2);
        }
      }
    });
  }
}

window.ITDARetargeting5 = { apply75Landmarks };
window.apply75Landmarks = apply75Landmarks;
console.info('[ITDA Rigging] ✅ 전신 자세 및 머리 고정 모드 활성화');
