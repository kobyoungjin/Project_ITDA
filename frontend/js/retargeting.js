/**
 * retargeting.js  ─  Step 5: Blendshape → 아바타 감정 + 손동작 리타겟팅
 *
 * ■ 역할
 *   1. MediaPipe 52종 faceBlendshapes → RobotExpressive Morph Targets 매핑
 *      - Angry    : browLowererLeft/Right, noseSneerLeft/Right 평균
 *      - Surprised: eyeWideLeft/Right, jawOpen 평균
 *      - Sad      : browInnerUp, mouthFrownLeft/Right 평균
 *   2. HandLandmarker 관절 → Three.js 아바타 Bone 회전 매핑
 *   3. 손동작과 표정이 같은 RAF 루프에서 처리되어 1프레임 단위 동기화 보장
 *
 * ■ 의존성
 *   - avatar.js 가 window.ITDAAvatar5 를 먼저 노출해야 함
 *   - itda:face:results / itda:hands:results 커스텀 이벤트 구독
 */

// ── Blendshape → Morph Target 가중치 맵 ─────────────────────
const EMOTION_MAP = {
  Angry: {
    browLowererLeft: 0.45,
    browLowererRight: 0.45,
    noseSneerLeft: 0.05,
    noseSneerRight: 0.05,
  },
  Surprised: {
    eyeWideLeft: 0.40,
    eyeWideRight: 0.40,
    jawOpen: 0.20,
  },
  Sad: {
    browInnerUp: 0.40,
    mouthFrownLeft: 0.30,
    mouthFrownRight: 0.30,
  },
};

// ── 손 관절 → 아바타 Bone 매핑 ───────────────────────────────
// MediaPipe HandLandmarker: 21 랜드마크 (0=WRIST … 20=PINKY_TIP)
// Three.js Xbot / RobotExpressive 공통 Bone 이름 사용
const HAND_BONE_MAP = {
  // 오른손 (MediaPipe 's label: "Right" = 화면 왼쪽 = 실제 오른손)
  Right: {
    wrist: { bonePrefix: 'RightHand', idx: 0 },
    thumb1: { bonePrefix: 'RightHandThumb1', idx: 1 },
    thumb2: { bonePrefix: 'RightHandThumb2', idx: 2 },
    thumb3: { bonePrefix: 'RightHandThumb3', idx: 3 },
    index1: { bonePrefix: 'RightHandIndex1', idx: 5 },
    index2: { bonePrefix: 'RightHandIndex2', idx: 6 },
    index3: { bonePrefix: 'RightHandIndex3', idx: 7 },
    middle1: { bonePrefix: 'RightHandMiddle1', idx: 9 },
    middle2: { bonePrefix: 'RightHandMiddle2', idx: 10 },
    middle3: { bonePrefix: 'RightHandMiddle3', idx: 11 },
    ring1: { bonePrefix: 'RightHandRing1', idx: 13 },
    ring2: { bonePrefix: 'RightHandRing2', idx: 14 },
    ring3: { bonePrefix: 'RightHandRing3', idx: 15 },
    pinky1: { bonePrefix: 'RightHandPinky1', idx: 17 },
    pinky2: { bonePrefix: 'RightHandPinky2', idx: 18 },
    pinky3: { bonePrefix: 'RightHandPinky3', idx: 19 },
  },
  Left: {
    wrist: { bonePrefix: 'LeftHand', idx: 0 },
    thumb1: { bonePrefix: 'LeftHandThumb1', idx: 1 },
    thumb2: { bonePrefix: 'LeftHandThumb2', idx: 2 },
    thumb3: { bonePrefix: 'LeftHandThumb3', idx: 3 },
    index1: { bonePrefix: 'LeftHandIndex1', idx: 5 },
    index2: { bonePrefix: 'LeftHandIndex2', idx: 6 },
    index3: { bonePrefix: 'LeftHandIndex3', idx: 7 },
    middle1: { bonePrefix: 'LeftHandMiddle1', idx: 9 },
    middle2: { bonePrefix: 'LeftHandMiddle2', idx: 10 },
    middle3: { bonePrefix: 'LeftHandMiddle3', idx: 11 },
    ring1: { bonePrefix: 'LeftHandRing1', idx: 13 },
    ring2: { bonePrefix: 'LeftHandRing2', idx: 14 },
    ring3: { bonePrefix: 'LeftHandRing3', idx: 15 },
    pinky1: { bonePrefix: 'LeftHandPinky1', idx: 17 },
    pinky2: { bonePrefix: 'LeftHandPinky2', idx: 18 },
    pinky3: { bonePrefix: 'LeftHandPinky3', idx: 19 },
  },
};

