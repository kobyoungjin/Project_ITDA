/**
 * retargeting.js  ─  Step 5 [Cyborg Alpha High-Fidelity Edition]
 * 
 * ■ 역할
 *   1. 52개 ARKit Blendshapes -> 아바타 Morph Targets 정밀 매핑
 *   2. 21개 손가락 관절(MCP, PIP, DIP) 정밀 리타겟팅
 *   3. 손목-팔꿈치-어깨를 잇는 팔(Arm) 궤적 보정 (IK 기반)
 */

// ── [Cyborg Alpha] 고해상도 손 관절 매핑 (21 포인트 전체) ──
const FINGER_NAMES = ['Thumb', 'Index', 'Middle', 'Ring', 'Pinky'];
const FINGER_STAGES = ['1', '2', '3']; // MCP, PIP, DIP

const HAND_BONE_MAP = { Right: {}, Left: {} };

['Right', 'Left'].forEach(side => {
  const prefix = side === 'Right' ? 'RightHand' : 'LeftHand'; // RPM/Mixamo 표준
  
  // 손목
  HAND_BONE_MAP[side]['wrist'] = { boneName: prefix, idx: 0 };
  
  // 손가락 마디마디 매핑 (RPM: RightHandIndex1, RightHandIndex2...)
  FINGER_NAMES.forEach(finger => {
    FINGER_STAGES.forEach((stage, sIdx) => {
      const boneName = `${prefix}${finger}${stage}`;
      const landmarkIdx = getLandmarkIndex(finger, sIdx);
      HAND_BONE_MAP[side][`${finger}${stage}`] = { boneName, idx: landmarkIdx };
    });
  });
});

function getLandmarkIndex(finger, stage) {
  const base = { 'Thumb': 1, 'Index': 5, 'Middle': 9, 'Ring': 13, 'Pinky': 17 };
  return base[finger] + stage;
}

// ── [Cyborg Alpha] 52종 ARKit Blendshape 매핑 엔진 ──
// 모델이 지원하는 모든 Morph Target을 실시간으로 싱크합니다.
function applyFaceBlendshapes(blendshapes) {
  const avatar = window.ITDAAvatar5;
  if (!avatar) return;

  blendshapes.forEach(({ categoryName, score }) => {
    // 1. ARKit 표준 이름을 아바타 Morph Target에 직접 투영
    avatar.setMorphTarget(categoryName, score);
    
    // 2. [Cyborg Alpha] 감정 파생 (Angry, Surprised, Sad 등 기존 Morph와 혼합)
    // 이 부분은 기존 감정 게이지 시스템과 상호작용합니다.
  });
}

// ── [Cyborg Alpha] SAM Fingers Engine (21포인트 정밀 IK) ──
function applyHandLandmarks(hands) {
  const avatar = window.ITDAAvatar5;
  if (!avatar || !avatar.bones) return;

  // 1. 손이 감지되지 않으면 중립 포즈로 서서히 복귀
  if (!hands || hands.length === 0) {
    neutralizeHands(avatar);
    return;
  }

  hands.forEach(hand => {
    // [Mirror Mode] 사용자의 'Right' -> 아바타의 'Left', 'Left' -> 'Right'로 스왑
    const avatarSide = hand.handedness === 'Right' ? 'Left' : 'Right';
    const sideMap = HAND_BONE_MAP[avatarSide];
    if (!sideMap) return;

    const lms = hand.landmarks;
    const wrist = lms[0];

    // 2. 손가락 마디별 정밀 굴곡(Flexion) 및 벌림(Abduction) 적용
    FINGER_NAMES.forEach(finger => {
      // 마디별 인덱스 추출
      const mcpIdx = getLandmarkIndex(finger, 0);
      const pipIdx = mcpIdx + 1;
      const dipIdx = mcpIdx + 2;
      const tipIdx = mcpIdx + 3;

      // [Flexion] 마디 간 굽힘 각도 계산
      const mcpFlex = bendAngle(wrist, lms[mcpIdx], lms[pipIdx]);
      const pipFlex = bendAngle(lms[mcpIdx], lms[pipIdx], lms[dipIdx]);
      const dipFlex = bendAngle(lms[pipIdx], lms[dipIdx], lms[tipIdx]);

      // [Abduction] 손가락 벌림 (중지 기준)
      const middleMcp = lms[9];
      const abduction = finger === 'Middle' ? 0 : (lms[mcpIdx].x - middleMcp.x) * 2.0;

      // 마디별 뼈 업데이트 매핑
      const stages = [
        { key: '1', angle: mcpFlex, abd: abduction },
        { key: '2', angle: pipFlex, abd: 0 },
        { key: '3', angle: dipFlex, abd: 0 }
      ];

      stages.forEach(stage => {
        const boneData = sideMap[`${finger}${stage.key}`];
        if (!boneData) return;

        if (finger === 'Thumb') {
          // 엄지손가락 전용 IK: 3축 회전 (Opposition 강조)
          avatar.updateBone(boneData.boneName, {
            x: stage.angle * 0.9,
            y: (stage.key === '1' ? -0.3 : 0), 
            z: (stage.key === '1' ? (avatarSide === 'Left' ? 0.3 : -0.3) : 0)
          }, 0.2);
        } else {
          // 일반 손가락: X(굴곡), Z(벌림)
          avatar.updateBone(boneData.boneName, {
            x: stage.angle * 1.1,
            y: 0,
            z: stage.abd * (avatarSide === 'Left' ? 1 : -1)
          }, 0.25);
        }
      });
    });
  });
}

