/**
 * vision.js  ─  Step 5: 얼굴 + 손 통합 비전 엔진
 *
 * ■ 역할
 *   1. MediaPipe Hands (21 관절) → 손동작 데이터 추출
 *   2. MediaPipe FaceLandmarker (52 Blendshapes) → 얼굴 표정 데이터 추출
 *   3. 하나의 웹캠 스트림으로 두 모델을 병렬 처리 (requestAnimationFrame 루프)
 *   4. 커스텀 이벤트를 발행하여 avatar.js / retargeting.js 가 구독
 *
 * ■ 발행 이벤트
 *   - itda:hands:results  → { hands: HandResult[] }
 *   - itda:face:results   → { blendshapes: Blendshape[] }
 *   - itda:fps:update     → { fps: number }
 */

import {
  FilesetResolver,
  FaceLandmarker,
  HandLandmarker,
  PoseLandmarker,
  DrawingUtils,
} from 'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.12/vision_bundle.mjs';

const HAND_CONNECTIONS = [
  { start: 0, end: 1 }, { start: 1, end: 2 }, { start: 2, end: 3 }, { start: 3, end: 4 }, // 엄지
  { start: 0, end: 5 }, { start: 5, end: 6 }, { start: 6, end: 7 }, { start: 7, end: 8 }, // 검지
  { start: 5, end: 9 }, { start: 9, end: 10 }, { start: 10, end: 11 }, { start: 11, end: 12 }, // 중지
  { start: 9, end: 13 }, { start: 13, end: 14 }, { start: 14, end: 15 }, { start: 15, end: 16 }, // 약지
  { start: 13, end: 17 }, { start: 17, end: 18 }, { start: 18, end: 19 }, { start: 19, end: 20 }, // 소지
  { start: 0, end: 17 } // 손바닥 밑부분
];
// Simplified FaceMesh connections for performance
const FACEMESH_TESSELATION = [[10, 338], [338, 297], [297, 332], [332, 284], [284, 251], [251, 389], [389, 356], [356, 454], [454, 323], [323, 361], [361, 288], [288, 397], [397, 365], [365, 379], [379, 378], [378, 400], [400, 377], [377, 152], [152, 148], [148, 176], [176, 149], [149, 150], [150, 136], [136, 172], [172, 58], [58, 132], [132, 93], [93, 234], [234, 127], [127, 162], [162, 21], [21, 54], [54, 103], [103, 67], [67, 109], [109, 10]];

// ── 설정 ──────────────────────────────────────────────────────
const CONFIG = {
  MIN_FRAME_INTERVAL_MS: 16,        // ~60 fps (기존 33ms에서 상향)
  FACE_DETECTION_CONFIDENCE: 0.5,
  FACE_TRACKING_CONFIDENCE: 0.5,
  HAND_DETECTION_CONFIDENCE: 0.25,  // 더 약한 손/부분 노출도 탐지
  HAND_PRESENCE_CONFIDENCE: 0.25,
  HAND_TRACKING_CONFIDENCE: 0.25,
  // 후보는 넉넉히 잡고(여러 사람 손 포함), 최종 2개만 사용 — 어깨·팔로 이어지는 손만 통과
  MAX_HANDS_DETECT: 4,
  MAX_HANDS_OUTPUT: 2,
  // 포즈 손목과 손 landmark[0] 사이 정규화 거리 임계 — 초과 시 다른 사람의 손으로 판단
  POSE_HAND_LINK_THRESHOLD: 0.22,
  // 손 가림(occlusion) 대응 — 마지막 유효 손 모양을 포즈 손목 이동으로 보정해 예측 (ms)
  HAND_PREDICT_MAX_MS: 500,
  MIN_CAMERA_WIDTH: 1280,
  MIN_CAMERA_HEIGHT: 720,
};

// ── 내부 상태 ─────────────────────────────────────────────────
let faceLandmarker = null;
let handLandmarker = null;
let poseLandmarker = null;
let videoStream = null;
let animationId = null;
let lastFrameTime = 0;
let lastFpsSample = 0;
let fpsBuffer = [];
let isRunning = false;

const videoEl = document.getElementById('vision-video');
const canvasEl = document.getElementById('vision-canvas');
const statusEl = document.getElementById('vision-status');
const canvasCtx = canvasEl.getContext('2d');
let drawingUtils = null;

// ── 표정 스무딩 버퍼 (Lerp 용) ────────────────────────────────
const blendBuffer = {};