// ── 현재 감정 상태 (스무딩용) ──────────────────────────────────
const emotionState = { Angry: 0, Surprised: 0, Sad: 0 };

// ── 주 함수: Blendshape → 아바타 Morph Target 업데이트 ────────
function applyFaceBlendshapes(blendshapes) {
  const avatar = window.ITDAAvatar5;
  if (!avatar) return;

  // 1. 각 감정 점수 계산 (가중 평균)
  const bsMap = {};
  for (const { categoryName, score } of blendshapes) {
    bsMap[categoryName] = score;
  }

  const targetScores = {};
  for (const [emotion, weights] of Object.entries(EMOTION_MAP)) {
    let total = 0, wSum = 0;
    for (const [key, w] of Object.entries(weights)) {
      total += (bsMap[key] ?? 0) * w;
      wSum += w;
    }
    targetScores[emotion] = wSum > 0 ? total / wSum : 0;
  }

  // 2. 감정 스무딩 연산 (아바타 리타겟팅 미적용 - 사용자 요청: 텍스트 수어만 표기)
  for (const [emotion, target] of Object.entries(targetScores)) {
    emotionState[emotion] += (target - emotionState[emotion]) * 0.2;
    // avatar.setMorphTarget(emotion, emotionState[emotion]); // 카메라 따라하기 비활성화
  }

  // 3. 감정 HUD 업데이트
  updateEmotionHUD(emotionState);
}

// ── 손 관절 → 아바타 Bone 회전 적용 ───────────────────────────
function applyHandLandmarks(hands) {
  // 사용자 요청: 웹캠 동작을 아바타가 따라 하지 않도록 비활성화 (텍스트 수어 번역만 동작)
  return;

  for (const hand of hands) {
    const side = hand.handedness; // 'Left' | 'Right'
    const lmList = hand.landmarks;  // {x,y,z}[]
    const boneMap = HAND_BONE_MAP[side];
    if (!boneMap) continue;

    for (const [_jointName, { bonePrefix, idx }] of Object.entries(boneMap)) {
      if (idx >= lmList.length) continue;
      const lm = lmList[idx];

      // MediaPipe 좌표(0~1 정규화) → 관절 회전값으로 변환
      // y는 위아래 반전, z는 깊이 보정
      const rotX = (lm.y - 0.5) * Math.PI * 0.8;
      const rotY = (lm.x - 0.5) * Math.PI * 0.6;
      const rotZ = lm.z * Math.PI * 0.4;

      avatar.updateBone(bonePrefix, { x: rotX, y: rotY, z: rotZ });
    }
  }
}

// ── HUD 업데이트 ──────────────────────────────────────────────
function updateEmotionHUD(state) {
  for (const [emotion, value] of Object.entries(state)) {
    const el = document.getElementById(`emotion-${emotion.toLowerCase()}`);
    if (el) {
      el.style.width = `${(value * 100).toFixed(1)}%`;
      el.textContent = `${(value * 100).toFixed(0)}%`;
    }
  }
}

// ══════════════════════════════════════════════════════════════
// ── 팔 IK 엔진 (PoseLandmarker 33개 관절 기반) ────────────────
// ══════════════════════════════════════════════════════════════

const POSE = {
  LEFT_SHOULDER: 11, RIGHT_SHOULDER: 12,
  LEFT_ELBOW: 13, RIGHT_ELBOW: 14,
  LEFT_WRIST: 15, RIGHT_WRIST: 16,
  LEFT_HIP: 23, RIGHT_HIP: 24,
};

const ARM_BONE_CANDIDATES = {
  shoulder: ['Shoulder'],
  upperArm: ['Arm', 'UpperArm', 'upperArm'],
  foreArm: ['ForeArm', 'foreArm', 'LowerArm'],
  hand: ['Hand', 'hand'],
};