/**
 * 손이 사라졌을 때 모든 손가락 관절 초기화
 */
function neutralizeHands(avatar) {
  const resetAlpha = 0.05;
  ['Right', 'Left'].forEach(side => {
    FINGER_NAMES.forEach(finger => {
      FINGER_STAGES.forEach(stage => {
        const boneName = HAND_BONE_MAP[side][`${finger}${stage}`]?.boneName;
        if (boneName) avatar.updateBone(boneName, { x: 0, y: 0, z: 0 }, resetAlpha);
      });
    });
  });
}

// ══════════════════════════════════════════════════════════════
// ── [Cyborg Alpha v4] 실제 포즈 기반 팔 IK 엔진 ──────────────
// MediaPipe PoseLandmarker 33개 관절에서 어깨·팔꿈치·손목 직접 추출
// ══════════════════════════════════════════════════════════════

// MediaPipe Pose 랜드마크 인덱스
const POSE = {
  LEFT_SHOULDER: 11,  RIGHT_SHOULDER: 12,
  LEFT_ELBOW: 13,     RIGHT_ELBOW: 14,
  LEFT_WRIST: 15,     RIGHT_WRIST: 16,
  LEFT_HIP: 23,       RIGHT_HIP: 24,
};

// 뼈 이름 후보 (모델마다 다를 수 있으므로 자동 탐색)
const ARM_BONE_CANDIDATES = {
  shoulder: ['Shoulder', 'shoulder'],
  upperArm: ['Arm', 'UpperArm', 'upperArm', 'Upper_Arm'],
  foreArm:  ['ForeArm', 'foreArm', 'LowerArm', 'lowerArm', 'Lower_Arm', 'Forearm'],
  hand:     ['Hand', 'hand', 'Wrist', 'wrist'],
};

function findBone(bones, side, candidates) {
  for (const c of candidates) {
    const rpm = `${side}${c}`;
    if (bones[rpm]) return rpm;
    const mixamo = `mixamorig${side}${c}`;
    if (bones[mixamo]) return mixamo;
    const under = `${side}_${c}`;
    if (bones[under]) return under;
    const lower = `${side.toLowerCase()}${c}`;
    if (bones[lower]) return lower;
  }
  return null;
}

const _armBoneCache = {};

function getArmBones(side, bones) {
  if (_armBoneCache[side]) return _armBoneCache[side];
  const result = {
    shoulder: findBone(bones, side, ARM_BONE_CANDIDATES.shoulder),
    upperArm: findBone(bones, side, ARM_BONE_CANDIDATES.upperArm),
    foreArm:  findBone(bones, side, ARM_BONE_CANDIDATES.foreArm),
    hand:     findBone(bones, side, ARM_BONE_CANDIDATES.hand),
  };
  console.info(`[ITDA Retargeting] ${side} Arm Bones:`, result);
  _armBoneCache[side] = result;
  return result;
}

/**
 * 두 점 사이의 각도를 계산 (부모→자식 방향)
 * [Cyborg Alpha] 안정성 강화: Z값 노이즈 억제 필터 적용
 */