// ── 초기화 ───────────────────────────────────────────────────
async function init() {
  try {
    setStatus('MediaPipe 모델 로딩 중…');

    const vision = await FilesetResolver.forVisionTasks(
      'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.12/wasm',
    );

    // ① FaceLandmarker
    faceLandmarker = await FaceLandmarker.createFromOptions(vision, {
      baseOptions: {
        modelAssetPath: 'https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task',
        delegate: 'GPU', // CPU -> GPU 가속
      },
      outputFaceBlendshapes: true,
      runningMode: 'VIDEO',
      numFaces: 1,
      minFaceDetectionConfidence: CONFIG.FACE_DETECTION_CONFIDENCE,
      minTrackingConfidence: CONFIG.FACE_TRACKING_CONFIDENCE,
    });

    // ② HandLandmarker — 후보를 4개까지 검출하고 포즈와 매칭해 2개만 통과시킴
    handLandmarker = await HandLandmarker.createFromOptions(vision, {
      baseOptions: {
        modelAssetPath: 'https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task',
        delegate: 'GPU', // CPU -> GPU 가속
      },
      runningMode: 'VIDEO',
      numHands: CONFIG.MAX_HANDS_DETECT,
      minHandDetectionConfidence: CONFIG.HAND_DETECTION_CONFIDENCE,
      minHandPresenceConfidence: CONFIG.HAND_PRESENCE_CONFIDENCE,
      minTrackingConfidence: CONFIG.HAND_TRACKING_CONFIDENCE,
    });

    // ③ PoseLandmarker (팔·어깨·몸통 33개 관절) - 교차/겹침 상황 정확도 향상을 위해 full 모델 사용
    poseLandmarker = await PoseLandmarker.createFromOptions(vision, {
      baseOptions: {
        modelAssetPath: 'https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task',
        delegate: 'GPU', // full -> lite 모델로 경량화 및 GPU 가속
      },
      runningMode: 'VIDEO',
      numPoses: 1,
      minPoseDetectionConfidence: 0.5,
      minPosePresenceConfidence: 0.5,
      minTrackingConfidence: 0.5,
      outputSegmentationMasks: false,
    });

    setStatus('카메라 연결 중…');
    await startCamera();

    // Initialize DrawingUtils
    drawingUtils = new DrawingUtils(canvasCtx);

    setStatus('✅ 실행 중');
    connectWebSocket(); // [활성화] 실시간 수어 번역을 위해 백엔드 웹소켓 연결 시작
    window.dispatchEvent(new CustomEvent('itda:vision:ready'));

  } catch (err) {
    console.error('[ITDA Vision] 초기화 실패:', err);
    setStatus('❌ 초기화 실패: ' + err.message);
  }
}

// ── 카메라 시작 ───────────────────────────────────────────────
// 현재 사용 중인 카메라 방향. 'user'=전면, 'environment'=후면(모바일).
let currentFacingMode = 'user';

async function startCamera() {
  videoStream = await navigator.mediaDevices.getUserMedia({
    video: {
      width: { ideal: CONFIG.MIN_CAMERA_WIDTH },
      height: { ideal: CONFIG.MIN_CAMERA_HEIGHT },
      frameRate: { ideal: 30 },
      facingMode: currentFacingMode,
    },
    audio: false,
  });
  videoEl.srcObject = videoStream;
  await new Promise(res => { videoEl.onloadedmetadata = res; });
  videoEl.play();
  isRunning = true;
  // 전면 카메라는 사용자가 자기 모습을 보는 게 자연스러우므로 좌우반전.
  // 후면 카메라는 실세계를 그대로 보여야 하므로 반전하지 않는다.
  videoEl.style.transform = (currentFacingMode === 'user') ? 'scaleX(-1)' : 'scaleX(1)';
  if (canvasEl) {
    canvasEl.style.transform = (currentFacingMode === 'user') ? 'scaleX(-1)' : 'scaleX(1)';
  }
  requestAnimationFrame(processFrame);
}

// 전·후면 카메라 전환. 현재 카메라를 정지하고 반대편 facingMode 로 재시작.
async function switchCamera() {
  const wasRunning = isRunning;
  currentFacingMode = (currentFacingMode === 'user') ? 'environment' : 'user';
  if (videoStream) {
    videoStream.getTracks().forEach(t => t.stop());
    videoStream = null;
  }
  if (wasRunning) {
    isRunning = false;
    try {
      await startCamera();
      setStatus('✅ 실행 중 (' + (currentFacingMode === 'user' ? '전면' : '후면') + ')');
    } catch (err) {
      // 후면 카메라가 없는 디바이스 등은 원래 facingMode 로 폴백
      console.warn('[ITDA Vision] 카메라 전환 실패, 폴백:', err.message);
      currentFacingMode = (currentFacingMode === 'user') ? 'environment' : 'user';
      await startCamera();
      setStatus('⚠️ 다른 카메라가 없습니다');
    }
  }
  return currentFacingMode;
}

// ── WebSocket 연동 상태 ───────────────────────────────────────
// 페이지를 서빙한 호스트를 그대로 사용해 origin 과 WS 대상의 IPv4/IPv6 혼선을 방지.
// file:// 로 직접 열었을 때만 127.0.0.1 로 폴백.
const WS_URL = `${(window.ITDAConfig?.API_WS) || `ws://${location.hostname || '127.0.0.1'}:8000`}/api/ws/vision`;
let ws = null;
let sessionId = crypto.randomUUID();
let frameCounter = 0;
let lastSendTime = 0;
let currentFPS = 0;
let prevWristY = null; // 모션 변화량 추적을 위한 이전 손목 Y좌표

