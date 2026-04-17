/**
 * retargeting.js [Cyborg Alpha v5.1 Debug Edition]
 */
import * as THREE from 'three';

console.info('%c[ITDA Retargeting] >>> retargeting.js STARTING', 'background: #FFD700; color: #000; font-weight: bold; padding: 2px 5px;');

const _QUAT = new THREE.Quaternion();
const _V1 = new THREE.Vector3();
const _armBoneCache = { Left: null, Right: null };

// 뼈 이름 후보 (확장된 하이브리드 리스트)
const CANDIDATES = {
  shoulder: ['Clavicle', 'Shoulder', 'Collar'],
  upperArm: ['UpperArm', 'Arm', 'Upper_Arm'],
  foreArm:  ['ForeArm', 'LowerArm', 'Arm_Twist', 'Forearm'],
  hand:     ['Hand', 'Wrist'],
};

function fuzzyFind(bones, side, candidates) {
  const names = Object.keys(bones);
  const sideAlt = side === 'Right' ? 'R' : 'L';
  const sideFull = side.toLowerCase();

  for (const c of candidates) {
    const variants = [
      `${side}${c}`, `mixamorig${side}${c}`, `${side}_${c}`, 
      `${sideAlt}_${c}`, `${c}_${sideAlt}`, `${c}.${sideAlt}`,
      `${sideFull}_${c}`, `${c}_${sideFull}`
    ];
    for (const v of variants) {
      const found = names.find(n => n.toLowerCase() === v.toLowerCase());
      if (found) return found;
    }
  }
  
  // 지능형 포함 검색 (Metahuman/Daz3D 대응)
  return names.find(n => {
    const lower = n.toLowerCase();
    return (lower.includes(sideFull) || lower.includes(`_${sideAlt.toLowerCase()}`)) 
           && candidates.some(c => lower.includes(c.toLowerCase()));
  });
}

function getBones(side, allBones) {
  if (_armBoneCache[side]) return _armBoneCache[side];
  
  const res = {
    shoulder: fuzzyFind(allBones, side, CANDIDATES.shoulder),
    upperArm: fuzzyFind(allBones, side, CANDIDATES.upperArm),
    foreArm:  fuzzyFind(allBones, side, CANDIDATES.foreArm),
    hand:     fuzzyFind(allBones, side, CANDIDATES.hand),
  };
  
  console.info(`[ITDA Retargeting] 🦴 ${side} Mapping:`, res);
  _armBoneCache[side] = res;
  return res;
}

// ── 핵심 리타겟팅 ─────────────────────────────────────────────
function applyPose(lms) {
  const avatar = window.ITDAAvatar5;
  if (!avatar || !lms) return;

  const POSE = { L_S: 11, R_S: 12, L_E: 13, R_E: 14, L_W: 15, R_W: 16 };

  ['Left', 'Right'].forEach(side => {
    try {
      const bNames = getBones(side, avatar.bones);
      if (!bNames.upperArm) return;

      // [Mirror Mode] 사용자의 Right -> 아바타의 Left, 사용자의 Left -> 아바타의 Right
      const dataSide = side === 'Left' ? 'Right' : 'Left';
      const s = dataSide === 'Left' ? POSE.L_S : POSE.R_S;
      const e = dataSide === 'Left' ? POSE.L_E : POSE.R_E;
      const w = dataSide === 'Left' ? POSE.L_W : POSE.R_W;

      if (!lms[s] || !lms[e]) return;

      // 벡터 변환 (MediaPipe -> THREE.Vector3)
      // [Mirror Mode] X축 반전, [Y-Invert] 상하 반전 해결, [Depth] 거리감 조정
      const pS = new THREE.Vector3(-lms[s].x, lms[s].y, -lms[s].z);
      const pE = new THREE.Vector3(-lms[e].x, lms[e].y, -lms[e].z);
      
      const dir = new THREE.Vector3().subVectors(pE, pS).normalize();
      const defaultDir = new THREE.Vector3(side === 'Left' ? 1 : -1, 0, 0);
      
      // [Cyborg Alpha] 상대 회전 계산: InitialPose * DeltaRotation
      const deltaQuat = new THREE.Quaternion().setFromUnitVectors(defaultDir, dir);
      const boneUpper = avatar.bones[bNames.upperArm];
      
      if (boneUpper && boneUpper.initialQuaternion) {
        _QUAT.copy(boneUpper.initialQuaternion).multiply(deltaQuat);
        avatar.updateBone(bNames.upperArm, _QUAT, 0.2);
      } else {
        avatar.updateBone(bNames.upperArm, deltaQuat, 0.2);
      }
      
      // 전완 (팔꿈치 -> 손목)
      if (lms[w] && bNames.foreArm) {
        const pW = new THREE.Vector3(-lms[w].x, lms[w].y, -lms[w].z);
        const fDir = new THREE.Vector3().subVectors(pW, pE).normalize();
        const fDeltaQuat = new THREE.Quaternion().setFromUnitVectors(defaultDir, fDir);
        const boneFore = avatar.bones[bNames.foreArm];

        if (boneFore && boneFore.initialQuaternion) {
          _QUAT.copy(boneFore.initialQuaternion).multiply(fDeltaQuat);
          avatar.updateBone(bNames.foreArm, _QUAT, 0.2);
        } else {
          avatar.updateBone(bNames.foreArm, fDeltaQuat, 0.2);
        }
      }
    } catch (err) {
      console.error('[ITDA Retargeting] Frame Error:', err);
    }
  });
}

// ── 이벤트 리스너 ─────────────────────────────────────────────
window.addEventListener('itda:pose:results', (e) => applyPose(e.detail.landmarks));

window.ITDARetargeting5 = {
  clearArmBoneCache() {
    _armBoneCache.Left = null;
    _armBoneCache.Right = null;
    console.log('[ITDA Retargeting] Cache Cleared.');
  }
};