const _zBuffer = {}; 
function angleBetween(parent, child) {
  // [Cyborg Alpha] 좌우 및 앞뒤 반전 적용 (거울 모드 및 정면 인식 대응)
  // dx 반전: 사용자의 오른쪽이 아바타의 오른쪽으로 매핑 (거울 효과)
  // dz 반전: 사용자가 카메라 쪽으로 뻗을 때 아바타도 앞으로 뻗도록 수정
  const dx = -(child.x - parent.x);
  const dy = child.y - parent.y;
  
  // Z축 노이즈 억제 및 방향 반전
  const rawDz = -(child.z - parent.z);
  const key = `${parent.x},${parent.y}`;
  const prevDz = _zBuffer[key] ?? rawDz;
  const dz = prevDz + (rawDz - prevDz) * 0.1;
  _zBuffer[key] = dz;

  return {
    // Y축 회전 (좌우 방향)
    y: Math.atan2(dx, dz || 0.001),
    // Z축 회전 (상하 방향)
    z: Math.atan2(-dy, Math.sqrt(dx*dx + dz*dz) || 0.001),
    // X축 회전 (뒤틀림)
    x: Math.atan2(dz, Math.sqrt(dx*dx + dy*dy) || 0.001),
  };
}

/**
 * 세 점(A→B→C)의 굽힘 각도 계산 (팔꿈치 등)
 */
function bendAngle(a, b, c) {
  const ab = { x: b.x - a.x, y: b.y - a.y, z: b.z - a.z };
  const bc = { x: c.x - b.x, y: c.y - b.y, z: c.z - b.z };
  const dot = ab.x*bc.x + ab.y*bc.y + ab.z*bc.z;
  const magAB = Math.sqrt(ab.x**2 + ab.y**2 + ab.z**2) || 0.001;
  const magBC = Math.sqrt(bc.x**2 + bc.y**2 + bc.z**2) || 0.001;
  const cosAngle = Math.max(-1, Math.min(1, dot / (magAB * magBC)));
  return Math.acos(cosAngle); // 0(완전히 펴짐) ~ PI(완전히 접힘)
}

// 기준 포즈(T-pose) 저장용 — 첫 프레임에서 캡처
let restPose = null;

// [Cyborg Alpha] 데이터 평활화 및 상태 관리를 위한 버퍼
const smoothingBuffer = {
  landmarks: {}, // 인덱스별 평활화된 좌표
  lastActiveTime: 0,
  isNeutralizing: false,
  calibration: { dist: 0.2, scale: 1.0 } // [Cyborg Alpha] 자동 보정용
};

const SMOOTHING_FACTOR = 0.1; // [추가 하향] 극강의 안정성을 위해 0.1 적용
const POSE_VISIBILITY_THRESHOLD = 0.2;

/**
 * 지수 이동 평균(EMA)을 이용한 랜드마크 스무딩
 */
function smoothLandmark(idx, current, customFactor) {
  const factor = customFactor !== undefined ? customFactor : SMOOTHING_FACTOR;
  if (!smoothingBuffer.landmarks[idx]) {
    smoothingBuffer.landmarks[idx] = { ...current };
    return current;
  }
  const prev = smoothingBuffer.landmarks[idx];
  prev.x = prev.x + (current.x - prev.x) * factor;
  prev.y = prev.y + (current.y - prev.y) * factor;
  prev.z = prev.z + (current.z - prev.z) * factor;
  return prev;
}

/**
 * 실제 포즈 데이터 기반 팔 리타겟팅
 * PoseLandmarker의 33개 관절 중 어깨·팔꿈치·손목을 직접 사용
 */