let wsRetryCount = 0;

// [P0] Pose 캐시 — PoseLandmarker 결과를 sendFrameWS 타이밍에 백엔드로 함께 전송
let latestPoseLandmarks = null;
const POSE_KEYS = {
  nose: 0,
  left_shoulder: 11, right_shoulder: 12,
  left_elbow: 13, right_elbow: 14,
  left_wrist: 15, right_wrist: 16,
  left_hip: 23, right_hip: 24,
};

// [P2] 모션 세그먼테이션 상태머신 ──────────────────────────────
//  idle      : 손이 감지 안됨
//  moving    : 손목 속도 > 임계값
//  settling  : 속도 떨어지는 중 (감속)
//  stable    : 500ms 이상 거의 정지 → 수어 한 단어가 "완성"됐다고 판정,
//              백엔드에 full-pipeline 실행 플래그 전달
const MOTION_THRESHOLDS = {
  MOVING_SPEED: 0.015,  // 정규화 좌표/프레임 (약 1.5% 화면 이동)
  STABLE_SPEED: 0.004,
  STABLE_HOLD_MS: 500, // 정지 상태가 0.5초 이상 유지되어야 동작 완료(stable)로 판정 (반응성 향상)
};
const motionState = {
  phase: 'idle',         // idle | moving | settling | stable
  lastWristR: null,      // 오른쪽 손목 최신 좌표
  lastWristL: null,
  speed: 0,              // 두 손목 중 큰 속도
  stillSince: 0,         // ms 타임스탬프 (정지 시작 시각)
  lastPhaseChange: 0,    // 최근 phase 변경 시각 (디바운스)
};

function _updateMotionPhase(hands, nowMs) {
  // 손이 없으면 idle
  if (!hands || hands.length === 0) {
    motionState.lastWristR = motionState.lastWristL = null;
    motionState.speed = 0;
    if (motionState.phase !== 'idle') {
      motionState.phase = 'idle';
      motionState.lastPhaseChange = nowMs;
    }
    return;
  }

  // 두 손목 속도 중 큰 값을 사용
  let maxSpeed = 0;
  for (const h of hands) {
    const w = h.landmarks[0];
    const key = h.handedness === 'Right' ? 'lastWristR' : 'lastWristL';
    const prev = motionState[key];
    if (prev) {
      const dx = w.x - prev.x, dy = w.y - prev.y;
      const s = Math.hypot(dx, dy);
      if (s > maxSpeed) maxSpeed = s;
    }
    motionState[key] = { x: w.x, y: w.y };
  }
  motionState.speed = maxSpeed;

  const prevPhase = motionState.phase;
  if (maxSpeed > MOTION_THRESHOLDS.MOVING_SPEED) {
    motionState.phase = 'moving';
    motionState.stillSince = 0;
  } else if (maxSpeed > MOTION_THRESHOLDS.STABLE_SPEED) {
    motionState.phase = (prevPhase === 'moving' || prevPhase === 'settling') ? 'settling' : motionState.phase;
  } else {
    // 거의 정지
    if (!motionState.stillSince) motionState.stillSince = nowMs;
    const heldMs = nowMs - motionState.stillSince;
    if (heldMs >= MOTION_THRESHOLDS.STABLE_HOLD_MS &&
      (prevPhase === 'moving' || prevPhase === 'settling')) {
      motionState.phase = 'stable';  // 이번 프레임 1회만 stable 로 트리거
    } else if (prevPhase === 'stable') {
      motionState.phase = 'idle';    // stable 은 1프레임 이벤트
    }
  }
  if (prevPhase !== motionState.phase) {
    motionState.lastPhaseChange = nowMs;
    // [P2 HUD] phase 변경 즉시 UI로 통지 — WS 연결과 무관하게 단독 모드에서도 동작
    window.dispatchEvent(new CustomEvent('itda:motion:phase', {
      detail: { phase: motionState.phase, speed: motionState.speed },
    }));
  }
}

