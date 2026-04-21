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

const HAND_CONNECTIONS = [[0, 1], [1, 2], [2, 3], [3, 4], [0, 5], [5, 6], [6, 7], [7, 8], [5, 9], [9, 10], [10, 11], [11, 12], [9, 13], [13, 14], [14, 15], [15, 16], [13, 17], [0, 17], [17, 18], [18, 19], [19, 20]];
// Simplified FaceMesh connections for performance
const FACEMESH_TESSELATION = [[10, 338], [338, 297], [297, 332], [332, 284], [284, 251], [251, 389], [389, 356], [356, 454], [454, 323], [323, 361], [361, 288], [288, 397], [397, 365], [365, 379], [379, 378], [378, 400], [400, 377], [377, 152], [152, 148], [148, 176], [176, 149], [149, 150], [150, 136], [136, 172], [172, 58], [58, 132], [132, 93], [93, 234], [234, 127], [127, 162], [162, 21], [21, 54], [54, 103], [103, 67], [67, 109], [109, 10]];

// ── 설정 ──────────────────────────────────────────────────────
const CONFIG = {
  MIN_FRAME_INTERVAL_MS: 33,        // ~30 fps
  FACE_DETECTION_CONFIDENCE: 0.6,
  FACE_TRACKING_CONFIDENCE:  0.5,
  HAND_DETECTION_CONFIDENCE: 0.7,
  HAND_TRACKING_CONFIDENCE:  0.6,
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
        delegate: 'GPU',
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
        delegate: 'GPU',
      },
      runningMode:    'VIDEO',
      numHands:       CONFIG.MAX_HANDS,
      minHandDetectionConfidence: CONFIG.HAND_DETECTION_CONFIDENCE,
      minHandPresenceConfidence:  0.5,
      minTrackingConfidence:      CONFIG.HAND_TRACKING_CONFIDENCE,
    });

    // ③ PoseLandmarker (팔·어깨·몸통 33개 관절)
    poseLandmarker = await PoseLandmarker.createFromOptions(vision, {
      baseOptions: {
        modelAssetPath: 'https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task',
        delegate: 'GPU',
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
    // connectWebSocket(); // [비활성화] 사용자 요청에 따라 백엔드 비전 소켓 연결 시도 원천 차단
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
const WS_URL = `ws://${location.hostname}:8000/api/ws/vision`;
let ws = null;
let sessionId = crypto.randomUUID();
let frameCounter = 0;
let lastSendTime = 0;
let currentFPS = 0;
let prevWristY = null; // 모션 변화량 추적을 위한 이전 손목 Y좌표

let wsRetryCount = 0;

function connectWebSocket() {
  if (ws && ws.readyState === WebSocket.OPEN) return;
  ws = new WebSocket(WS_URL);
  ws.onopen = () => {
    console.info("[ITDA WebSocket] 백엔드 RAG 연동 완료");
    wsRetryCount = 0;
  };
  ws.onmessage = (evt) => {
    try {
      const ack = JSON.parse(evt.data);
      if (ack.rag_result) {
        window.dispatchEvent(new CustomEvent('itda:rag:result', { detail: ack }));
      }
    } catch(e) {}
  };
  ws.onclose = () => {
    if (wsRetryCount < 3) {
      console.warn(`[ITDA] 백엔드 연결 실패. 재연결 시도 중... (${wsRetryCount + 1}/3)`);
      wsRetryCount++;
      setTimeout(connectWebSocket, 2000);
    } else if (wsRetryCount === 3) {
      console.info("💡 [ITDA] 백엔드(8000) 서버 오프라인으로 확인됨. 단독 모드로 전환합니다.");
      wsRetryCount++;
    }
  };
}

function sendFrameWS(hands) {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  const now = performance.now();
  
  // [과제 3] 0.5초(500ms) 단위로 버퍼링/제한 (기존 33fps 무한 호출 방지)
  if (now - lastSendTime < 500) return; 
  lastSendTime = now;

  const ESSENTIAL_INDICES = [0, 3, 4, 6, 8, 10, 12, 14, 16, 18, 20];
  const handDataList = hands.map(h => {
    const keypoints = ESSENTIAL_INDICES.map(idx => {
       const lm = h.landmarks[idx];
       return { x: +(lm.x).toFixed(4), y: +(lm.y).toFixed(4), z: +(lm.z).toFixed(4) };
    });
    return { handedness: h.handedness, keypoints: keypoints };
  });

  // [과제 1] 원시 좌표(x,y,z) 대신 백엔드가 이해하기 쉬운 메타데이터 추출
  let movement_desc = "정지 상태";
  if (hands.length > 0) {
    const currentWristY = hands[0].landmarks[0].y; // 0은 맨 위(이마쪽), 1은 맨 아래(가슴쪽)
    if (prevWristY !== null) {
      const deltaY = currentWristY - prevWristY;
      if (deltaY > 0.05) {
        movement_desc = "손목이 위에서 아래로 부드럽게 내려옵니다."; // 예: 감사합니다 등
      } else if (deltaY < -0.05) {
        movement_desc = "손목이 아래에서 위로 올라갑니다.";
      }
    }
    prevWristY = currentWristY;
  } else {
    prevWristY = null;
  }

  ws.send(JSON.stringify({
    frame_id: frameCounter++,
    session_id: sessionId,
    timestamp_ms: now,
    fps: currentFPS,
    hands: handDataList,
    meta_features: {               // 백엔드로 보낼 정제된 특징
      movement: movement_desc,
      hand_count: hands.length
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
  window.dispatchEvent(new CustomEvent('itda:pose:results', {
    detail: { landmarks: poseResult.landmarks?.[0] ?? null },
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
      // 외곽선 (두껍게)
      drawingUtils.drawConnectors(landmarks, HAND_CONNECTIONS, {
        color: "#000000",
        lineWidth: 4
      });
      // 실제 선 (조금 더 얇게)
      drawingUtils.drawConnectors(landmarks, HAND_CONNECTIONS, {
        color: "#00F2FE",
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
