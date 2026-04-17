/**
 * vision.js  ─  Step 5: 얼굴 + 손 + 포즈 통합 비전 엔진
 *
 * ■ 역할
 *   1. MediaPipe Hands (21 관절) → 손동작 데이터 추출
 *   2. MediaPipe FaceLandmarker (52 Blendshapes) → 얼굴 표정 데이터 추출
 *   3. MediaPipe PoseLandmarker (33 관절) → 어깨/팔꿈치/손목 실제 포즈 추출
 *   4. 하나의 웹캠 스트림으로 세 모델을 병렬 처리 (requestAnimationFrame 루프)
 *   5. 커스텀 이벤트를 발행하여 avatar.js / retargeting.js 가 구독
 *
 * ■ 발행 이벤트
 *   - itda:hands:results  → { hands: HandResult[] }
 *   - itda:face:results   → { blendshapes: Blendshape[] }
 *   - itda:pose:results   → { landmarks: PoseLandmark[] }
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

// [Cyborg Alpha] 포즈 디버그용 연결선 (어깨, 팔꿈치, 손목 위주)
const POSE_CONNECTIONS = [
  [11, 12], // 어깨-어깨
  [11, 13], [13, 15], // 왼팔
  [12, 14], [14, 16], // 오른팔
  [11, 23], [12, 24], [23, 24] // 상체 윤곽
];

// ── 설정 ──────────────────────────────────────────────────────
const CONFIG = {
  MIN_FRAME_INTERVAL_MS: 33,        // ~30 fps
  FACE_DETECTION_CONFIDENCE: 0.6,
  FACE_TRACKING_CONFIDENCE: 0.5,
  HAND_DETECTION_CONFIDENCE: 0.7,
  HAND_TRACKING_CONFIDENCE: 0.6,
  POSE_VISIBILITY_THRESHOLD: 0.15,    // [Cyborg Alpha] 더 민감하게 인식 (0.5 -> 0.15)
  MAX_HANDS: 2,
};

// ── 내부 상태 ─────────────────────────────────────────────────
let faceLandmarker = null;
let handLandmarker = null;
let poseLandmarker = null;
let poseResults = null; // 시각화용 최신 포즈 데이터 저장
let videoStream = null;
let animationId = null;
let lastFrameTime = 0;
let lastFpsSample = 0;
let fpsBuffer = [];
let isRunning = false;

const videoEl  = document.getElementById('vision-video');
const canvasEl  = document.getElementById('vision-canvas');
const statusEl  = document.getElementById('vision-status');
// canvasCtx는 init() 안에서 canvasEl 존재 확인 후 생성
let canvasCtx   = null;
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
      runningMode: 'VIDEO',
      numFaces: 1,
      minFaceDetectionConfidence: CONFIG.FACE_DETECTION_CONFIDENCE,
      minTrackingConfidence: CONFIG.FACE_TRACKING_CONFIDENCE,
    });

    // ② HandLandmarker
    handLandmarker = await HandLandmarker.createFromOptions(vision, {
      baseOptions: {
        modelAssetPath: 'https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task',
        delegate: 'GPU',
      },
      runningMode: 'VIDEO',
      numHands: CONFIG.MAX_HANDS,
      minHandDetectionConfidence: CONFIG.HAND_DETECTION_CONFIDENCE,
      minHandPresenceConfidence: 0.5,
      minTrackingConfidence: CONFIG.HAND_TRACKING_CONFIDENCE,
    });

    // ③ PoseLandmarker (어깨·팔꿈치·손목 실제 인식)
    setStatus('포즈 모델 로딩 중…');
    poseLandmarker = await PoseLandmarker.createFromOptions(vision, {
      baseOptions: {
        modelAssetPath: 'https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task',
        delegate: 'GPU',
      },
      runningMode: 'VIDEO',
      numPoses: 1,
      minPoseDetectionConfidence: 0.5,
      minTrackingConfidence: 0.5,
    });
    console.info('[ITDA Vision] ✅ PoseLandmarker 로드 완료');

    setStatus('카메라 연결 중…');
    await startCamera();

    // canvasEl 존재 확인 후 안전하게 2D 컨텍스트 초기화
    if (canvasEl) {
      canvasCtx   = canvasEl.getContext('2d');
      drawingUtils = new DrawingUtils(canvasCtx);
    } else {
      console.warn('[ITDA Vision] #vision-canvas 요소를 찾을 수 없어 랜드마크 그리기를 건너뜁니다.');
    }

    setStatus('✅ 실행 중');
    connectWebSocket(); // 백엔드 RAG 엔진 연동 개시
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
let prevWristY = null;

function connectWebSocket() {
  if (ws && ws.readyState === WebSocket.OPEN) return;
  ws = new WebSocket(WS_URL);
  ws.onopen = () => console.info("[ITDA WebSocket] 백엔드 RAG 연동 완료");
  ws.onmessage = (evt) => {
    try {
      const ack = JSON.parse(evt.data);
      if (ack.rag_result) {
        window.dispatchEvent(new CustomEvent('itda:rag:result', { detail: ack }));
      }
    } catch (e) { }
  };
  ws.onclose = () => {
    console.warn("WS 재연결 시도 중...");
    setTimeout(connectWebSocket, 2000);
  };
}

function sendFrameWS(hands) {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  const now = performance.now();

  // 500ms(0.5초) 단위 버퍼링 (무한 호출 방지)
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

  // 원시 좌표 대신 백엔드가 이해하기 쉬운 메타데이터 추출
  let movement_desc = "정지 상태";
  if (hands.length > 0) {
    const currentWristY = hands[0].landmarks[0].y;
    if (prevWristY !== null) {
      const deltaY = currentWristY - prevWristY;
      if (deltaY > 0.05) {
        movement_desc = "손목이 위에서 아래로 내려옵니다.";
      } else if (deltaY < -0.05) {
        movement_desc = "손목이 아래에서 위로 올라갑니다.";
      }
    }
    prevWristY = currentWristY;
  } else {
    prevWristY = null;
  }

  // [Cyborg Alpha] 센서 퓨전 데이터 시뮬레이션 (YOLO v11 + SED)
  // 실제 연동 시에는 외부 API에서 받은 값으로 교체
  const visual_conf = hands.length > 0 ? 0.92 : 0.4;
  const audio_conf = Math.random() * 0.5 + 0.3; // 0.3 ~ 0.8 사이 랜덤
  const detected_area = hands.length > 0 ? 1.25 : 0.0;

  ws.send(JSON.stringify({
    frame_id: frameCounter++,
    session_id: sessionId,
    timestamp_ms: now,
    fps: currentFPS,
    hands: handDataList,
    detection_data: {
      visual_confidence: visual_conf,
      audio_confidence: audio_conf,
      detected_area_m2: detected_area
    },
    meta_features: {
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

  // ① 얼굴 감지 (FaceLandmarker)
  const faceResult = faceLandmarker.detectForVideo(videoEl, timestamp);
  processFaceResults(faceResult);

  // ② 손 감지 (HandLandmarker)
  const handResult = handLandmarker.detectForVideo(videoEl, timestamp);

  // ③ 포즈 감지 (PoseLandmarker) — 어깨·팔꿈치·손목 실측
  if (poseLandmarker) {
    poseResults = poseLandmarker.detectForVideo(videoEl, timestamp);
    processPoseResults(poseResults);
  }

  // ── 시각화 (Drawing) ──
  drawResults(faceResult, handResult, poseResults);

  processHandResults(handResult);

  // ④ FPS 계산
  updateFPS(timestamp);
}

function processFaceResults(results) {
  if (results.faceBlendshapes && results.faceBlendshapes.length > 0) {
    const blendshapes = results.faceBlendshapes[0].categories;

    // [Cyborg Alpha] 52종 전송 (필터링 없이 전체 싱크)
    window.dispatchEvent(new CustomEvent('itda:face:results', {
      detail: { blendshapes: blendshapes }
    }));
  }
}

function processHandResults(results) {
  const hands = [];
  if (results.landmarks && results.landmarks.length > 0) {
    for (let i = 0; i < results.landmarks.length; i++) {
      const handedness = results.handednesses[i][0].categoryName; // 'Left' or 'Right'
      const landmarks = results.landmarks[i];

      hands.push({
        handedness: handedness,
        landmarks: landmarks // 21개 랜드마크 전체
      });
    }
  } else {
    // [Cyborg Alpha] 손이 감지되지 않으면 빈 배열을 발행하여 중립 복귀 유도
  }

  window.dispatchEvent(new CustomEvent('itda:hands:results', {
    detail: { hands: hands }
  }));

  // 백엔드 전송 (연결된 경우에만)
  sendFrameWS(hands);
}

/**
 * 포즈 결과 처리 — 33개 포즈 랜드마크를 이벤트로 발행
 * 핵심 인덱스: 11=왼쪽어깨, 12=오른쪽어깨, 13=왼쪽팔꿈치, 14=오른쪽팔꿈치,
 *            15=왼쪽손목, 16=오른쪽손목, 23=왼쪽엉덩이, 24=오른쪽엉덩이
 */