function connectWebSocket() {
  if (ws && ws.readyState === WebSocket.OPEN) return;
  ws = new WebSocket(WS_URL);
  ws.onopen = () => {
    console.info("[ITDA WebSocket] 백엔드 RAG 연동 완료");
    wsRetryCount = 0;
    window.dispatchEvent(new CustomEvent('itda:vision:ws_state', { detail: { state: 'connected' } }));
  };
  ws.onmessage = (evt) => {
    try {
      const ack = JSON.parse(evt.data);
      if (ack.rag_result) {
        window.dispatchEvent(new CustomEvent('itda:rag:result', { detail: ack }));
      }
      // [P0] 백엔드 Handshape 분석 결과 브로드캐스트 → avatar/HUD/교육 모듈이 구독
      if (ack.hand_analyses && ack.hand_analyses.length > 0) {
        window.dispatchEvent(new CustomEvent('itda:hands:analysis', { detail: ack.hand_analyses }));
      }
      // [P0] 백엔드 Pose 분석 결과 브로드캐스트
      if (ack.pose_analysis) {
        window.dispatchEvent(new CustomEvent('itda:pose:analysis', { detail: ack.pose_analysis }));
      }
    } catch (e) { }
  };
  ws.onerror = (err) => {
    console.error("[ITDA WebSocket] 에러 발생:", err);
    window.dispatchEvent(new CustomEvent('itda:vision:ws_state', {
      detail: { state: 'error', message: 'Connection Refused (Check Backend)' }
    }));
  };
  ws.onclose = (evt) => {
    window.dispatchEvent(new CustomEvent('itda:vision:ws_state', {
      detail: { state: 'disconnected', code: evt.code, reason: evt.reason }
    }));
    wsRetryCount++;
    // 초반 3회는 빠르게(2초), 이후에는 느리게(15초) 무한 재시도한다.
    // 영구 포기하지 않으므로 백엔드가 나중에 켜져도 자동으로 복구된다.
    const delay = wsRetryCount <= 3 ? 2000 : 15000;
    if (wsRetryCount === 4) {
      console.info("💡 [ITDA] 백엔드(8000) 오프라인. 단독 모드로 전환하고 15초마다 백그라운드 재연결을 시도합니다.");
    }
    console.warn(`[ITDA] 백엔드 연결 끊김 (코드: ${evt.code}). ${delay / 1000}초 후 재연결 시도 (${wsRetryCount}회차)`);
    setTimeout(connectWebSocket, delay);
    window.dispatchEvent(new CustomEvent('itda:vision:ws_state', { detail: { state: 'connecting' } }));
  };
}

function sendFrameWS(hands) {
  const now = performance.now();

  // [P2] 모션 상태머신은 WS 연결 여부와 무관하게 매 프레임 갱신 (phase 이벤트는 단독 모드에서도 유용)
  _updateMotionPhase(hands, now);

  if (!ws || ws.readyState !== WebSocket.OPEN) return;

  // [과제 3] 0.3초(300ms) 단위로 버퍼링/제한 (기존 500ms에서 속도 상향)
  const isFinalTrigger = motionState.phase === 'stable';
  if (!isFinalTrigger && now - lastSendTime < 300) return;
  lastSendTime = now;

  // [P0] 손 관절 랜드마크 전송: 21개 전체 랜드마크 전송
  // 백엔드 ml_utils에서 직접 정규화(wrist 기준) 및 거리 계산을 수행하므로 절대좌표로 전송
  const handDataList = hands.map(h => {
    const keypoints = h.landmarks.map(lm => ({
      x: +lm.x.toFixed(4),
      y: +lm.y.toFixed(4),
      z: +(lm.z ?? 0).toFixed(4),
    }));
    return { handedness: h.handedness, keypoints: keypoints, normalized: false };
  });

  // [과제 1] 원시 좌표(x,y,z) 대신 백엔드가 이해하기 쉬운 메타데이터 추출
  let movement_desc = "정지 상태";
  if (hands.length > 0) {
    const currentWristY = hands[0].landmarks[0].y; // 0은 맨 위(이마쪽), 1은 맨 아래(가슴쪽)
    if (prevWristY !== null) {
      const deltaY = currentWristY - prevWristY;
      if (deltaY > 0.005) {
        movement_desc = "손목이 위에서 아래로 부드럽게 내려옵니다."; // 예: 감사합니다 등
      } else if (deltaY < -0.005) {
        movement_desc = "손목이 아래에서 위로 올라갑니다.";
      }
    }
    prevWristY = currentWristY;
  } else {
    prevWristY = null;
  }

  // [P0] Pose 동봉: 어깨/팔꿈치/손목/엉덩이 좌표를 POSE_KEYS 라벨 기반 dict 로 변환
  let poseField = null;
  if (latestPoseLandmarks) {
    const lmDict = {};
    for (const [label, idx] of Object.entries(POSE_KEYS)) {
      const lm = latestPoseLandmarks[idx];
      if (!lm) continue;
      lmDict[label] = {
        x: +lm.x.toFixed(4),
        y: +lm.y.toFixed(4),
        z: +(lm.z ?? 0).toFixed(4),
        visibility: +(lm.visibility ?? 1.0).toFixed(3),
      };
    }
    if (Object.keys(lmDict).length > 0) poseField = { landmarks: lmDict };
  }

  ws.send(JSON.stringify({
    frame_id: frameCounter++,
    session_id: sessionId,
    timestamp_ms: now,
    fps: currentFPS,
    hands: handDataList,
    pose: poseField,
    meta_features: {               // 백엔드로 보낼 정제된 특징
      movement: movement_desc,
      hand_count: hands.length,
      // [P2] 모션 상태 — 백엔드가 Track2/Track3 게이팅에 사용
      motion_phase: motionState.phase,
      motion_speed: +motionState.speed.toFixed(4),
    }
  }));
}

