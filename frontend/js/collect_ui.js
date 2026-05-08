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
const labelInput = document.getElementById('collect-word-input');
const btnStart   = document.getElementById('btn-collect-start');
const btnStop    = document.getElementById('btn-collect-stop');
const btnTrain   = document.getElementById('btn-collect-train');
const countEl    = document.getElementById('collect-sample-count');
const videoInput = document.getElementById('collect-video-file');
const btnVideo   = document.getElementById('btn-collect-video');
const urlInput   = document.getElementById('collect-url-input');
const btnUrl     = document.getElementById('btn-collect-url');
const btnBatch   = document.getElementById('btn-collect-batch');

async function init() {
    console.info('[ITDA Collect] 데이터 수집 모듈 초기화');

    btnStart?.addEventListener('click', startRecording);
    btnStop?.addEventListener('click', stopRecording);
    btnTrain?.addEventListener('click', trainModel);
    
    // 비디오 업로드 제어
    btnVideo?.addEventListener('click', () => videoInput.click());
    videoInput?.addEventListener('change', handleVideoUpload);

    // URL 추출 제어
    btnUrl?.addEventListener('click', handleUrlUpload);

    // 배치 학습 제어
    btnBatch?.addEventListener('click', handleBatchUpload);

    // 카메라 데이터 구독
    window.addEventListener('itda:hands:results', onHandsDetected);
    
    // 초기 상태 확인
    updateStatus();
}

async function handleBatchUpload() {
    if (!confirm('사전 영상 데이터(상위 10개)를 자동으로 학습하시겠습니까?\n이 작업은 약 1~2분 정도 소요됩니다.')) return;

    btnBatch.disabled = true;
    btnBatch.textContent = '⏳ 자동 학습 진행 중...';

    try {
        const res = await fetch(`${API_BASE}/batch?limit_words=10`, { method: 'POST' });
        const data = await res.json();
        
        if (data.ok) {
            alert(`🎉 자동 학습 완료!\n${data.message}`);
            updateStatus();
        } else {
            alert('배치 학습 실패: ' + data.message);
        }
    } catch (err) {
        console.error('배치 학습 실패:', err);
    } finally {
        btnBatch.disabled = false;
        btnBatch.textContent = '🚀 사전 영상 자동 학습 시작';
    }
}

async function handleUrlUpload() {
    const url = urlInput.value.trim();
    const label = labelInput.value.trim();

    if (!url) {
        alert('영상 URL을 입력해주세요!');
        return;
    }
    if (!label) {
        alert('단어 이름을 먼저 입력해주세요!');
        return;
    }

    btnUrl.disabled = true;
    btnUrl.textContent = '⏳';

    try {
        const res = await fetch(`${API_BASE}/url?label=${encodeURIComponent(label)}&url=${encodeURIComponent(url)}`, {
            method: 'POST'
        });
        const data = await res.json();
        
        if (data.ok) {
            alert(`분석 완료!\n${data.saved_samples}개의 샘플이 '${label}'로 추가되었습니다.`);
            updateStatus();
            urlInput.value = '';
        } else {
            alert('URL 분석 실패: ' + data.message);
        }
    } catch (err) {
        console.error('URL 업로드 실패:', err);
    } finally {
        btnUrl.disabled = false;
        btnUrl.textContent = '추출';
    }
}

async function handleVideoUpload(e) {
    const file = e.target.files[0];
    if (!file) return;

    const label = labelInput.value.trim();
    if (!label) {
        alert('영상에 해당하는 단어 이름을 입력해주세요!');
        return;
    }

    const formData = new FormData();
    formData.append('file', file);
    
    btnVideo.disabled = true;
    btnVideo.textContent = '⏳ 분석 중...';

    try {
        const res = await fetch(`${API_BASE}/video?label=${encodeURIComponent(label)}`, {
            method: 'POST',
            body: formData
        });
        const data = await res.json();
        
        if (data.ok) {
            alert(`분석 완료!\n${data.saved_samples}개의 샘플이 '${label}'로 추가되었습니다.`);
            updateStatus();
        } else {
            alert('비디오 분석 실패: ' + data.message);
        }
    } catch (err) {
        console.error('비디오 업로드 실패:', err);
    } finally {
        btnVideo.disabled = false;
        btnVideo.textContent = '영상 업로드 및 분석';
        videoInput.value = '';
    }
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

    // 양손 데이터 추출
    let right_landmarks = null;
    let left_landmarks = null;

    for (const h of hands) {
        if (h.handedness === 'Right') {
            right_landmarks = h.landmarks;
        } else if (h.handedness === 'Left') {
            left_landmarks = h.landmarks;
        }
    }

    try {
        const res = await fetch(`${API_BASE}/sample`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ 
                right_landmarks, 
                left_landmarks,
                // 하위 호환성을 위해 hands[0]도 보냄 (필요 시)
                landmarks: hands[0].landmarks,
                handedness: hands[0].handedness
            })
        });
        const data = await res.json();
        if (data.ok) {
            state.count = data.count;
            if (countEl) countEl.textContent = `${data.count}개`;
            state.lastSampleTime = now;
        }
    } catch (err) {
        console.warn('샘플 전송 실패:', err);
    }
}

async function trainModel() {
    btnTrain.disabled = true;
    btnTrain.textContent = '⏳ 훈련 중...';

    try {
        const res = await fetch(`${API_BASE}/train`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ n_neighbors: 5 })
        });
        const data = await res.json();
        
        if (data.ok) {
            alert(`훈련 완료!\n정확도: ${data.accuracy}%\n단어 수: ${data.label_count}`);
        } else {
            alert(`훈련 실패: ${data.message}`);
        }
    } catch (e) {
        console.error('훈련 요청 실패:', e);
    } finally {
        btnTrain.disabled = false;
        btnTrain.textContent = '⚙️ KNN 모델 훈련 시작';
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
