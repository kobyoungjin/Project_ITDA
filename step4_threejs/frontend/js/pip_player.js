/**
 * pip_player.js - PIP 영상 제어 및 SLM-RAG 시뮬레이션
 */

const slmOutput = document.getElementById('slm-output');
const ragOutput = document.getElementById('rag-output');
const pipVideo = document.getElementById('pip-video');

// ── SLM-RAG 시뮬레이션 시나리오 ────────────────────────────
// 실제 3단계 모듈이 완성되면 이 부분은 WebSocket 또는 API 호출로 대체됩니다.
const scenarios = [
    { slm: "안... 녕...", rag: "안녕하세요!" },
    { slm: "밥... 먹었...", rag: "식사 하셨나요?" },
    { slm: "오... 늘... 날... 씨...", rag: "오늘 날씨가 참 좋네요." },
    { slm: "수... 어... 공... 부...", rag: "함께 수어를 공부해봐요." }
];

let currentScenario = 0;

function simulateTranslation() {
    const scenario = scenarios[currentScenario];
    
    // 1단계: SLM 예측 (느리게 타이핑되는 효과)
    slmOutput.textContent = "";
    let i = 0;
    const interval = setInterval(() => {
        slmOutput.textContent += scenario.slm[i];
        i++;
        if (i >= scenario.slm.length) {
            clearInterval(interval);
            
            // 2단계: RAG 보정 결과 출력 (서버 응답 시뮬레이션)
            setTimeout(() => {
                ragOutput.innerHTML = `<span>${scenario.rag}</span>`;
                ragOutput.style.color = 'var(--accent-cyan)';
                
                // 다음 시나리오 준비
                currentScenario = (currentScenario + 1) % scenarios.length;
            }, 800);
        }
    }, 150);
}

// 5초마다 시뮬레이션 반복
setInterval(simulateTranslation, 8000);

// PIP 비디오 조작 (간단한 예시)
document.getElementById('btn-camera-reset').addEventListener('click', () => {
    // 비디오 재생 시점 초기화
    pipVideo.currentTime = 0;
    console.info("[ITDA PIP] 영상 재생 시점 초기화");
});

console.info("[ITDA PIP] 시뮬레이션 모듈 로드 완료");
simulateTranslation();