// ── 손 후보 → 포즈 매칭·근접 우선 선별 ────────────────────────
// 여러 사람이 있을 때 손이 사람 간 점프하는 문제 해결:
//   1) 포즈 손목(LM 15/16)과 가까운 손 = "어깨·팔에서 이어진" 손 → 우선
//   2) 임계 거리 초과 = 다른 사람의 손 → 후순위
//   3) 동등하면 손 크기(palm size) 큰 쪽 = 카메라에 더 가까운 손 우선
//   4) 좌·우 손 다양성 확보 (한쪽 손만 두 개 잡히는 것보다 좌·우 한 개씩 선호)
function _dist2D(a, b) {
  const dx = a.x - b.x;
  const dy = a.y - b.y;
  return Math.sqrt(dx*dx + dy*dy);
}
function _pickPrimaryHands(handResult, poseLandmarks) {
  if (!handResult?.landmarks || handResult.landmarks.length === 0) {
    return { landmarks: [], handedness: [] };
  }
  const lw = poseLandmarks?.[15] ?? null;
  const rw = poseLandmarks?.[16] ?? null;
  const hasPoseWrists = lw && rw;

  const candidates = handResult.landmarks.map((lm, i) => {
    const handWrist = lm[0];
    const palmSize = _dist2D(lm[0], lm[9]); // wrist ↔ middle MCP, 클수록 카메라 근접
    let poseDist = Infinity;
    if (hasPoseWrists) {
      poseDist = Math.min(_dist2D(handWrist, lw), _dist2D(handWrist, rw));
    }
    return {
      landmarks: lm,
      handedness: handResult.handedness[i]?.[0]?.displayName ?? 'Unknown',
      handednessScore: handResult.handedness[i]?.[0]?.score ?? 0,
      palmSize,
      poseDist,
    };
  });

  // 정렬 점수: 포즈와 매칭된 손이 항상 우선. 포즈 임계 초과(다른 사람)는 큰 페널티.
  const T = CONFIG.POSE_HAND_LINK_THRESHOLD;
  candidates.forEach(c => {
    if (!hasPoseWrists) {
      // 포즈가 없으면 손 크기만으로 판단 (가까운 손이 우선)
      c.score = -c.palmSize;
    } else if (c.poseDist <= T) {
      // 포즈와 매칭된 손 — 거리가 가까울수록(=정확히 손목 위) 좋음
      c.score = c.poseDist;
    } else {
      // 임계 초과 — 다른 사람 손으로 보고 페널티 부과
      c.score = c.poseDist + 1.0;
    }
  });
  candidates.sort((a, b) => a.score - b.score);

  // 좌·우 다양성: 가장 좋은 Left 1개 + Right 1개 우선, 부족하면 다음 후보로 채움
  const N = CONFIG.MAX_HANDS_OUTPUT;
  const picked = [];
  const handednessSeen = new Set();
  for (const c of candidates) {
    if (picked.length >= N) break;
    if (!handednessSeen.has(c.handedness)) {
      picked.push(c);
      handednessSeen.add(c.handedness);
    }
  }
  // 슬롯 남으면 점수 순으로 나머지 채움 (같은 손잡이 중복 허용)
  for (const c of candidates) {
    if (picked.length >= N) break;
    if (!picked.includes(c)) picked.push(c);
  }

  // 포즈가 있으면 손잡이(handedness)를 포즈 손목 근접도로 재할당 — MediaPipe 가 가림 상황에서 잘못 라벨링하는 문제 보정
  if (hasPoseWrists) {
    picked.forEach(c => {
      const dL = _dist2D(c.landmarks[0], lw);
      const dR = _dist2D(c.landmarks[0], rw);
      c.handedness = dL < dR ? 'Left' : 'Right';
    });
  }

  return {
    landmarks: picked.map(c => c.landmarks),
    handedness: picked.map(c => [{ displayName: c.handedness, score: c.handednessScore }]),
  };
}

