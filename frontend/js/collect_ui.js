/**
 * collect_ui.js ─ [ML] 데이터 수집 및 훈련 제어 모듈 (멀티-take)
 *
 * ■ 멀티-take 수집 흐름
 *   한 단어를 같은 동작으로 "여러 번" 녹화한다. 녹화 1회(시작→중지) = take 1개.
 *   백엔드는 /start 마다 새 세션 ID를 출처(source)로 기록하므로,
 *   take 가 많을수록 데이터 다양성이 커지고 누수 없는 평가도 가능해진다.
 */

const API_BASE = `http://${location.hostname || '127.0.0.1'}:8000/api/collect`;

const state = {
    isRecording: false,
    word: '',              // 지금 take 들을 모으고 있는 단어
    takes: [],             // 완료된 take 목록 [{ n, samples }]
    currentTakeCount: 0,   // 진행 중인 take 의 샘플 수
    lastSampleTime: 0,
    sampleInterval: 200,   // 200ms 마다 1샘플
    latestPoseLandmarks: null,
};

// UI 요소
const labelInput   = document.getElementById('collect-word-input');
const btnStart     = document.getElementById('btn-collect-start');
const btnStop      = document.getElementById('btn-collect-stop');
const btnTrain     = document.getElementById('btn-collect-train');
const summaryEl    = document.getElementById('collect-take-summary');
const takeListEl   = document.getElementById('collect-take-list');
const takeStatusEl = document.getElementById('collect-take-status');
const videoInput   = document.getElementById('collect-video-file');
const btnVideo     = document.getElementById('btn-collect-video');
const urlInput     = document.getElementById('collect-url-input');
const btnUrl       = document.getElementById('btn-collect-url');

function init() {
    console.info('[ITDA Collect] 데이터 수집 모듈 초기화 (멀티-take)');

    btnStart?.addEventListener('click', startRecording);
    btnStop?.addEventListener('click', stopRecording);
    btnTrain?.addEventListener('click', trainModel);

    btnVideo?.addEventListener('click', () => videoInput.click());
    videoInput?.addEventListener('change', handleVideoUpload);
    btnUrl?.addEventListener('click', handleUrlUpload);

    // 단어를 바꾸면 take 목록 초기화 (녹화 중에는 입력이 잠겨 있어 안전)
    labelInput?.addEventListener('input', () => {
        if (state.isRecording) return;
        if (labelInput.value.trim() !== state.word) resetTakes();
    });

    // 카메라 데이터 구독
    window.addEventListener('itda:hands:results', onHandsDetected);
    window.addEventListener('itda:pose:results', (e) => {
        if (!e.detail.landmarks) return;
        const POSE_KEYS = {
            left_shoulder: 11, right_shoulder: 12,
            left_elbow: 13,    right_elbow: 14,
            left_wrist: 15,    right_wrist: 16,
        };
        const lmDict = {};
        for (const [k, idx] of Object.entries(POSE_KEYS)) {
            const lm = e.detail.landmarks[idx];
            if (lm) lmDict[k] = lm;
        }
        state.latestPoseLandmarks = { landmarks: lmDict };
    });

    renderTakes();
}

// ── take 목록 표시 ───────────────────────────────────────────
function resetTakes() {
    state.word = '';
    state.takes = [];
    state.currentTakeCount = 0;
    renderTakes();
    if (takeStatusEl) {
        takeStatusEl.textContent = '단어를 입력하고 같은 동작을 여러 번 녹화하세요. 많이 찍을수록 정확해집니다.';
        takeStatusEl.style.color = '';
    }
}

function renderTakes() {
    const total = state.takes.reduce((s, t) => s + t.samples, 0);
    if (summaryEl) summaryEl.textContent = `Take ${state.takes.length}개 · 총 ${total}개 샘플`;
    if (takeListEl) {
        takeListEl.innerHTML = state.takes
            .map(t => `<span>✓ Take ${t.n} — ${t.samples}개</span>`)
            .join('');
    }
}

// ── 한 번의 동작 녹화 (= take 1개) ───────────────────────────
async function startRecording() {
    const word = labelInput.value.trim();
    if (!word) {
        alert('수집할 단어의 이름을 먼저 입력해주세요!');
        return;
    }
    // 단어가 바뀌었으면 take 목록을 새로 시작 (이전 단어 데이터는 CSV에 그대로 보존됨)
    if (word !== state.word) {
        state.word = word;
        state.takes = [];
    }

    try {
        const res = await fetch(`${API_BASE}/start`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ label: word }),
        });
        const data = await res.json();
        if (!data.ok) {
            alert('수집 시작 실패: ' + (data.message || ''));
            return;
        }
    } catch (e) {
        console.error('수집 시작 실패:', e);
        alert('백엔드에 연결할 수 없습니다. 서버(8000)를 확인하세요.');
        return;
    }

    state.isRecording = true;
    state.currentTakeCount = 0;
    btnStart.style.display = 'none';
    btnStop.style.display = 'block';
    labelInput.disabled = true;

    const takeNo = state.takes.length + 1;
    if (takeStatusEl) {
        takeStatusEl.innerHTML = `🔴 <b>Take ${takeNo}</b> 녹화 중 — 동작을 1회 수행하세요. (0개)`;
        takeStatusEl.style.color = '#ff6b6b';
    }
}

