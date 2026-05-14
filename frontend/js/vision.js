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
  FACE_TRACKING_CONFIDENCE:  0.5,
  HAND_DETECTION_CONFIDENCE: 0.3,   // 감지 문턱값 하향 (빠른 움직임 대응)
  HAND_TRACKING_CONFIDENCE:  0.3,
  MAX_HANDS: 2,
};

// ── 내부 상태 ─────────────────────────────────────────────────
let faceLandmarker   = null;
let handLandmarker   = null;
let poseLandmarker   = null;
let videoStream      = null;
let animationId      = null;
let lastFrameTime    = 0;
let lastFpsSample    = 0;
let fpsBuffer        = [];
let isRunning        = false;

const videoEl   = document.getElementById('vision-video');
const canvasEl  = document.getElementById('vision-canvas');
const statusEl  = document.getElementById('vision-status');
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
      runningMode:           'VIDEO',
      numFaces:              1,
      minFaceDetectionConfidence: CONFIG.FACE_DETECTION_CONFIDENCE,
      minTrackingConfidence:      CONFIG.FACE_TRACKING_CONFIDENCE,
    });

    // ② HandLandmarker
    handLandmarker = await HandLandmarker.createFromOptions(vision, {
      baseOptions: {
        modelAssetPath: 'https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task',
        delegate: 'GPU', // CPU -> GPU 가속
      },
      runningMode:    'VIDEO',
      numHands:       CONFIG.MAX_HANDS,
      minHandDetectionConfidence: CONFIG.HAND_DETECTION_CONFIDENCE,
      minHandPresenceConfidence:  0.5,
      minTrackingConfidence:      CONFIG.HAND_TRACKING_CONFIDENCE,
    });

    // ③ PoseLandmarker (팔·어깨·몸통 33개 관절) - 교차/겹침 상황 정확도 향상을 위해 full 모델 사용
    poseLandmarker = await PoseLandmarker.createFromOptions(vision, {
      baseOptions: {
        modelAssetPath: 'https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task',
        delegate: 'GPU', // full -> lite 모델로 경량화 및 GPU 가속
      },
      runningMode:  'VIDEO',
      numPoses:     1,
      minPoseDetectionConfidence: 0.5,
      minPosePresenceConfidence:  0.5,
      minTrackingConfidence:      0.5,
      outputSegmentationMasks:    false,
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
async function startCamera() {
  videoStream = await navigator.mediaDevices.getUserMedia({
    video: { width: { ideal: 1280 }, height: { ideal: 720 }, frameRate: { ideal: 60 } },
    audio: false,
  });
  videoEl.srcObject = videoStream;
  await new Promise(res => { videoEl.onloadedmetadata = res; });
  videoEl.play();
  isRunning = true;
  requestAnimationFrame(processFrame);
}

// ── WebSocket 연동 상태 ───────────────────────────────────────
const WS_URL = `ws://127.0.0.1:8000/api/ws/vision`; // localhost 대신 127.0.0.1 사용하여 IPv6/IPv4 혼선 방지
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
  left_shoulder: 11,  right_shoulder: 12,
  left_elbow: 13,     right_elbow: 14,
  left_wrist: 15,     right_wrist: 16,
  left_hip: 23,       right_hip: 24,
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
    } catch(e) {}
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
    if (wsRetryCount < 3) {
      console.warn(`[ITDA] 백엔드 연결 실패 (코드: ${evt.code}). 재연결 시도 중... (${wsRetryCount + 1}/3)`);
      wsRetryCount++;
      setTimeout(connectWebSocket, 2000);
      window.dispatchEvent(new CustomEvent('itda:vision:ws_state', { detail: { state: 'connecting' } }));
    } else if (wsRetryCount === 3) {
      console.info("💡 [ITDA] 백엔드(8000) 서버 오프라인으로 확인됨. 단독 모드로 전환합니다.");
      wsRetryCount++;
    }
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

  // ② 손 감지 (HandLandmarker)
  const handResult = handLandmarker.detectForVideo(videoEl, timestamp);
  
  // ── 시각화 (Drawing) ──
  drawResults(faceResult, handResult, poseResult);

  if (handResult.landmarks && handResult.landmarks.length > 0) {
    const hands = handResult.landmarks.map((lm, i) => ({
      handedness: handResult.handedness[i]?.[0]?.displayName ?? 'Unknown',
      landmarks:  lm,
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

/**
 * 전용 캔버스에 랜드마크 그리기
 */
function drawResults(faceResult, handResult, poseResult) {
  if (!canvasCtx || !drawingUtils) return;

  // 1. 캔버스 크기 동기화
  if (canvasEl.width !== videoEl.videoWidth) {
    canvasEl.width = videoEl.videoWidth;
    canvasEl.height = videoEl.videoHeight;
  }

  canvasCtx.save();
  canvasCtx.clearRect(0, 0, canvasEl.width, canvasEl.height);

  // 2. 얼굴 랜드마크 그리기
  if (faceResult.faceLandmarks) {
    for (const landmarks of faceResult.faceLandmarks) {
      drawingUtils.drawConnectors(
        landmarks,
        FACEMESH_TESSELATION,
        { color: "#C0C0C070", lineWidth: 1 }
      );
    }
  }

  // 3. 손 랜드마크 그리기
  if (handResult.landmarks) {
    for (const landmarks of handResult.landmarks) {
      // 외곽선 (글로우 효과를 위한 어두운 배경)
      drawingUtils.drawConnectors(landmarks, HAND_CONNECTIONS, {
        color: "rgba(0, 0, 0, 0.5)",
        lineWidth: 5
      });
      // 실제 관절 선 (네온 느낌의 마젠타/핑크)
      drawingUtils.drawConnectors(landmarks, HAND_CONNECTIONS, {
        color: "#FF00FF",
        lineWidth: 2
      });
      // 관절 포인트
      drawingUtils.drawLandmarks(landmarks, {
        color: "#FF00FF",
        lineWidth: 1,
        radius: (data) => {
          return data.from?.z ? DrawingUtils.lerp(data.from.z, -0.15, 0.1, 5, 1) : 3;
        }
      });
    }
  }
  // 4. 포즈 관절 점 (어깨=빨강, 팔꿈치=초록, 손목=파랑)
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
    const BONES = [[11,13],[13,15],[12,14],[14,16]];

    canvasCtx.lineWidth = 2;
    canvasCtx.strokeStyle = 'rgba(255,255,255,0.5)';
    for (const [a, b] of BONES) {
      const la = lms[a], lb = lms[b];
      if (!la || !lb || (la.visibility ?? 0) < 0.3 || (lb.visibility ?? 0) < 0.3) continue;
      canvasCtx.beginPath();
      canvasCtx.moveTo(la.x * canvasEl.width, la.y * canvasEl.height);
      canvasCtx.lineTo(lb.x * canvasEl.width, lb.y * canvasEl.height);
      canvasCtx.stroke();
    }

    for (const { idx, color, label } of JOINTS) {
      const lm = lms[idx];
      if (!lm || (lm.visibility ?? 0) < 0.3) continue;
      const x = lm.x * canvasEl.width;
      const y = lm.y * canvasEl.height;
      canvasCtx.beginPath();
      canvasCtx.arc(x, y, 7, 0, Math.PI * 2);
      canvasCtx.fillStyle = color;
      canvasCtx.fill();
      canvasCtx.fillStyle = '#ffffff';
      canvasCtx.font = 'bold 11px monospace';
      canvasCtx.fillText(label, x + 10, y + 4);
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
  stop: () => {
    isRunning = false;
    if (animationId) cancelAnimationFrame(animationId);
    if (videoStream) videoStream.getTracks().forEach(t => t.stop());
  },
};