function findBone(bones, side, candidates) {
  for (const c of candidates) {
    if (bones[`${side}${c}`]) return `${side}${c}`;
    if (bones[`mixamorig:${side}${c}`]) return `mixamorig:${side}${c}`;
    if (bones[`mixamorig${side}${c}`]) return `mixamorig${side}${c}`;
  }
  return null;
}

// 왼쪽=따뜻한 계열, 오른쪽=차가운 계열
const MARKER_COLORS = {
  Left: { shoulder: 0xFF6B6B, upperArm: 0xFF9933, hand: 0xFFCC00 },
  Right: { shoulder: 0x4488FF, upperArm: 0x44CCFF, hand: 0x44FFCC },
};

const _armBoneCache = {};
function getArmBones(side, bones) {
  if (_armBoneCache[side]) return _armBoneCache[side];
  const result = {
    shoulder: findBone(bones, side, ARM_BONE_CANDIDATES.shoulder),
    upperArm: findBone(bones, side, ARM_BONE_CANDIDATES.upperArm),
    foreArm: findBone(bones, side, ARM_BONE_CANDIDATES.foreArm),
    hand: findBone(bones, side, ARM_BONE_CANDIDATES.hand),
  };
  _armBoneCache[side] = result;
  const avatar = window.ITDAAvatar5;
  if (avatar?.addBoneMarker) {
    const c = MARKER_COLORS[side] ?? MARKER_COLORS.Left;
    if (result.shoulder) avatar.addBoneMarker(result.shoulder, c.shoulder);
    if (result.upperArm) avatar.addBoneMarker(result.upperArm, c.upperArm);
    if (result.hand) avatar.addBoneMarker(result.hand, c.hand);
  }
  return result;
}

const _zBuf = {};
function angleBetween(parent, child) {
  const dx = -(child.x - parent.x);
  const dy = child.y - parent.y;
  const rawDz = -(child.z - parent.z);
  const key = `${parent.x.toFixed(3)},${parent.y.toFixed(3)}`;
  const prev = _zBuf[key] ?? rawDz;
  const dz = prev + (rawDz - prev) * 0.15;
  _zBuf[key] = dz;
  return {
    y: Math.atan2(dx, dz || 0.001),
    z: Math.atan2(-dy, Math.sqrt(dx * dx + dz * dz) || 0.001),
    x: Math.atan2(dz, Math.sqrt(dx * dx + dy * dy) || 0.001),
  };
}

function bendAngle(a, b, c) {
  const ab = { x: b.x - a.x, y: b.y - a.y, z: b.z - a.z };
  const bc = { x: c.x - b.x, y: c.y - b.y, z: c.z - b.z };
  const dot = ab.x * bc.x + ab.y * bc.y + ab.z * bc.z;
  const mag = (Math.sqrt(ab.x ** 2 + ab.y ** 2 + ab.z ** 2) || 0.001)
    * (Math.sqrt(bc.x ** 2 + bc.y ** 2 + bc.z ** 2) || 0.001);
  return Math.acos(Math.max(-1, Math.min(1, dot / mag)));
}

let _lastPoseActive = 0;

function applyPoseLandmarks(poseLandmarks) {
  // 사용자 요청: 웹캠 동작을 아바타가 따라 하지 않도록 비활성화
  return;

  if (!poseLandmarks) {
    // 미인식 시 차렷 자세로 복귀
    ['Right', 'Left'].forEach(side => {
      const b = getArmBones(side, avatar.bones);
      // 신규 모델 대응: 만세 현상을 해결하기 위해 부호 반전
      const downZ = side === 'Right' ? -Math.PI / 2 : Math.PI / 2;

      // 어깨가 안으로 굽지 않도록 Y축 회전 제거
      if (b.shoulder) avatar.updateBone(b.shoulder, { x: 0, y: 0, z: 0 }, 0.05);
      // 팔꿈치가 얼굴로 가지 않도록 X, Y축을 0으로 고정하고 Z축만 조절
      if (b.upperArm) avatar.updateBone(b.upperArm, { x: 0, y: 0, z: downZ }, 0.05);
      if (b.foreArm) avatar.updateBone(b.foreArm, { x: 0.1, y: 0, z: 0 }, 0.05);
    });
    return;
  }

  const core = [POSE.LEFT_SHOULDER, POSE.RIGHT_SHOULDER, POSE.LEFT_ELBOW, POSE.RIGHT_ELBOW];
  const visible = core.every(i => (poseLandmarks[i]?.visibility ?? 0) > 0.85);
  if (!visible) return;

  _lastPoseActive = performance.now();

  // Mirror 모드: 사용자 오른쪽(데이터 Right) -> 아바타 왼쪽(화면 오른쪽)
  // 사용자 왼쪽(데이터 Left) -> 아바타 오른쪽(화면 왼쪽)
  applySingleArm('Right', poseLandmarks, avatar, 'Left');
  applySingleArm('Left', poseLandmarks, avatar, 'Right');
}

