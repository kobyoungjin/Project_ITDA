/**
 * translator.js
 * 
 * [목적]
 * 1. Web Speech API를 활용한 음성 인식(STT)
 * 2. 텍스트 입력을 백엔드(/api/sign-language/search)로 전송
 * 3. 응답(감정) 기반으로 아바타 표정 및 UI 업데이트
 */

// UI Elements
const chatInput = document.getElementById('chat-input');
const btnMic = document.getElementById('btn-mic');
const btnSend = document.getElementById('btn-send');
const emotionOutput = document.getElementById('emotion-output');

// Web Speech API
const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
let recognition = null;
let isRecording = false;

if (SpeechRecognition) {
  recognition = new SpeechRecognition();
  recognition.lang = 'ko-KR'; // 한국어
  recognition.continuous = false;
  recognition.interimResults = false;

  recognition.onstart = () => {
    isRecording = true;
    btnMic.classList.add('recording');
    chatInput.placeholder = '말씀해 주세요...';
  };

  recognition.onresult = (event) => {
    const transcript = event.results[0][0].transcript;
    chatInput.value = transcript;
    sendMessage(transcript);
  };

  recognition.onerror = (event) => {
    console.error('[STT] Speech recognition error:', event.error);
    isRecording = false;
    btnMic.classList.remove('recording');
    chatInput.placeholder = '번역할 내용을 입력하세요...';
    emotionOutput.innerHTML = `<span style="color:#ff4757">음성 인식 오류: ${event.error}</span>`;
  };

  recognition.onend = () => {
    isRecording = false;
    btnMic.classList.remove('recording');
    chatInput.placeholder = '번역할 내용을 입력하세요...';
  };
} else {
  console.warn('[STT] Web Speech API is not supported in this browser.');
  btnMic.style.display = 'none'; // 미지원 브라우저는 버튼 숨김
}

// Event Listeners
btnMic.addEventListener('click', () => {
  if (!recognition) return;
  if (isRecording) {
    recognition.stop();
  } else {
    chatInput.value = '';
    recognition.start();
  }
});

btnSend.addEventListener('click', () => {
  const text = chatInput.value.trim();
  if (text) sendMessage(text);
});

chatInput.addEventListener('keypress', (e) => {
  if (e.key === 'Enter') {
    const text = chatInput.value.trim();
    if (text) sendMessage(text);
  }
});

// 번역 데이터 플래그 (웹캠 리타겟팅과 충돌을 막기 위한 전역 상태)
window.translationModeActive = false;
let translationTimeout = null;

// 백엔드 통신 및 번역
async function sendMessage(text) {
  chatInput.value = '';
  emotionOutput.innerHTML = `<span style="color:var(--text-muted); font-style:italic;">🤔 텍스트 분석 및 모션 생성 중... ("${text}")</span>`;

  try {
    const res = await fetch('http://localhost:8000/api/sign-language/search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query: text, context: "" })
    });

    if (!res.ok) throw new Error(`서버 응답 오류 (코드: ${res.status})`);
    
    const result = await res.json();
    const data = result.data;

    if (data) {
      // 화면 출력 업데이트
      const emotionsHtml = data.emotions ? data.emotions.map(em => `<span class="t-emotion-badge" style="background: rgba(0, 242, 254, 0.1); border: 1px solid var(--accent-cyan); color: var(--accent-cyan);">${em}</span>`).join(' ') : '';
      emotionOutput.innerHTML = `<span style="color:var(--accent-cyan); font-weight:800; font-size:1.1rem;">✨ ${data.keyword}</span><br/><span style="font-size:0.8rem; color:var(--text-muted)">${data.warm_translation}</span> ${emotionsHtml}`;

      // 아바타 애니메이션 트리거 (감정 + 키워드 기반 모션)
      animateAvatar(data.emotions, data.keyword);
    }
  } catch (err) {
    console.error('[Translator] Error:', err);
    emotionOutput.innerHTML = `<span style="color:#ff4757">오류 발생: 서버 연결을 확인해주세요.</span>`;
  }
}

// --- 전문 수어 리깅 및 프리셋 ---
const RIG_PRESETS = {
  FIST: {
    Thumb1: {x:0.3, y:0, z:0}, Index1: {x:1.5, y:0, z:0}, Middle1: {x:1.5, y:0, z:0}, Ring1: {x:1.5, y:0, z:0}, Pinky1: {x:1.5, y:0, z:0},
    Index2: {x:1.2, y:0, z:0}, Middle2: {x:1.2, y:0, z:0}, Ring2: {x:1.2, y:0, z:0}, Pinky2: {x:1.2, y:0, z:0}
  },
  PALM: {
    Thumb1: {x:0, y:0, z:0}, Index1: {x:0, y:0, z:0}, Middle1: {x:0, y:0, z:0}, Ring1: {x:0, y:0, z:0}, Pinky1: {x:0, y:0, z:0}
  },
  POINT: {
    Index1: {x:0, y:0, z:0}, Index2: {x:0, y:0, z:0},
    Middle1: {x:1.5, y:0, z:0}, Ring1: {x:1.5, y:0, z:0}, Pinky1: {x:1.5, y:0, z:0}
  }
};

/**
 * 특정 마디 그룹(예: 오른손)에 프리셋 적용 보조 함수
 */
function applyHandPreset(bonesObj, side, presetName) {
  const preset = RIG_PRESETS[presetName];
  if (!preset) return;
  for (const [part, rot] of Object.entries(preset)) {
    bonesObj[side + 'Hand' + part] = rot;
  }
}

