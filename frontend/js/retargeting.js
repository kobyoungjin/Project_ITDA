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

  // 1. 위치 동기화 (어깨 중앙 기준)
  const lS = pts[MP.POSE.L_S], rS = pts[MP.POSE.R_S];
  if (lS && rS && avatar.model) {
    const cX = (lS.x + rS.x) / 2;
    const cY = (lS.y + rS.y) / 2;
    
    const targetX = -(cX - 0.5) * 1.8;
    const targetY = (0.5 - cY) * 1.8 + 1.25; 
    
    // 모델의 전체 위치만 이동시키고 회전은 건드리지 않음
    avatar.model.position.lerp(new THREE.Vector3(targetX, targetY - 1.45, 0), 0.2);
  }

  // 2. 상체 관절 리깅 (머리 회전 포함)
  // 머리가 과도하게 꺾이는 문제를 방지하기 위해 회전 영향도를 대폭 낮추거나 비활성화
  rigUpperBody(pts, avatar);

  // 3. 팔 리깅
  rigSide('Right', pts, avatar, 'Left');
  rigSide('Left', pts, avatar, 'Right');

  avatar.updateSkeleton?.(lms);
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

  // 팔 리깅 (Lerp 값을 조절하여 부드럽게 추종)
  if (s && e && m.u) {
    avatar.updateBone(m.u, getRotation(s, e, baseArm), 0.3);
  }
  if (e && w && m.f) {
    avatar.updateBone(m.f, getRotation(e, w, baseArm), 0.3);
  }
  if (m.h && e && w) {
    // 손목은 팔의 방향을 따라가되 부드럽게
    avatar.updateBone(m.h, getRotation(e, w, baseArm), 0.1);
  }

  // 손가락 리깅
  const bIdx = isR ? MP.HAND.R_B : MP.HAND.L_B;
  const basePoint = pts[bIdx];
  if (basePoint) {
    MP.HAND.TIPS.forEach((off, i) => {
      const tip = pts[bIdx + off];
      if (tip) {
        const d = Math.sqrt(Math.pow(tip.x-basePoint.x,2)+Math.pow(tip.y-basePoint.y,2)+Math.pow(tip.z-basePoint.z,2));
        const curl = Math.max(0, Math.min(1.2, (0.12 - d) * 15)); 
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