function applySingleArm(boneSide, lms, avatar, dataSide) {
  const b = getArmBones(boneSide, avatar.bones);

  const sIdx = dataSide === 'Left' ? POSE.LEFT_SHOULDER : POSE.RIGHT_SHOULDER;
  const eIdx = dataSide === 'Left' ? POSE.LEFT_ELBOW : POSE.RIGHT_ELBOW;
  const wIdx = dataSide === 'Left' ? POSE.LEFT_WRIST : POSE.RIGHT_WRIST;
  const hIdx = dataSide === 'Left' ? POSE.LEFT_HIP : POSE.RIGHT_HIP;

  const shoulder = lms[sIdx];
  const elbow = lms[eIdx];
  const wrist = lms[wIdx];
  const hip = lms[hIdx];
  if (!shoulder || !elbow || !wrist) return;

  // 상완 방향 보정 (T-Pose 기반)
  const upperArmAngle = angleBetween(shoulder, elbow);
  if (b.upperArm) {
    // 신규 모델 특성: T-Pose 기준, 팔을 내리는 각도가 Side별로 상이함
    // T-Pose 기반 오프셋: 팔이 위(만세)로 가는 것을 막고 아래를 향하게 함
    let finalZ = upperArmAngle.z;
    if (boneSide === 'Right') {
      finalZ = upperArmAngle.z - Math.PI / 2; // 오른쪽 보정
    } else {
      finalZ = upperArmAngle.z + Math.PI / 2; // 왼쪽 보정
    }

    avatar.updateBone(b.upperArm, {
      x: upperArmAngle.x * 0.8,
      y: upperArmAngle.y * 0.8,
      z: finalZ,
    }, 0.2);
  }

  // 어깨 보정 (몸 안으로 파고드는 현상 방지)
  const hipVisible = hip && (hip.visibility ?? 0) > 0.4;
  if (b.shoulder) {
    const clamp = (v, min, max) => Math.max(min, Math.min(max, v));
    const shoulderAngle = angleBetween(shoulder, elbow);
    const torsoAngle = hipVisible ? angleBetween(hip, shoulder) : { y: 0, z: 0 };

    // y축 부호 반전 또는 범위 제한으로 몸 안쪽 침범 방지
    let targetY = (shoulderAngle.y - torsoAngle.y) * 0.35;
    if (boneSide === 'Right') targetY = -targetY; // 오른어깨 보정

    avatar.updateBone(b.shoulder, {
      x: 0,
      y: clamp(targetY, -0.15, 0.15),
      z: clamp((shoulderAngle.z - torsoAngle.z) * 0.2, -0.1, 0.1),
    }, 0.15);
  }

  // 전완 (팔꿈치 굽힘)
  if (b.foreArm) {
    const bend = bendAngle(shoulder, elbow, wrist);
    const foreAngle = angleBetween(elbow, wrist);
    avatar.updateBone(b.foreArm, {
      x: bend * 1.1,
      y: foreAngle.y * 0.4,
      z: 0,
    }, 0.2);
  }

  // 손목 방향
  if (b.hand) {
    const wristAngle = angleBetween(elbow, wrist);
    avatar.updateBone(b.hand, {
      x: wristAngle.x * 0.5,
      y: wristAngle.y * 0.5,
      z: 0,
    }, 0.2);
  }
}