// ── 손 가림(occlusion) 예측 추적 ──────────────────────────────
// 사이드(Left/Right)별로 마지막 유효 landmark + 그 시점의 포즈 손목 위치를 기억.
// 다음 프레임에 손이 검출 안 되면 → 포즈 손목 이동량(Δ)으로 마지막 landmark 를 평행이동해 예측.
// HAND_PREDICT_MAX_MS 이내에서만 유지, 그 후엔 자연스럽게 폐기.
const handMemory = { Left: null, Right: null }; // {landmarks, ts, poseWrist:{x,y,z}}
function _predictMissingHands(detected, poseLandmarks, now) {
  const sides = ['Left', 'Right'];
  const wrists = { Left: poseLandmarks?.[15] ?? null, Right: poseLandmarks?.[16] ?? null };

  // 검출된 손은 메모리 업데이트 — 포즈 손목이 있을 때만 (없으면 예측 기준이 없음)
  const detectedSides = new Set();
  for (let i = 0; i < detected.landmarks.length; i++) {
    const side = detected.handedness[i]?.[0]?.displayName;
    if (!sides.includes(side)) continue;
    detectedSides.add(side);
    const wrist = wrists[side];
    if (!wrist) continue;
    handMemory[side] = {
      landmarks: detected.landmarks[i].map(p => ({ x: p.x, y: p.y, z: p.z, visibility: p.visibility, presence: p.presence })),
      ts: now,
      poseWrist: { x: wrist.x, y: wrist.y, z: wrist.z ?? 0 },
    };
  }

  // 검출 안 된 사이드는 메모리 + 현재 포즈 손목으로 예측 시도
  const augmentedLandmarks = [...detected.landmarks];
  const augmentedHandedness = [...detected.handedness];
  const predictedFlags = detected.landmarks.map(() => false);

  for (const side of sides) {
    if (detectedSides.has(side)) continue;
    const mem = handMemory[side];
    if (!mem) continue;
    if (now - mem.ts > CONFIG.HAND_PREDICT_MAX_MS) {
      handMemory[side] = null; // 만료 → 메모리 정리
      continue;
    }
    const wrist = wrists[side];
    if (!wrist) continue; // 포즈 손목이 없으면 평행이동 기준이 없음

    const dx = wrist.x - mem.poseWrist.x;
    const dy = wrist.y - mem.poseWrist.y;
    const dz = (wrist.z ?? 0) - mem.poseWrist.z;
    const shifted = mem.landmarks.map(p => ({
      x: p.x + dx, y: p.y + dy, z: p.z + dz,
      visibility: p.visibility, presence: p.presence,
    }));
    // 시간 경과에 따른 신뢰도 감쇠 (1.0 → 0)
    const ageRatio = (now - mem.ts) / CONFIG.HAND_PREDICT_MAX_MS;
    const score = Math.max(0, 1 - ageRatio) * 0.5; // 검출 손보다 명확히 낮게
    augmentedLandmarks.push(shifted);
    augmentedHandedness.push([{ displayName: side, score }]);
    predictedFlags.push(true);
  }

  return {
    landmarks: augmentedLandmarks,
    handedness: augmentedHandedness,
    predicted: predictedFlags,
  };
}

// ── 메인 처리 루프 ─────────────────────────────────────────────
async function processFrame(timestamp) {
  if (!isRunning) return;
  animationId = requestAnimationFrame(processFrame);

  if (timestamp - lastFrameTime < CONFIG.MIN_FRAME_INTERVAL_MS) return;
  if (videoEl.readyState < HTMLMediaElement.HAVE_ENOUGH_DATA) return;

  lastFrameTime = timestamp;

  // ① 포즈 감지 (PoseLandmarker) — 팔·어깨·몸통
  const poseResult = poseLandmarker.detectForVideo(videoEl, timestamp);
  // [P0] 백엔드 pose_analyzer 로 보낼 최신 스냅샷 캐싱
  latestPoseLandmarks = poseResult.landmarks?.[0] ?? null;
  window.dispatchEvent(new CustomEvent('itda:pose:results', {
    detail: { landmarks: latestPoseLandmarks },
  }));

  // ② 얼굴 감지 (FaceLandmarker)
  const faceResult = faceLandmarker.detectForVideo(videoEl, timestamp);
  if (faceResult.faceBlendshapes && faceResult.faceBlendshapes.length > 0) {
    const raw = faceResult.faceBlendshapes[0].categories;
    const smoothed = smoothBlendshapes(raw);

    window.dispatchEvent(new CustomEvent('itda:face:results', {
      detail: { blendshapes: smoothed },
    }));
  }

  // ② 손 감지 (HandLandmarker) — 후보 최대 4개
  const rawHandResult = handLandmarker.detectForVideo(videoEl, timestamp);
  // 포즈의 어깨·팔과 이어지고 카메라에 가까운 손 2개만 통과 — 사람 간 점프 방지
  const filteredHandResult = _pickPrimaryHands(rawHandResult, latestPoseLandmarks);
  // 가림(overlap)으로 한쪽 손이 빠지면 포즈 손목 기준으로 마지막 모양을 예측 — 0.5초 이내
  const handResult = _predictMissingHands(filteredHandResult, latestPoseLandmarks, timestamp);

  // ── 시각화 (Drawing) ── 필터링·예측된 손을 캔버스에 표시
  drawResults(faceResult, handResult, poseResult);

  if (handResult.landmarks && handResult.landmarks.length > 0) {
    const hands = handResult.landmarks.map((lm, i) => ({
      handedness: handResult.handedness[i]?.[0]?.displayName ?? 'Unknown',
      landmarks: lm,
    }));
    window.dispatchEvent(new CustomEvent('itda:hands:results', {
      detail: { hands },
    }));

    // 백엔드 파이프라인으로 실시간 전송
    sendFrameWS(hands);
  } else {
    sendFrameWS([]); // 빈 손일지라도 전송하여 상태 유지
  }

  // ③ FPS 계산
  updateFPS(timestamp);
}

