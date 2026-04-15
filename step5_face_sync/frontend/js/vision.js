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

    setStatus('카메라 연결 중…');
    await startCamera();
    
    // Initialize DrawingUtils
    drawingUtils = new DrawingUtils(canvasCtx);
    
    setStatus('✅ 실행 중');
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

// ── 메인 처리 루프 ─────────────────────────────────────────────
async function processFrame(timestamp) {
  if (!isRunning) return;
  animationId = requestAnimationFrame(processFrame);

  if (timestamp - lastFrameTime < CONFIG.MIN_FRAME_INTERVAL_MS) return;
  if (videoEl.readyState < HTMLMediaElement.HAVE_ENOUGH_DATA) return;

  lastFrameTime = timestamp;

  // ① 얼굴 감지 (FaceLandmarker)
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
  drawResults(faceResult, handResult);

  if (handResult.landmarks && handResult.landmarks.length > 0) {
    const hands = handResult.landmarks.map((lm, i) => ({
      handedness: handResult.handedness[i]?.[0]?.displayName ?? 'Unknown',
      landmarks:  lm,
    }));
    window.dispatchEvent(new CustomEvent('itda:hands:results', {
      detail: { hands },
    }));
  }

  // ③ FPS 계산
  updateFPS(timestamp);
}

/**
 * 전용 캔버스에 랜드마크 그리기
 */
function drawResults(faceResult, handResult) {
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
    const avg = fpsBuffer.reduce((a, b) => a + b, 0) / fpsBuffer.length;
    window.dispatchEvent(new CustomEvent('itda:fps:update', { detail: { fps: avg } }));
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
