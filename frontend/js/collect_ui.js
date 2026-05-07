/**
 * collect_ui.js ─ [ML] 데이터 수집 및 훈련 제어 모듈
 * 
 * ■ 역할
 *   1. 사용자가 '수집' 모드일 때 랜드마크 데이터를 백엔드 /api/collect/sample 로 전송.
 *   2. 수집 시작/중지 및 KNN 모델 훈련 명령 제어.
 */

const API_BASE = 'http://127.0.0.1:8000/api/collect';

const state = {
    isRecording: false,
    label: '',
    count: 0,
    lastSampleTime: 0,
    sampleInterval: 200, // 200ms 마다 1샘플 수집 (너무 많으면 오버피팅/데이터 비대)
};

// UI 요소
const labelInput = document.getElementById('collect-label');
const btnStart   = document.getElementById('btn-collect-start');
const btnStop    = document.getElementById('btn-collect-stop');
const btnTrain   = document.getElementById('btn-collect-train');
const countEl    = document.getElementById('collect-count');
const msgEl      = document.getElementById('collect-msg');

async function init() {
    console.info('[ITDA Collect] 데이터 수집 모듈 초기화');

    btnStart.addEventListener('click', startRecording);
    btnStop.addEventListener('click', stopRecording);
    btnTrain.addEventListener('click', trainModel);

    // 카메라 데이터 구독
    window.addEventListener('itda:hands:results', onHandsDetected);
    
    // 초기 상태 확인
    updateStatus();
}

async function startRecording() {
    const label = labelInput.value.trim();
    if (!label) {
        alert('수집할 단어의 이름을 입력해주세요!');
        return;
    }

    try {
        const res = await fetch(`${API_BASE}/start`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ label })
        });
        const data = await res.json();
        
        if (data.ok) {
            state.isRecording = true;
            state.label = label;
            state.count = 0;
            btnStart.style.display = 'none';
            btnStop.style.display = 'block';
            labelInput.disabled = true;
            msgEl.textContent = `🔴 '${label}' 수집 중... 카메라 앞에서 동작을 반복하세요.`;
            msgEl.style.color = '#ff4757';
        }
    } catch (e) {
        console.error('수집 시작 실패:', e);
    }
}

async function stopRecording() {
    try {
        const res = await fetch(`${API_BASE}/stop`, { method: 'POST' });
        const data = await res.json();
        
        state.isRecording = false;
        btnStart.style.display = 'block';
        btnStop.style.display = 'none';
        labelInput.disabled = false;
        msgEl.textContent = `✅ 수집 완료. 총 ${data.count}개의 샘플이 저장되었습니다.`;
        msgEl.style.color = 'var(--accent-green)';
        updateStatus();
    } catch (e) {
        console.error('수집 중지 실패:', e);
    }
}

async function onHandsDetected(e) {
    if (!state.isRecording) return;
    
    const now = Date.now();
    if (now - state.lastSampleTime < state.sampleInterval) return;

    const hands = e.detail.hands;
    if (hands.length === 0) return;

    // 일단 첫 번째 손(주로 쓰는 손) 데이터만 전송
    const landmarks = hands[0].landmarks;
    const handedness = hands[0].handedness;

    try {
        const res = await fetch(`${API_BASE}/sample`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ landmarks, handedness })
        });
        const data = await res.json();
        if (data.ok) {
            state.count = data.count;
            countEl.textContent = `${data.count}개`;
            state.lastSampleTime = now;
        }
    } catch (err) {
        console.warn('샘플 전송 실패:', err);
    }
}

async function trainModel() {
    msgEl.textContent = '⚙️ 모델 훈련 중... 잠시만 기다려주세요.';
    btnTrain.disabled = true;

    try {
        const res = await fetch(`${API_BASE}/train`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ n_neighbors: 5 })
        });
        const data = await res.json();
        
        if (data.ok) {
            alert(`훈련 완료!\n정확도: ${data.accuracy}%\n단어 수: ${data.label_count}`);
            msgEl.textContent = data.message;
        } else {
            alert(`훈련 실패: ${data.message}`);
            msgEl.textContent = '❌ 훈련 실패';
        }
    } catch (e) {
        console.error('훈련 요청 실패:', e);
    } finally {
        btnTrain.disabled = false;
    }
}

async function updateStatus() {
    try {
        const res = await fetch(`${API_BASE}/status`);
        const data = await res.json();
        countEl.textContent = `${data.count || 0}개`;
    } catch (e) {}
}

// 외부 노출
window.ITDACollect = {
    init,
    stop: () => {
        if (state.isRecording) stopRecording();
    }
};

// 즉시 실행
init();