// ── Cover-fit 좌표 변환 ──────────────────────────────────────
// 비디오가 object-fit:cover 로 컨테이너에 잘려 보일 때, 원본 비디오 좌표(0~1)를
// "실제 표시 영역" 기준 캔버스 좌표(0~1)로 매핑한다.
// 모바일 세로 화면에서 1280×720 비디오가 세로로 늘어나 보이던 손 관절 평탄화 문제를 해결.
function _coverFitTransform(srcW, srcH, dstW, dstH) {
  if (!srcW || !srcH || !dstW || !dstH) {
    return { scale: 1, offX: 0, offY: 0, dispW: dstW, dispH: dstH };
  }
  const scale = Math.max(dstW / srcW, dstH / srcH);
  const dispW = srcW * scale;
  const dispH = srcH * scale;
  return {
    scale,
    dispW,
    dispH,
    offX: (dstW - dispW) / 2,
    offY: (dstH - dispH) / 2,
  };
}

// 정규화 랜드마크 배열(원본 비디오 0~1)을 캔버스 표시 영역에 맞춘 0~1 좌표로 변환.
// DrawingUtils 가 normalized*canvas.width 로 그리므로, 변환 후 다시 정규화해서 넘긴다.
function _remapLandmarksToCanvas(landmarks, fit, canvW, canvH) {
  if (!landmarks) return landmarks;
  return landmarks.map(p => ({
    x: (fit.offX + p.x * fit.dispW) / canvW,
    y: (fit.offY + p.y * fit.dispH) / canvH,
    z: p.z,
    visibility: p.visibility,
    presence: p.presence,
  }));
}

/**
 * 전용 캔버스에 랜드마크 그리기
 */
function drawResults(faceResult, handResult, poseResult) {
  if (!canvasCtx || !drawingUtils) return;

  // 1. 캔버스 내부 좌표를 "표시 영역(CSS px)"에 맞춤.
  //    이전엔 비디오 원본 해상도(예: 1280×720)로 설정해서 세로 모바일에선
  //    CSS 스케일이 비균등(가로/세로 비율 차이)으로 일어나 랜드마크가 평탄/왜곡됐다.
  const cssW = canvasEl.clientWidth || canvasEl.width;
  const cssH = canvasEl.clientHeight || canvasEl.height;
  // DPR 보정으로 화면이 흐려지지 않게 (저사양 모바일은 2 까지만 사용)
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const targetW = Math.max(1, Math.round(cssW * dpr));
  const targetH = Math.max(1, Math.round(cssH * dpr));
  if (canvasEl.width !== targetW || canvasEl.height !== targetH) {
    canvasEl.width = targetW;
    canvasEl.height = targetH;
  }

  // 비디오 원본 → 캔버스(=표시 영역) 좌표 매핑 (object-fit:cover 보정)
  const fit = _coverFitTransform(
    videoEl.videoWidth,
    videoEl.videoHeight,
    canvasEl.width,
    canvasEl.height,
  );

  canvasCtx.save();
  canvasCtx.clearRect(0, 0, canvasEl.width, canvasEl.height);

  // 2. 얼굴 랜드마크 그리기
  if (faceResult.faceLandmarks) {
    for (const landmarks of faceResult.faceLandmarks) {
      const mapped = _remapLandmarksToCanvas(landmarks, fit, canvasEl.width, canvasEl.height);
      drawingUtils.drawConnectors(
        mapped,
        FACEMESH_TESSELATION,
        { color: "#C0C0C070", lineWidth: 1 }
      );
    }
  }

  // 3. 손 랜드마크 그리기 — 예측된 손은 시안색 반투명으로 구분 표시
  if (handResult.landmarks) {
    const predictedFlags = handResult.predicted || [];
    handResult.landmarks.forEach((landmarks, i) => {
      const isPredicted = predictedFlags[i] === true;
      const connColor = isPredicted ? "rgba(0, 242, 254, 0.55)" : "#FF00FF";
      const pointColor = isPredicted ? "rgba(0, 242, 254, 0.75)" : "#FF00FF";
      const mapped = _remapLandmarksToCanvas(landmarks, fit, canvasEl.width, canvasEl.height);
      // 외곽선 (글로우 효과)
      drawingUtils.drawConnectors(mapped, HAND_CONNECTIONS, {
        color: isPredicted ? "rgba(0, 0, 0, 0.25)" : "rgba(0, 0, 0, 0.5)",
        lineWidth: isPredicted ? 3 : 5,
      });
      // 실제/예측 관절 선
      drawingUtils.drawConnectors(mapped, HAND_CONNECTIONS, {
        color: connColor,
        lineWidth: isPredicted ? 1.5 : 2,
      });
      // 관절 포인트
      drawingUtils.drawLandmarks(mapped, {
        color: pointColor,
        lineWidth: 1,
        radius: (data) => {
          return data.from?.z ? DrawingUtils.lerp(data.from.z, -0.15, 0.1, 5, 1) : 3;
        }
      });
    });
  }
  // 4. 포즈 관절 점 (어깨=빨강, 팔꿈치=초록, 손목=파랑) — cover 보정된 좌표로 직접 그림
  if (poseResult?.landmarks?.[0]) {
    const lms = poseResult.landmarks[0];
    const JOINTS = [
      { idx: 11, color: '#FF6B6B', label: '어깨L' },
      { idx: 12, color: '#4488FF', label: '어깨R' },
      { idx: 13, color: '#FF9933', label: '팔꿈치L' },
      { idx: 14, color: '#44CCFF', label: '팔꿈치R' },
      { idx: 15, color: '#FFCC00', label: '손목L' },
      { idx: 16, color: '#44FFCC', label: '손목R' },
    ];
    const BONES = [[11, 13], [13, 15], [12, 14], [14, 16]];

    const toCanvas = (lm) => ({
      x: fit.offX + lm.x * fit.dispW,
      y: fit.offY + lm.y * fit.dispH,
    });

    canvasCtx.lineWidth = 2 * dpr;
    canvasCtx.strokeStyle = 'rgba(255,255,255,0.5)';
    for (const [a, b] of BONES) {
      const la = lms[a], lb = lms[b];
      if (!la || !lb || (la.visibility ?? 0) < 0.3 || (lb.visibility ?? 0) < 0.3) continue;
      const pa = toCanvas(la), pb = toCanvas(lb);
      canvasCtx.beginPath();
      canvasCtx.moveTo(pa.x, pa.y);
      canvasCtx.lineTo(pb.x, pb.y);
      canvasCtx.stroke();
    }

    for (const { idx, color, label } of JOINTS) {
      const lm = lms[idx];
      if (!lm || (lm.visibility ?? 0) < 0.3) continue;
      const { x, y } = toCanvas(lm);
      canvasCtx.beginPath();
      canvasCtx.arc(x, y, 7 * dpr, 0, Math.PI * 2);
      canvasCtx.fillStyle = color;
      canvasCtx.fill();
      canvasCtx.fillStyle = '#ffffff';
      canvasCtx.font = `bold ${11 * dpr}px monospace`;
      canvasCtx.fillText(label, x + 10 * dpr, y + 4 * dpr);
    }
  }

  canvasCtx.restore();
}

