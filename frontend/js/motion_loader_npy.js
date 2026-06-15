/**
 * motion_loader_npy.js
 * 
 * 국립국어원(SLDict) 관절 데이터 (.npy -> .json 변환본) 로더 및 재생 엔진.
 * 75개 MediaPipe 랜드마크 데이터를 기반으로 아바타를 구동합니다.
 */

const CACHE = new Map();
const JOINT_CACHE_DIR = './data/ksl_motions'; // 국립국어원 데이터 기본 경로
const FALLBACK_DIR    = './data/joint_cache'; // 기존 수동 캐시 경로

const FILE_LIST_CACHE = { ksl: null, joint: null };

async function getFileList(dir) {
    try {
        const resp = await fetch(dir + '/_list.json'); // 만약 서버에 목록 파일이 있다면 활용
        if (resp.ok) return await resp.json();
    } catch(e) {}
    return [];
}

async function loadJoints(word) {
    if (!word) return null;
    if (CACHE.has(word)) return CACHE.get(word);

    const safeWord = word.replace(/\//g, "_").replace(/,/g, "_");
    
    // 1. 정확한 이름으로 시도
    const dirs = [JOINT_CACHE_DIR, FALLBACK_DIR];
    for (const dir of dirs) {
        const url = `${dir}/${encodeURIComponent(safeWord)}.json`;
        try {
            const resp = await fetch(url, { cache: 'no-cache' });
            if (resp.ok) {
                const data = await resp.json();
                CACHE.set(word, data);
                return data;
            }
        } catch(e) {}
    }

    // 2. 백엔드 실시간 생성 요청 (NEW)
    console.info(`[JointLoader] '${word}' 데이터를 찾을 수 없어 실시간 생성을 시도합니다...`);
    try {
        const resolveResp = await fetch('http://localhost:8000/api/sign-language/resolve-motion', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ word: word })
        });
        
        if (resolveResp.ok) {
            const res = await resolveResp.json();
            console.info(`[JointLoader] 백엔드 생성 성공: ${res.message}`);
            // 생성되었으니 다시 1번 로직으로 로드 시도
            const retryUrl = `${JOINT_CACHE_DIR}/${encodeURIComponent(safeWord)}.json`;
            const retryResp = await fetch(retryUrl, { cache: 'no-cache' });
            if (retryResp.ok) {
                const data = await retryResp.json();
                CACHE.set(word, data);
                return data;
            }
        }
    } catch(e) {
        console.error(`[JointLoader] 백엔드 생성 요청 실패:`, e);
    }
    return null;
}

let currentAnimationId = null;
let isPlaying = false;

/**
 * 관절 데이터 기반 아바타 재생
 */
function playJoints(word, options = { loop: false }) {
    return new Promise(async (resolve) => {
        isPlaying = true;
        const data = await loadJoints(word);
        if (!data || !data.frames || data.frames.length === 0) {
            isPlaying = false;
            resolve();
            return;
        }

        const avatar = window.ITDAAvatar5;
        const retargeting = window.ITDARetargeting5;

        // 기존 재생 중인 애니메이션 중단
        stop();
        isPlaying = true;

        avatar?.stopIdle?.();

        let frameIdx = 0;
        const fps = data.fps || 15;
        // ~15fps 기준으로 정규화 (기존 29fps 파일도 자동 보정)
        const TARGET_FPS = 15;
        const frameSkip = Math.max(1, Math.round(fps / TARGET_FPS));
        const effectiveFps = fps / frameSkip;
        const interval = 1000 / effectiveFps;
        let lastTime = 0;

        console.info(`[JointLoader] '${word}' 재생 시작 (${data.frames.length} 프레임, 원본 ${fps}fps → skip=${frameSkip} → ${effectiveFps.toFixed(1)}fps)`);

        function animate(time) {
            if (!isPlaying) {
                resolve();
                return;
            }
            
            if (!lastTime) lastTime = time;
            const delta = time - lastTime;

            if (delta >= interval) {
                const frameData = data.frames[frameIdx];
                if (frameData) {
                    avatar?.updateSkeleton?.(frameData);
                    retargeting?.apply75Landmarks?.(frameData);
                }
                
                frameIdx += frameSkip;
                lastTime = time;
            }

            if (frameIdx < data.frames.length) {
                currentAnimationId = requestAnimationFrame(animate);
            } else {
                if (options.loop && isPlaying) {
                    // 반복 재생 (Loop)
                    frameIdx = 0;
                    currentAnimationId = requestAnimationFrame(animate);
                } else {
                    console.info(`[JointLoader] '${word}' 재생 완료`);
                    stop();
                    resolve();
                }
            }
        }
        
        currentAnimationId = requestAnimationFrame(animate);
        
        // 이벤트 발행 (UI 연동용)
        window.dispatchEvent(new CustomEvent('itda:motion:played', { 
            detail: { keyword: word, source: 'sldict' } 
        }));
    });
}

function stop() {
    isPlaying = false;
    if (currentAnimationId) {
        cancelAnimationFrame(currentAnimationId);
        currentAnimationId = null;
    }
    // 동작 중단 시 기본 포즈로 리셋
    if (window.ITDAAvatar5?.reset) {
        window.ITDAAvatar5.reset();
    }
}

// 전역 노출
window.ITDAMotionNPY = {
    load: loadJoints,
    play: playJoints,
    stop: stop
};

console.info('[JointLoader] 국립국어원 관절 로더 활성화');