function applyPoseLandmarks(poseLandmarks) {
  const avatar = window.ITDAAvatar5;
  if (!avatar || !avatar.bones) return;

  // 1. 사람이 없거나 가시성이 낮아 null이 들어온 경우 -> 중립 포즈로 복귀
  if (!poseLandmarks) {
    neutralizeAvatar(avatar);
    return;
  }

  // 2. 가시성 및 유효성 검사 (핵심 관절 가시성 확인)
  const coreIndices = [POSE.LEFT_SHOULDER, POSE.RIGHT_SHOULDER, POSE.LEFT_ELBOW, POSE.RIGHT_ELBOW];
  const isVisible = coreIndices.every(idx => poseLandmarks[idx]?.visibility > POSE_VISIBILITY_THRESHOLD);

  if (!isVisible) {
    neutralizeAvatar(avatar);
    return;
  }

  // 3. 기준 포즈 및 자동 캘리브레이션 (가시성이 확보된 상태에서 최초 1회)
  if (!restPose) {
    restPose = {
      leftShoulder: { ...poseLandmarks[POSE.LEFT_SHOULDER] },
      rightShoulder: { ...poseLandmarks[POSE.RIGHT_SHOULDER] },
    };
    // 사용자의 어깨너비를 측정하여 팔 동작의 스케일 보정
    const dx = poseLandmarks[POSE.RIGHT_SHOULDER].x - poseLandmarks[POSE.LEFT_SHOULDER].x;
    const dy = poseLandmarks[POSE.RIGHT_SHOULDER].y - poseLandmarks[POSE.LEFT_SHOULDER].y;
    smoothingBuffer.calibration.dist = Math.sqrt(dx*dx + dy*dy) || 0.2;
    smoothingBuffer.calibration.scale = 0.2 / smoothingBuffer.calibration.dist;
    console.info('[ITDA Retargeting] ✅ 캘리브레이션 완료. Scale:', smoothingBuffer.calibration.scale);
  }

  // 4. 데이터 복귀 모드 해제
  smoothingBuffer.isNeutralizing = false;
  smoothingBuffer.lastActiveTime = performance.now();

  // 5. 스무딩 처리된 랜드마크 생성
  const smoothedLms = poseLandmarks.map((lm, idx) => {
    // [Cyborg Alpha] 인식이 불안정할 때(low visibility) 스무딩 계수를 낮춤(0.05)하여 튀는 동작 억제
    const factor = (lm.visibility || 0) < 0.5 ? 0.05 : SMOOTHING_FACTOR;
    return smoothLandmark(idx, lm, factor);
  });

  // 6. 양쪽 팔 처리 (Mirror Mode: 데이터의 'Left' -> 아바타의 'Right')
  applySingleArm('Right', smoothedLms, avatar, 'Left');
  applySingleArm('Left', smoothedLms, avatar, 'Right');
}

/**
 * 미인식 시 아바타를 천천히 중립 자세로 복귀시킴
 */
function neutralizeAvatar(avatar) {
  // 마지막 인식 후 3초가 지나면 업데이트 중단 (성능 절약)
  if (performance.now() - smoothingBuffer.lastActiveTime > 3000) return;
  
  smoothingBuffer.isNeutralizing = true;
  const resetAlpha = 0.04; // 복귀 속도 (매우 부드럽게)

  ['Left', 'Right'].forEach(side => {
    const bones = getArmBones(side, avatar.bones);
    if (!bones) return;

    if (bones.shoulder) avatar.updateBone(bones.shoulder, { x: 0, y: 0, z: 0 }, resetAlpha);
    if (bones.upperArm) avatar.updateBone(bones.upperArm, { x: 0, y: 0, z: 0 }, resetAlpha);
    if (bones.foreArm)  avatar.updateBone(bones.foreArm,  { x: 0, y: 0, z: 0 }, resetAlpha);
    if (bones.hand)     avatar.updateBone(bones.hand,     { x: 0, y: 0, z: 0 }, resetAlpha);
  });
}

/**
 * 실제 포즈 데이터 기반 팔 리타겟팅 (Mirror 지원)
 * dataSide: landmarks에서 가져올 쪽 (Left/Right)
 * boneSide: 아바타 뼈에서 가져올 쪽 (Right/Left)
 */
