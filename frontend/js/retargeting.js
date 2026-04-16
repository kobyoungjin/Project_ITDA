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
    browLowererLeft:   0.45,
    browLowererRight:  0.45,
    noseSneerLeft:     0.05,
    noseSneerRight:    0.05,
  },
  Surprised: {
    eyeWideLeft:       0.40,
    eyeWideRight:      0.40,
    jawOpen:           0.20,
  },
  Sad: {
    browInnerUp:       0.40,
    mouthFrownLeft:    0.30,
    mouthFrownRight:   0.30,
  },
};

// ── 손 관절 → 아바타 Bone 매핑 ───────────────────────────────
// MediaPipe HandLandmarker: 21 랜드마크 (0=WRIST … 20=PINKY_TIP)
// Three.js Xbot / RobotExpressive 공통 Bone 이름 사용
const HAND_BONE_MAP = {
  // 오른손 (MediaPipe 's label: "Right" = 화면 왼쪽 = 실제 오른손)
  Right: {
    wrist:       { bonePrefix: 'RightHand',       idx: 0 },
    thumb0:      { bonePrefix: 'RightHandThumb1', idx: 2 },
    thumb1:      { bonePrefix: 'RightHandThumb2', idx: 3 },
    index0:      { bonePrefix: 'RightHandIndex1', idx: 5 },
    index1:      { bonePrefix: 'RightHandIndex2', idx: 6 },
    middle0:     { bonePrefix: 'RightHandMiddle1',idx: 9 },
    ring0:       { bonePrefix: 'RightHandRing1',  idx: 13 },
    pinky0:      { bonePrefix: 'RightHandPinky1', idx: 17 },
  },
  Left: {
    wrist:       { bonePrefix: 'LeftHand',        idx: 0 },
    thumb0:      { bonePrefix: 'LeftHandThumb1',  idx: 2 },
    thumb1:      { bonePrefix: 'LeftHandThumb2',  idx: 3 },
    index0:      { bonePrefix: 'LeftHandIndex1',  idx: 5 },
    index1:      { bonePrefix: 'LeftHandIndex2',  idx: 6 },
    middle0:     { bonePrefix: 'LeftHandMiddle1', idx: 9 },
    ring0:       { bonePrefix: 'LeftHandRing1',   idx: 13 },
    pinky0:      { bonePrefix: 'LeftHandPinky1',  idx: 17 },
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
      wSum  += w;
    }
    targetScores[emotion] = wSum > 0 ? total / wSum : 0;
  }

  // 2. Lerp 적용 후 아바타에 전달 (α = 0.2 → 부드러운 전환)
  // 단, 번역 텍스트에 의한 아바타 애니메이션이 재생 중이면 웹캠 감정 리타겟팅을 멈춥니다.
  if (!window.translationModeActive) {
    for (const [emotion, target] of Object.entries(targetScores)) {
      emotionState[emotion] += (target - emotionState[emotion]) * 0.2;
      avatar.setMorphTarget(emotion, emotionState[emotion]);
    }
  }

  // 3. 감정 HUD 업데이트
  updateEmotionHUD(emotionState);
}

// ── 손 관절 → 아바타 Bone 회전 적용 ───────────────────────────
function applyHandLandmarks(hands) {
  const avatar = window.ITDAAvatar5;
  if (!avatar || window.translationModeActive) return;

  for (const hand of hands) {
    const side   = hand.handedness; // 'Left' | 'Right'
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

// ── 이벤트 구독 ───────────────────────────────────────────────
window.addEventListener('itda:face:results',  (e) => applyFaceBlendshapes(e.detail.blendshapes));
window.addEventListener('itda:hands:results', (e) => applyHandLandmarks(e.detail.hands));

// ── 전역 노출 ─────────────────────────────────────────────────
window.ITDARetargeting5 = {
  applyFaceBlendshapes,
  applyHandLandmarks,
  emotionState,
  EMOTION_MAP,
};
