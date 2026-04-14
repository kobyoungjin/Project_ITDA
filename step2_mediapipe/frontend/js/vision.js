/**
 * vision.js - MediaPipe 기반 수어 관절 추출·정규화·전송 모듈
 *
 * ■ 핵심 기능
 *   1. MediaPipe Hands로 21개 관절 추출
 *   2. 수어 필수 11개 관절만 필터링
 *   3. JSON 정규화·소수점 압축 후 WebSocket 전송
 *   4. 30fps 이상 유지 최적화
 *
 * ■ 30fps 최적화 전략
 *   - requestAnimationFrame 사용 (브라우저 렌더링 루프에 최적화)
 *   - 전송 간격 제어: 최소 30ms(약 33fps) 보장, 최대 60fps 허용
 *   - 데이터 압축: 11개 관절만 전송 + 소수점 4자리 반올림
 *   - 비파괴 복사 없이 직접 처리 (GC 부하 최소화)
 */

// ─── 설정 상수 ────────────────────────────────────────────────
const CONFIG = {
  // 수어 필수 관절 인덱스 (MediaPipe 21개 중 11개 선택)
  //  0: WRIST        3: INDEX_MCP    4: INDEX_TIP
  //  6: MIDDLE_MCP   8: MIDDLE_TIP  10: RING_MCP
  // 12: RING_TIP    14: PINKY_MCP  16: PINKY_TIP
  // 18: THUMB_MCP   20: THUMB_TIP
  ESSENTIAL_INDICES: [0, 3, 4, 6, 8, 10, 12, 14, 16, 18, 20],

  // WebSocket 서버 주소 (2단계 독립 실행 시 8001, 1단계 통합 시 1단계 포트로 변경)
  WS_URL: `ws://${location.hostname}:${location.port || 8001}/ws/vision`,

  // 좌표 소수점 자리수 (4자리: JSON 크기 최소화)
  PRECISION: 4,

  // 프레임 전송 최소 간격 (ms) - 30fps = 33ms
  MIN_SEND_INTERVAL_MS: 33,

  // WebSocket 재연결 대기 시간 (ms)
  WS_RECONNECT_DELAY_MS: 2000,

  // MediaPipe 신뢰도 임계값 (낮은 식별 정확도 프레임 무시)
  DETECTION_CONFIDENCE: 0.7,
  TRACKING_CONFIDENCE: 0.6,
};

// ─── 관절 이름 매핑 (디버깅용) ───────────────────────────────
const LANDMARK_NAMES = {
  0: "WRIST", 3: "INDEX_MCP", 4: "INDEX_TIP",
  6: "MIDDLE_MCP", 8: "MIDDLE_TIP", 10: "RING_MCP",
  12: "RING_TIP", 14: "PINKY_MCP", 16: "PINKY_TIP",
  18: "THUMB_MCP", 20: "THUMB_TIP",
};

// ─── 상태 변수 ───────────────────────────────────────────────
let ws = null;
let isStreaming = false;
let sessionId = crypto.randomUUID();
let frameCounter = 0;
let lastSendTime = 0;
let lastFrameTime = 0;
let currentFPS = 0;
let fpsBuffer = [];        // FPS 이동평균 계산용 (10프레임)
let lastHandResults = null; // MediaPipe 최신 결과 캐시

// ─── 세션 ID 전역 노출 (index.html 접근용) ──────────────────
window.itdaSessionId = sessionId;

/**
 * MediaPipe 21개 → 핵심 11개 관절 필터링 및 정규화
 *
 * @param {Array} landmarks - MediaPipe NormalizedLandmarkList
 * @param {string} handedness - 'Left' | 'Right'
 * @returns {Object} - HandKeypoints 스키마 호환 객체
 */
function extractKeypoints(landmarks, handedness) {
  const keypoints = CONFIG.ESSENTIAL_INDICES.map((idx) => {
    const lm = landmarks[idx];
    return {
      x: +lm.x.toFixed(CONFIG.PRECISION),
      y: +lm.y.toFixed(CONFIG.PRECISION),
      z: +lm.z.toFixed(CONFIG.PRECISION),
    };
  });

  return {
    handedness,
    keypoints,
    // full_landmarks: null  // 학습 데이터 수집 시 아래로 교체
    // full_landmarks: landmarks.map(lm => ({
    //   x: +lm.x.toFixed(CONFIG.PRECISION),
    //   y: +lm.y.toFixed(CONFIG.PRECISION),
    //   z: +lm.z.toFixed(CONFIG.PRECISION),
    // })),
  };
}

/**
 * VisionFrame 페이로드 생성 (schema.py의 VisionFrame과 1:1 대응)
 *
 * @param {Array} handDataList - extractKeypoints() 결과 배열
 * @returns {Object} - VisionFrame JSON
 */
function buildFrame(handDataList) {
  return {
    frame_id: frameCounter++,
    session_id: sessionId,
    timestamp_ms: performance.now(),
    fps: currentFPS,
    hands: handDataList,
  };
}