// ── 이벤트 구독 ───────────────────────────────────────────────
window.addEventListener('itda:face:results', (e) => applyFaceBlendshapes(e.detail.blendshapes));
window.addEventListener('itda:hands:results', (e) => applyHandLandmarks(e.detail.hands));
window.addEventListener('itda:pose:results', (e) => applyPoseLandmarks(e.detail.landmarks));

// ── 75개 관절 데이터 (LH 21 + RH 21 + POSE 33) 통합 적용 ──────
function apply75Landmarks(landmarks75) {
  if (!landmarks75 || landmarks75.length < 75 * 3) return;
  const avatar = window.ITDAAvatar5;
  if (!avatar) return;

  // 1. 데이터 분리
  const points = [];
  let allZero = true;
  for (let i = 0; i < 75; i++) {
    const x = landmarks75[i * 3];
    const y = landmarks75[i * 3 + 1];
    const z = landmarks75[i * 3 + 2];
    if (x !== 0 || y !== 0) allZero = false;
    points.push({ x, y, z });
  }

  // 무효 프레임 (전부 0) 건너뛰기
  if (allZero) return;

  const lh = points.slice(0, 21);
  const rh = points.slice(21, 42);
  const pose = points.slice(42, 75);

  // 2. 몸통(Pose) 리타겟팅
  // 어깨 관절이 (0,0)이면 데이터가 유효하지 않은 것으로 간주
  if (pose[11].x !== 0 || pose[12].x !== 0) {
    _applyPoseDirect(pose, avatar);
  }

  // 3. 손(Hands) 리타겟팅
  _applyHandDirect('Left', lh, avatar);
  _applyHandDirect('Right', rh, avatar);
}

function _applyPoseDirect(lms, avatar) {
  // Mirror 모드: 데이터 Left -> 아바타 Right
  applySingleArm('Right', lms, avatar, 'Left');
  applySingleArm('Left', lms, avatar, 'Right');
  
  // Hips/Root 보정 (Pose 23, 24 기반)
  if (lms[23] && lms[24]) {
    const midX = (lms[23].x + lms[24].x) / 2;
    const midY = (lms[23].y + lms[24].y) / 2;
    // 아바타 위치 미세 조정 (선택 사항)
    // avatar.updateBone('Hips', { x: (0.5 - midX) * 0.5, y: (0.5 - midY) * 0.5, z: 0 });
  }
}

function _applyHandDirect(side, lms, avatar) {
  const boneMap = HAND_BONE_MAP[side];
  if (!boneMap) return;

  // 손목 데이터가 없으면 중단
  if (lms[0].x === 0 && lms[0].y === 0) return;

  for (const [key, { bonePrefix, idx }] of Object.entries(boneMap)) {
    const lm = lms[idx];
    if (!lm || (idx > 0 && lm.x === 0 && lm.y === 0)) continue;

    let rotX = 0, rotY = 0, rotZ = 0;

    if (key === 'wrist') {
        // 손목은 Pose 엔진이 처리하므로 미세 조정만 수행 (옵션)
        continue;
    } else if (key.includes('thumb')) {
        // 엄지: MediaPipe 좌표 차이를 이용한 굽힘 근사
        // 엄지는 Y축 회전이 큼
        rotX = (0.5 - lm.y) * Math.PI * 0.4;
        rotY = (side === 'Right' ? (0.5 - lm.x) : (lm.x - 0.5)) * Math.PI * 0.8;
    } else {
        // 검지~소지: 손목 대비 Y좌표 차이로 굽힘 각도 계산
        // lm.y가 lms[0].y보다 크면(아래쪽) 굽혀진 상태
        const bend = Math.max(0, (lm.y - lms[0].y) * 2.0);
        rotX = bend * Math.PI * 0.6;
    }

    avatar.updateBone(bonePrefix, { x: rotX, y: rotY, z: rotZ }, 0.25);
  }
}

// ── 전역 노출 ─────────────────────────────────────────────────
window.ITDARetargeting5 = {
  applyFaceBlendshapes,
  applyHandLandmarks,
  applyPoseLandmarks,
  apply75Landmarks, // 신규 추가
  emotionState,
  EMOTION_MAP,
};