function applySingleArm(boneSide, lms, avatar, dataSide) {
  const armBones = getArmBones(boneSide, avatar.bones);
  
  // 포즈 인덱스 선택 (dataSide 기준)
  const shoulderIdx = dataSide === 'Left' ? POSE.LEFT_SHOULDER : POSE.RIGHT_SHOULDER;
  const elbowIdx    = dataSide === 'Left' ? POSE.LEFT_ELBOW    : POSE.RIGHT_ELBOW;
  const wristIdx    = dataSide === 'Left' ? POSE.LEFT_WRIST    : POSE.RIGHT_WRIST;
  const hipIdx      = dataSide === 'Left' ? POSE.LEFT_HIP      : POSE.RIGHT_HIP;

  const shoulder = lms[shoulderIdx];
  const elbow    = lms[elbowIdx];
  let wrist      = { ...lms[wristIdx] }; // 복사본 생성 (좌표 수정용)
  const hip      = lms[hipIdx];
  const nose     = lms[0]; // 얼굴 위치 기준점 (Nose)

  if (!shoulder || !elbow || !wrist) return;

  // ── [Cyborg Alpha] 수어 공간 최적화 : 얼굴 및 상체 뚫림 방지 (Collision Avoidance) ──
  if (nose) {
    const distToFace = Math.sqrt((wrist.x - nose.x)**2 + (wrist.y - nose.y)**2 + (wrist.z - nose.z)**2);
    const safeZone = 0.12; // 수어 시 손이 얼굴에 너무 가까워지지 않도록 하는 버퍼
    if (distToFace < safeZone) {
      // 얼굴 방향으로 너무 깊이 들어오면 Z축을 밖으로 밀어냄
      wrist.z = nose.z - safeZone * 0.8; 
    }
  }

  // ── 1) 어깨 회전: 몸통(엉덩이→어깨) 대비 팔(어깨→팔꿈치) 방향 ──
  const shoulderAngle = angleBetween(shoulder, elbow);
  // 몸통 기준선 (엉덩가 보이지 않으면 0으로 고정하여 떨림 방지)
  const isHipVisible = hip && (hip.visibility || 0) > 0.5;
  const torsoAngle = isHipVisible ? angleBetween(hip, shoulder) : { y: 0, z: 0, x: 0 };
  
  if (armBones.shoulder) {
    avatar.updateBone(armBones.shoulder, {
      x: 0,
      y: (shoulderAngle.y - torsoAngle.y) * 0.4,
      z: (shoulderAngle.z - torsoAngle.z) * 0.3,
    }, 0.15);
  }

  // ── 2) 상완 회전: 어깨→팔꿈치 방향 (주된 팔 방향) ──
  if (armBones.upperArm) {
    // 상완 벡터에서 직접 각도 추출
    const upperArmAngle = angleBetween(shoulder, elbow);
    avatar.updateBone(armBones.upperArm, {
      x: upperArmAngle.x * 0.8,
      y: upperArmAngle.y * 0.8,
      z: upperArmAngle.z * 0.9,
    }, 0.2);
  }

  // ── 3) 전완 회전: 팔꿈치 굽힘 (어깨-팔꿈치-손목 세 점의 각도) ──
  if (armBones.foreArm) {
    const bend = bendAngle(shoulder, elbow, wrist);
    // bend: 0=완전 펴짐, PI=완전 접힘
    const elbowFlex = bend; // [버그수정] 펴졌을 때 0이 되도록

    // 전완 방향 (팔꿈치→손목)
    const foreAngle = angleBetween(elbow, wrist);
    
    avatar.updateBone(armBones.foreArm, {
      x: elbowFlex * 1.2,        // 팔꿈치 굽힘 강도 상향
      y: foreAngle.y * 0.5,      // 전완 비틀림
      z: 0,
    }, 0.25);
  }
  
  // ── 4) 손목 회전: 팔꿈치→손목 방향에서 추출 ──
  if (armBones.hand) {
    const handAngle = angleBetween(elbow, wrist);
    avatar.updateBone(armBones.hand, {
      x: handAngle.x * 0.7,
      y: handAngle.y * 0.6,
      z: 0,
    }, 0.25);
  }
}

// ── 이벤트 및 인터페이스 ──
window.addEventListener('itda:face:results',  (e) => applyFaceBlendshapes(e.detail.blendshapes));
window.addEventListener('itda:hands:results', (e) => applyHandLandmarks(e.detail.hands));
window.addEventListener('itda:pose:results',  (e) => applyPoseLandmarks(e.detail.landmarks));

window.ITDARetargeting5 = {
  applyExternalNMS: (guide, level) => {
    // 백엔드 NMS 가이드를 52종 Blendshape에 맞게 보정하여 강제 적용
    const avatar = window.ITDAAvatar5;
    if (guide.mouth === 'pa') avatar.setMorphTarget('mouthPucker', 0.8);
    if (guide.eyebrows === 'furrowed') avatar.setMorphTarget('browInnerUp', 0.1);
  },
  
  // 디버그: 팔 뼈 캐시 확인용
  getArmBoneCache() { return _armBoneCache; },
};