/**
 * WebSocket 전송
 * - MIN_SEND_INTERVAL_MS 미만 간격이면 스킵 (30fps 제어)
 * - 연결 안 됐으면 즉시 반환 (논블로킹)
 */
function sendFrame(handDataList) {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;

  const now = performance.now();
  if (now - lastSendTime < CONFIG.MIN_SEND_INTERVAL_MS) return;
  lastSendTime = now;

  const payload = JSON.stringify(buildFrame(handDataList));
  ws.send(payload);
}

/**
 * FPS 계산 (10프레임 이동평균)
 */
function updateFPS() {
  const now = performance.now();
  if (lastFrameTime > 0) {
    const delta = now - lastFrameTime;
    fpsBuffer.push(1000 / delta);
    if (fpsBuffer.length > 10) fpsBuffer.shift();
    currentFPS = fpsBuffer.reduce((a, b) => a + b, 0) / fpsBuffer.length;
  }
  lastFrameTime = now;
}

// ─── WebSocket 연결 관리 ──────────────────────────────────────

/**
 * WebSocket 연결 시작
 * 연결 해제 시 WS_RECONNECT_DELAY_MS 후 자동 재연결
 */
function connectWebSocket() {
  if (ws && ws.readyState === WebSocket.OPEN) return;

  ws = new WebSocket(CONFIG.WS_URL);

  ws.onopen = () => {
    console.info("[ITDA Vision] WebSocket 연결됨:", CONFIG.WS_URL);
    window.dispatchEvent(new CustomEvent("itda:ws:open"));
  };

  ws.onmessage = (evt) => {
    try {
      const ack = JSON.parse(evt.data);
      // RAG 결과가 있을 경우 이벤트 발행 (overlay.js 또는 앱에서 수신)
      if (ack.rag_result) {
        window.dispatchEvent(new CustomEvent("itda:rag:result", { detail: ack }));
      }
    } catch (e) {
      console.warn("[ITDA Vision] ACK 파싱 오류:", e);
    }
  };

  ws.onerror = (err) => {
    console.error("[ITDA Vision] WebSocket 오류:", err);
  };

  ws.onclose = () => {
    console.warn("[ITDA Vision] WebSocket 연결 종료. 재연결 대기...");
    window.dispatchEvent(new CustomEvent("itda:ws:close"));
    if (isStreaming) {
      setTimeout(connectWebSocket, CONFIG.WS_RECONNECT_DELAY_MS);
    }
  };
}

function disconnectWebSocket() {
  if (ws) {
    ws.onclose = null; // 재연결 방지
    ws.close();
    ws = null;
  }
}

// ─── MediaPipe 핸들러 ─────────────────────────────────────────

/**
 * MediaPipe Hands 결과 콜백
 * index.html 에서 hands.onResults(onHandsResults) 로 등록
 *
 * @param {Object} results - MediaPipe Hands 결과 객체
 */
function onHandsResults(results) {
  updateFPS();

  // 결과 캐시 저장 (overlay.js에서 접근)
  lastHandResults = results;
  window.itdaLastResults = results;

  // 스트리밍 중이 아니면 추출만 하고 전송은 하지 않음
  if (!isStreaming) return;

  const handDataList = [];

  if (results.multiHandLandmarks && results.multiHandLandmarks.length > 0) {
    for (let i = 0; i < results.multiHandLandmarks.length; i++) {
      const landmarks  = results.multiHandLandmarks[i];
      const handedness = results.multiHandedness?.[i]?.label ?? "Unknown";
      handDataList.push(extractKeypoints(landmarks, handedness));
    }
  }

  // 손이 없어도 빈 배열로 프레임 전송 (서버가 "손 없음" 상태 추적 가능)
  sendFrame(handDataList);

  // FPS 이벤트 발행 (UI 업데이트용)
  window.dispatchEvent(new CustomEvent("itda:fps:update", {
    detail: { fps: currentFPS }
  }));
}

// ─── 공개 API ─────────────────────────────────────────────────

/**
 * 스트리밍 시작
 * - WebSocket 연결 → 좌표 전송 루프 활성화
 */
function startStreaming() {
  isStreaming = true;
  connectWebSocket();
  console.info("[ITDA Vision] 스트리밍 시작. session:", sessionId);
}

/**
 * 스트리밍 중지
 */
function stopStreaming() {
  isStreaming = false;
  disconnectWebSocket();
  fpsBuffer = [];
  currentFPS = 0;
  console.info("[ITDA Vision] 스트리밍 중지.");
}

/**
 * 현재 추출 설정 반환 (디버깅·테스트용)
 */
function getConfig() {
  return {
    ...CONFIG,
    sessionId,
    isStreaming,
    currentFPS: currentFPS.toFixed(1),
    landmarkNames: LANDMARK_NAMES,
  };
}

// ─── 전역 노출 ────────────────────────────────────────────────
window.ITDAVision = {
  startStreaming,
  stopStreaming,
  onHandsResults,   // index.html에서 MediaPipe에 바인딩
  getConfig,
  CONFIG,
};