// --- 전문 수어 동작 프로필 (KSL Motion Profiles) ---
// 정밀 리깅을 위해 Spine, Neck, Finger 관절을 대폭 보강
const MOTION_PROFILES = {
  "안녕하세요": [
    { duration: 600,  bones: { Spine: {x:0.2, y:0, z:0}, RightArm: {x:-1.0, y:0, z:0}, RightForeArm: {x:1.2, y:0.4, z:0} }, morphs: { Surprised: 0.5 } },
    { duration: 1000, bones: { Spine: {x:0, y:0, z:0}, RightArm: {x:-0.5, y:0, z:0}, RightForeArm: {x:0.2, y:0, z:0} }, morphs: { Surprised: 0 } }
  ],
  "고맙습니다": [
    // 1단계: 손바닥을 펴서 가슴 앞으로
    { duration: 700,  bones: { Spine1: {x:0.1, y:0, z:0}, RightArm: {x:-0.8, y:0, z:0}, RightForeArm: {x:1.0, y:0, z:0}, RightHand: {x:0.5, y:0, z:0} } },
    // 2단계: 손가락을 정밀하게 제어 (보 상태)
    { duration: 800,  bones: (()=>{ let b={}; applyHandPreset(b,'Right','PALM'); b.RightHand={x:0.8, y:0, z:0}; return b; })() },
    { duration: 600,  bones: { Spine: {x:0.3, y:0, z:0}, RightArm: {x:0, y:0, z:0} } }
  ],
  "미안합니다": [
    { duration: 800,  bones: { Neck: {x:0.3, y:0, z:0}, RightArm: {x:-1.5, y:0, z:0}, RightForeArm: {x:1.2, y:0, z:0} }, morphs: { Sad: 0.8 } },
    { duration: 1200, bones: { Neck: {x:0, y:0, z:0}, RightArm: {x:0, y:0, z:0} } }
  ],
  "default": [
    { duration: 1000, bones: { Spine: {x:0.1, y:0, z:0}, RightArm: {x:-0.3, y:-0.3, z:0}, LeftArm: {x:-0.3, y:0.3, z:0} } }
  ]
};

/**
 * 3D 수어 애니메이션 엔진 (Quaternion Slerp 기반)
 */
async function animateAvatar(emotions, keyword) {
  const avatar = window.ITDAAvatar5;
  if (!avatar) return;

  window.translationModeActive = true;
  if (translationTimeout) clearTimeout(translationTimeout);

  const profile = MOTION_PROFILES[keyword] || MOTION_PROFILES["default"];
  console.log(`[Motion] ${keyword} (Slerp) 재생 시작`);

  /** 
   * 단계별 동작 실행 (Quaternion Slerp 지원)
   */
  const playStep = async (stepData) => {
    const duration = stepData.duration || 500;
    const startTime = performance.now();
    
    // 시작 및 타겟 쿼터니언 프리컴퓨팅
    const startQuats = {};
    const targetQuats = {};
    
    if (stepData.bones) {
      for (const [bName, euler] of Object.entries(stepData.bones)) {
        const bone = avatar.bones[bName] || avatar.bones['mixamorig' + bName];
        if (bone) {
          startQuats[bName] = bone.quaternion.clone();
          // Euler -> Quaternion 변환
          const dummy = new THREE.Object3D();
          dummy.rotation.set(euler.x, euler.y, euler.z);
          targetQuats[bName] = dummy.quaternion.clone();
        }
      }
    }

    return new Promise((resolve) => {
      function update(now) {
        const elapsed = now - startTime;
        const progress = Math.min(elapsed / duration, 1.0);
        const ease = progress * (2 - progress);

        if (stepData.bones) {
          for (const bName in targetQuats) {
            const bone = avatar.bones[bName] || avatar.bones['mixamorig' + bName];
            if (bone) {
              bone.quaternion.copy(startQuats[bName]).slerp(targetQuats[bName], ease);
            }
          }
        }
        
        if (stepData.morphs) {
          for (const [mName, val] of Object.entries(stepData.morphs)) {
            avatar.setMorphTarget(mName, val * ease);
          }
        }

        if (progress < 1.0) requestAnimationFrame(update);
        else resolve();
      }
      requestAnimationFrame(update);
    });
  };

  /** 모든 뼈대를 초기 상태로 부드럽게 복구 (찌그러짐 방지) */
  const returnToInitial = async () => {
    const duration = 1000;
    const startTime = performance.now();
    const currentQuats = {};
    for (const name in avatar.initialBoneQuats) {
      const b = avatar.bones[name];
      if (b) currentQuats[name] = b.quaternion.clone();
    }

    return new Promise((resolve) => {
      function update(now) {
        const elapsed = now - startTime;
        const progress = Math.min(elapsed / duration, 1.0);
        
        for (const [name, initialQuat] of Object.entries(avatar.initialBoneQuats)) {
          const bone = avatar.bones[name];
          if (bone && currentQuats[name]) {
            bone.quaternion.copy(currentQuats[name]).slerp(initialQuat, progress);
          }
        }
        
        if (progress < 1.0) requestAnimationFrame(update);
        else resolve();
      }
      requestAnimationFrame(update);
    });
  };

  try {
    for (const step of profile) {
      await playStep(step);
    }
    // 종료 후 찌그러짐 방지를 위한 부드러운 복귀
    await returnToInitial();
    
    window.translationModeActive = false;
    console.log(`[Motion] ${keyword} 완료 및 복구 성공`);
  } catch (err) {
    console.error('[Motion] Error:', err);
    avatar.reset();
    window.translationModeActive = false;
  }
}