function processPoseResults(results) {
  if (!results.landmarks || results.landmarks.length === 0) {
    // 사람이 감지되지 않으면 null 전송하여 중립 복귀 유도
    window.dispatchEvent(new CustomEvent('itda:pose:results', { detail: { landmarks: null } }));
    return;
  }

  const poseLandmarks = results.landmarks[0]; // 첫 번째 사람

  // [Cyborg Alpha] 가시성 체크: 핵심 관절(어깨, 팔꿈치, 손목)의 평균 가시성 확인
  const coreIndices = [11, 12, 13, 14, 15, 16];
  const avgVisibility = coreIndices.reduce((sum, idx) => sum + (poseLandmarks[idx]?.visibility || 0), 0) / coreIndices.length;

  if (avgVisibility < CONFIG.POSE_VISIBILITY_THRESHOLD) {
    window.dispatchEvent(new CustomEvent('itda:pose:results', { detail: { landmarks: null } }));
    return;
  }

  window.dispatchEvent(new CustomEvent('itda:pose:results', {
    detail: { landmarks: poseLandmarks }
  }));
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

  // 4. [Cyborg Alpha] 포즈 랜드마크 그리기 (디버그용)
  if (poseResult && poseResult.landmarks && poseResult.landmarks.length > 0) {
    const landmarks = poseResult.landmarks[0];
    
    // 핵심 연결선 (골드)
    drawingUtils.drawConnectors(landmarks, POSE_CONNECTIONS, {
      color: "#FFD700",
      lineWidth: 2
    });

    // 어깨, 팔꿈치, 손목 포인트 (그린)
    const debugIndices = [11, 12, 13, 14, 15, 16];
    const debugPoints = debugIndices.map(i => landmarks[i]).filter(p => p && p.visibility > 0.5);
    drawingUtils.drawLandmarks(debugPoints, { color: "#00FF00", lineWidth: 2, radius: 4 });
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