async function stopRecording() {
    let finalCount = state.currentTakeCount;
    try {
        const res = await fetch(`${API_BASE}/stop`, { method: 'POST' });
        const data = await res.json();
        if (typeof data.count === 'number') finalCount = data.count;
    } catch (e) {
        console.error('수집 중지 실패:', e);
    }

    state.isRecording = false;
    state.currentTakeCount = 0;
    btnStart.style.display = 'block';
    btnStop.style.display = 'none';
    labelInput.disabled = false;

    if (finalCount > 0) {
        const n = state.takes.length + 1;
        state.takes.push({ n, samples: finalCount });
        if (takeStatusEl) {
            takeStatusEl.innerHTML = `✅ Take ${n} 저장 완료 (${finalCount}개). 같은 동작을 한 번 더 녹화하거나, 다른 단어로 넘어가세요.`;
            takeStatusEl.style.color = '';
        }
    } else if (takeStatusEl) {
        takeStatusEl.innerHTML = '⚠️ 손이 감지되지 않아 저장된 샘플이 없습니다. 손을 카메라에 보이게 한 뒤 다시 녹화하세요.';
        takeStatusEl.style.color = '';
    }
    renderTakes();
}

async function onHandsDetected(e) {
    if (!state.isRecording) return;

    const now = Date.now();
    if (now - state.lastSampleTime < state.sampleInterval) return;

    const hands = e.detail.hands;
    if (!hands || hands.length === 0) return;

    let right_landmarks = null, left_landmarks = null;
    for (const h of hands) {
        if (h.handedness === 'Right') right_landmarks = h.landmarks;
        else if (h.handedness === 'Left') left_landmarks = h.landmarks;
    }

    try {
        const res = await fetch(`${API_BASE}/sample`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                right_landmarks,
                left_landmarks,
                pose_landmarks: state.latestPoseLandmarks,
                landmarks: hands[0].landmarks,
                handedness: hands[0].handedness,
            }),
        });
        const data = await res.json();
        if (data.ok) {
            state.currentTakeCount = data.count;
            state.lastSampleTime = now;
            const takeNo = state.takes.length + 1;
            if (takeStatusEl) {
                takeStatusEl.innerHTML = `🔴 <b>Take ${takeNo}</b> 녹화 중 — 동작을 수행하세요. (${data.count}개)`;
            }
        }
    } catch (err) {
        console.warn('샘플 전송 실패:', err);
    }
}

async function trainModel() {
    if (state.isRecording) {
        alert('녹화를 먼저 중지한 뒤 훈련하세요.');
        return;
    }
    btnTrain.disabled = true;
    btnTrain.textContent = '⏳ 훈련 중...';
    try {
        const res = await fetch(`${API_BASE}/train`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ n_neighbors: 5 }),
        });
        const data = await res.json();
        if (data.ok) {
            // 학습 단어 목록이 갱신되었음을 다른 창(avatar_only.html 등)에 알림.
            // 수신 측은 '🆕 새로 추가된 단어' 섹션을 자동 업데이트한다.
            try {
                const ch = new BroadcastChannel('itda_model_channel');
                ch.postMessage({ type: 'words_updated', label_count: data.label_count });
                ch.close();
            } catch (e) { /* 채널 미지원 환경 — 무시 */ }
            alert(`훈련 완료!\n정확도: ${data.accuracy}%\n단어 수: ${data.label_count}`);
        } else {
            alert(`훈련 실패: ${data.message}`);
        }
    } catch (e) {
        console.error('훈련 요청 실패:', e);
        alert('백엔드에 연결할 수 없습니다.');
    } finally {
        btnTrain.disabled = false;
        btnTrain.textContent = '⚙️ KNN 모델 훈련';
    }
}

// ── 영상 기반 수집 (URL / PC 파일) ───────────────────────────
async function handleUrlUpload() {
    const url = urlInput.value.trim();
    const label = labelInput.value.trim();
    if (!url) { alert('영상 URL을 입력해주세요!'); return; }
    if (!label) { alert('단어 이름을 먼저 입력해주세요!'); return; }

    btnUrl.disabled = true;
    btnUrl.textContent = '⏳';
    try {
        const res = await fetch(
            `${API_BASE}/url?label=${encodeURIComponent(label)}&url=${encodeURIComponent(url)}`,
            { method: 'POST' }
        );
        const data = await res.json();
        if (data.ok) {
            alert(`분석 완료!\n${data.saved_samples}개의 샘플이 '${label}'로 추가되었습니다.`);
            urlInput.value = '';
        } else {
            alert('URL 분석 실패: ' + data.message);
        }
    } catch (err) {
        console.error('URL 업로드 실패:', err);
        alert('백엔드에 연결할 수 없습니다.');
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
            body: formData,
        });
        const data = await res.json();
        if (data.ok) {
            alert(`분석 완료!\n${data.saved_samples}개의 샘플이 '${label}'로 추가되었습니다.`);
        } else {
            alert('비디오 분석 실패: ' + data.message);
        }
    } catch (err) {
        console.error('비디오 업로드 실패:', err);
        alert('백엔드에 연결할 수 없습니다.');
    } finally {
        btnVideo.disabled = false;
        btnVideo.textContent = '📂 내 PC 영상 파일 학습';
        videoInput.value = '';
    }
}

// 외부 노출
window.ITDACollect = {
    init,
    stop: () => { if (state.isRecording) stopRecording(); },
};

// 즉시 실행
init();