// ── Blendshape 스무딩 (Lerp α=0.35) ─────────────────────────
function smoothBlendshapes(raw) {
  return raw.map(({ categoryName, score }) => {
    const prev = blendBuffer[categoryName] ?? score;
    const smooth = prev + (score - prev) * 0.35;
    blendBuffer[categoryName] = smooth;
    return { categoryName, score: smooth };
  });
}

// ── FPS 이동 평균 ─────────────────────────────────────────────
function updateFPS(timestamp) {
  if (lastFpsSample > 0) {
    const fps = 1000 / (timestamp - lastFpsSample);
    fpsBuffer.push(fps);
    if (fpsBuffer.length > 10) fpsBuffer.shift();
    currentFPS = fpsBuffer.reduce((a, b) => a + b, 0) / fpsBuffer.length;
    window.dispatchEvent(new CustomEvent('itda:fps:update', { detail: { fps: currentFPS } }));
  }
  lastFpsSample = timestamp;
}

// ── 유틸 ──────────────────────────────────────────────────────
function setStatus(msg) {
  if (statusEl) statusEl.textContent = msg;
  console.info('[ITDA Vision]', msg);
}

// ── 공개 API ──────────────────────────────────────────────────
window.ITDAVision5 = {
  init,
  start: async () => {
    // isRunning 을 동기적으로 먼저 설정해 start() 중복 진입(이중 카메라/루프)을 막는다.
    if (isRunning) return;
    isRunning = true;
    try {
      await startCamera();
      setStatus('✅ 실행 중');
    } catch (err) {
      isRunning = false;
      console.error('[ITDA Vision] 카메라 시작 실패:', err);
      setStatus('❌ 카메라 시작 실패: ' + err.message);
    }
  },
  reconnect: () => {
    // 백엔드가 오프라인이었다가 복구된 경우 수동 재연결용
    wsRetryCount = 0;
    connectWebSocket();
  },
  stop: () => {
    isRunning = false;
    if (animationId) cancelAnimationFrame(animationId);
    if (videoStream) {
      videoStream.getTracks().forEach(t => t.stop());
      videoStream = null;
    }
    // 캔버스 잔상 제거
    if (canvasCtx && canvasEl) {
      canvasCtx.clearRect(0, 0, canvasEl.width, canvasEl.height);
    }
    setStatus('⏸️ 카메라 꺼짐');
  },
  isRunning: () => isRunning,
  switchCamera,
  getFacingMode: () => currentFacingMode,
};
