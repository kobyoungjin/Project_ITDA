/**
 * overlay.js - 수어 관절 시각화 오버레이 모듈
 *
 * ■ 기능
 *   - MediaPipe 원본 21개 연결선 (회색)
 *   - 핵심 11개 관절 강조 점 (컬러)
 *   - 손목 → 손가락 끝까지의 핵심 경로 강조 (녹색)
 *   - FPS + 실시간 좌표 디버그 패널
 *
 * ■ 성능 고려
 *   - canvas 2D API 사용 (WebGL 없이도 60fps 가능)
 *   - 필요 없으면 window.ITDAOverlay.disable() 호출
 */

// ─── 색상 팔레트 ──────────────────────────────────────────────
const COLORS = {
  connection:  "rgba(150,150,150,0.5)",  // 전체 연결선 (회색 반투명)
  essential:   "#00FFB3",                // 핵심 11개 관절 점 (민트)
  essential_r: "#FF6B6B",                // 오른손 핵심 관절 (코랄)
  path:        "rgba(0,255,179,0.7)",    // 핵심 경로 선 (민트)
  thumb:       "#FFD93D",                // 엄지 (노랑)
  text_bg:     "rgba(0,0,0,0.6)",
  text_fg:     "#FFFFFF",
  fps_ok:      "#00FFB3",               // FPS ≥ 30 (초록)
  fps_warn:    "#FFD93D",               // FPS 15~30 (노랑)
  fps_bad:     "#FF6B6B",               // FPS < 15 (빨강)
};

// MediaPipe Hands 연결 쌍 (인덱스 기준)
const HAND_CONNECTIONS = [
  [0,1],[1,2],[2,3],[3,4],      // 엄지
  [0,5],[5,6],[6,7],[7,8],      // 검지
  [0,9],[9,10],[10,11],[11,12], // 중지
  [0,13],[13,14],[14,15],[15,16],// 약지
  [0,17],[17,18],[18,19],[19,20],// 새끼
  [5,9],[9,13],[13,17],         // 손바닥 연결
];

// 핵심 관절 세트 (빠른 조회)
const ESSENTIAL_SET = new Set([0, 3, 4, 6, 8, 10, 12, 14, 16, 18, 20]);

let canvas = null;
let ctx = null;
let enabled = true;

/**
 * 초기화
 * @param {HTMLCanvasElement} canvasEl - 오버레이용 canvas
 */
function init(canvasEl) {
  canvas = canvasEl;
  ctx = canvas.getContext("2d");
  console.info("[ITDA Overlay] 초기화 완료");
}

/**
 * 프레임 렌더링
 * index.html의 requestAnimationFrame 루프에서 호출
 *
 * @param {Object} results - window.itdaLastResults (MediaPipe 결과)
 * @param {number} fps - 현재 FPS
 */
function draw(results, fps) {
  if (!ctx || !canvas) return;

  // 캔버스 초기화
  ctx.clearRect(0, 0, canvas.width, canvas.height);

  if (!enabled) {
    drawFPS(fps);
    return;
  }

  if (!results?.multiHandLandmarks) {
    drawFPS(fps);
    return;
  }

  for (let h = 0; h < results.multiHandLandmarks.length; h++) {
    const landmarks  = results.multiHandLandmarks[h];
    const handedness = results.multiHandedness?.[h]?.label ?? "Unknown";
    const isRight    = handedness === "Right";

    // ── 1. 전체 연결선 (회색) ─────────────────────────────
    ctx.strokeStyle = COLORS.connection;
    ctx.lineWidth   = 1.5;
    for (const [a, b] of HAND_CONNECTIONS) {
      const pa = toCanvasCoord(landmarks[a]);
      const pb = toCanvasCoord(landmarks[b]);
      ctx.beginPath();
      ctx.moveTo(pa.x, pa.y);
      ctx.lineTo(pb.x, pb.y);
      ctx.stroke();
    }

    // ── 2. 핵심 관절 점 강조 ─────────────────────────────
    for (let i = 0; i < landmarks.length; i++) {
      const p     = toCanvasCoord(landmarks[i]);
      const isKey = ESSENTIAL_SET.has(i);

      if (isKey) {
        // 엄지 특수 색상
        const isThumb = (i === 18 || i === 20);
        ctx.fillStyle = isThumb
          ? COLORS.thumb
          : (isRight ? COLORS.essential_r : COLORS.essential);
        ctx.beginPath();
        ctx.arc(p.x, p.y, 6, 0, Math.PI * 2);
        ctx.fill();

        // 외곽선
        ctx.strokeStyle = "rgba(0,0,0,0.6)";
        ctx.lineWidth   = 1;
        ctx.stroke();
      } else {
        // 비핵심 관절: 작은 점
        ctx.fillStyle = "rgba(255,255,255,0.3)";
        ctx.beginPath();
        ctx.arc(p.x, p.y, 3, 0, Math.PI * 2);
        ctx.fill();
      }
    }

    // ── 3. 손 레이블 (손목 위에 표시) ───────────────────
    const wrist = toCanvasCoord(landmarks[0]);
    drawLabel(
      `${handedness} Hand`,
      wrist.x,
      wrist.y + 20,
      isRight ? COLORS.essential_r : COLORS.essential
    );
  }

  // ── 4. FPS 패널 ──────────────────────────────────────────
  drawFPS(fps);
}

// ─── 보조 함수 ────────────────────────────────────────────────

function toCanvasCoord(lm) {
  return {
    x: lm.x * canvas.width,
    y: lm.y * canvas.height,
  };
}

function drawLabel(text, x, y, color = COLORS.text_fg) {
  ctx.font      = "bold 13px 'Noto Sans KR', sans-serif";
  const w       = ctx.measureText(text).width;
  ctx.fillStyle = COLORS.text_bg;
  ctx.fillRect(x - 4, y - 14, w + 8, 20);
  ctx.fillStyle = color;
  ctx.fillText(text, x, y);
}

function drawFPS(fps) {
  const fpsNum = parseFloat(fps) || 0;
  const color  = fpsNum >= 30 ? COLORS.fps_ok
               : fpsNum >= 15 ? COLORS.fps_warn
               : COLORS.fps_bad;

  const text = `FPS: ${fpsNum.toFixed(1)}`;
  ctx.font      = "bold 16px monospace";
  const w       = ctx.measureText(text).width;
  ctx.fillStyle = COLORS.text_bg;
  ctx.fillRect(8, 8, w + 12, 28);
  ctx.fillStyle = color;
  ctx.fillText(text, 14, 28);
}

function enable()  { enabled = true; }
function disable() { enabled = false; }
function toggle()  { enabled = !enabled; }

// ─── 전역 노출 ────────────────────────────────────────────────
window.ITDAOverlay = { init, draw, enable, disable, toggle };
