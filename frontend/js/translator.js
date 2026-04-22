/**
 * translator.js
 *
 * [목적]
 * 1. Web Speech API를 활용한 음성 인식(STT)
 * 2. 텍스트 입력을 백엔드(/api/sign-language/search)로 전송
 * 3. 응답(감정) 기반으로 아바타 표정 및 UI 업데이트
 */

import * as THREE from 'three';

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

      // [참고 영상 PIP 제어]
      const refPip = document.getElementById('ref-pip');
      const refVid = document.getElementById('ref-video');
      if (data.video_url && data.video_url.startsWith('http')) {
        refPip.style.display = 'block';
        refVid.src = data.video_url;
        refVid.play().catch(e => console.warn("[Video] Auto-play blocked or failed:", e));
      } else {
        refPip.style.display = 'none';
      }

      // 아바타 애니메이션 트리거 (감정 + 키워드 기반 모션)
      animateAvatar(data.emotions, data.keyword);
    }
  } catch (err) {
    console.error("[Search Error]", err);
    // [단독 모드 변환] 
    let fallbackKeyword = Object.keys(MOTION_PROFILES).find(k => text.includes(k) || (k === '고맙습니다' && text.includes('감사')));
    
    if (fallbackKeyword) {
      emotionOutput.innerHTML = `<span style="color:#00F2FE; font-weight:800;">[로컬 매칭] : ${fallbackKeyword}</span>`;
      animateAvatar(['행복'], fallbackKeyword);
    } else {
      emotionOutput.innerHTML = `<span style="color:#ffb8b8">"안녕", "고마워", "사랑해", "네", "아니" 등이나 문장을 입력해보세요.</span>`;
      // 모르는 단어라도 감정을 담아 움직이도록 함 (Generic Fallback)
      animateAvatar(['정보전달'], text);
    }
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
    // Step 1: 준비 (양손을 가슴 높이로 들어 올림, 펴서 모은 손)
    { 
      duration: 600,  
      bones: (()=>{ let b={ LeftArm: {x:-0.5, y:0, z:0}, LeftForeArm: {x:0.8, y:0, z:0}, RightArm: {x:-0.8, y:0, z:0}, RightForeArm: {x:1.0, y:0, z:0} }; applyHandPreset(b, 'Left', 'PALM'); applyHandPreset(b, 'Right', 'PALM'); return b; })(),
      morphs: { mouthSmile: 0.3 }
    },
    // Step 2: 접촉 (오른손을 왼손등에 가볍게 터치, 목 살짝 굽힘)
    { 
      duration: 500,  
      bones: { LeftHand: {x:0.2, y:0, z:0}, RightHand: {x:0.3, y:0, z:0}, Neck: {x:0.1, y:0, z:0} } 
    },
    // Step 3: 목례 (상체와 목을 숙이며 감사 표현, 밝은 미소)
    { 
      duration: 800,  
      bones: { Spine: {x:0.2, y:0, z:0}, Neck: {x:0.2, y:0, z:0} },
      morphs: { mouthSmile: 0.5, eyeWideLeft: 0.2, eyeWideRight: 0.2 } 
    }
  ],
  "미안합니다": [
    { duration: 800,  bones: { Neck: {x:0.3, y:0, z:0}, RightArm: {x:-1.5, y:0, z:0}, RightForeArm: {x:1.2, y:0, z:0} }, morphs: { Sad: 0.8 } },
    { duration: 1200, bones: { Neck: {x:0, y:0, z:0}, RightArm: {x:0, y:0, z:0} } }
  ],
  "사랑합니다": [
    // 머리위 하트는 리깅상 제약이 있을 수 있어, 양손을 가슴에서 포개는 동작으로 구성
    { duration: 700, bones: { Spine: {x:0.1, y:0, z:0}, RightArm: {x:-1.2, y:0, z:-0.5}, LeftArm: {x:-1.2, y:0, z:0.5}, RightForeArm: {x:1.5, y:0, z:0}, LeftForeArm: {x:1.5, y:0, z:0} }, morphs: { mouthSmile: 0.8, eyeWideLeft: 0.3, eyeWideRight: 0.3 } },
    { duration: 1000, bones: { Spine: {x:0, y:0, z:0} }, morphs: { mouthSmile: 0.5 } }
  ],
  "네": [
    // 긍정: 오른 주먹을 쥐고 상하로 가볍게 흔듦 + 고개 끄덕임
    { duration: 400, bones: (()=>{ let b={ Neck: {x:0.2, y:0, z:0}, RightArm: {x:-0.5, y:0, z:0}, RightForeArm: {x:0.8, y:0, z:0} }; applyHandPreset(b,'Right','FIST'); return b; })(), morphs: { mouthSmile: 0.2 } },
    { duration: 400, bones: { Neck: {x:0, y:0, z:0}, RightForeArm: {x:0.5, y:0, z:0} }, morphs: { mouthSmile: 0.2 } }
  ],
  "아니오": [
    // 부정: 오른손 펴서 좌우로 흔듦 + 고개 가로저음
    { duration: 400, bones: (()=>{ let b={ Neck: {x:0, y:-0.15, z:0}, RightArm: {x:-0.5, y:0, z:0}, RightForeArm: {x:0.8, y:-0.3, z:0} }; applyHandPreset(b,'Right','PALM'); return b; })(), morphs: { browLowererLeft: 0.4, browLowererRight: 0.4 } },
    { duration: 400, bones: { Neck: {x:0, y:0.15, z:0}, RightForeArm: {x:0.8, y:0.3, z:0} }, morphs: { browLowererLeft: 0.4, browLowererRight: 0.4 } }
  ],
  "GENERIC_EXPLANATION": [
    // 모르는 단어 대응: 양손을 가볍게 벌리며 설명하는 기조
    { duration: 600, bones: { Spine: {x:0.1, y:0, z:0}, RightArm: {x:-0.5, y:-0.2, z:0}, LeftArm: {x:-0.5, y:0.2, z:0}, RightForeArm: {x:0.8, y:0, z:0}, LeftForeArm: {x:0.8, y:0, z:0} } },
    { duration: 800, bones: { RightHand: {x:0.1, y:0, z:0.2}, LeftHand: {x:0.1, y:0, z:-0.2} } }
  ],
  "default": [
    { duration: 1000, bones: { Spine: {x:0, y:0, z:0}, RightArm: {x:-0.15, y:-0.15, z:0}, LeftArm: {x:-0.15, y:0.15, z:0} } }
  ]
};

// [감정명 -> 아바타 모프] 매핑 헬퍼
const EMOTION_MORPH_MAP = {
  "기쁨": { mouthSmile: 0.5, eyeWideLeft: 0.1 },
  "행복": { mouthSmile: 0.7, eyeWideLeft: 0.2 },
  "슬픔": { Sad: 0.6, mouthFrownLeft: 0.4 },
  "긴박": { Surprised: 0.7, eyeWideLeft: 0.5 },
  "감사": { mouthSmile: 0.4, Neck: {x:0.1} },
  "정보전달": { Surprised: 0.1, mouthSmile: 0.1 }
};

/**
 * 3D 수어 애니메이션 엔진 (Quaternion Slerp 기반)
 */
async function animateAvatar(emotions, keyword) {
  const avatar = window.ITDAAvatar5;
  if (!avatar) return;

  window.translationModeActive = true;
  if (translationTimeout) clearTimeout(translationTimeout);

  // 1. 단어 기반 프로필 찾기 (Fuzzy Match 포함)
  let profile = MOTION_PROFILES[keyword];
  if (!profile) {
    const foundKey = Object.keys(MOTION_PROFILES).find(k => keyword.includes(k));
    profile = foundKey ? MOTION_PROFILES[foundKey] : MOTION_PROFILES["GENERIC_EXPLANATION"];
  }

  // 2. 감정 데이터 기반 페이셜 선처리
  if (emotions && emotions.length > 0) {
    for (const emName of emotions) {
      const effect = EMOTION_MORPH_MAP[emName];
      if (effect) {
        for (const [mName, val] of Object.entries(effect)) {
            if (typeof val === 'number') avatar.setMorphTarget(mName, val);
        }
      }
    }
  }

  console.log(`[Motion] ${keyword} (Dynamically Resolved) 재생 시작`);

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
        const bone = avatar.bones[bName] 
               || avatar.bones['mixamorig:' + bName] 
               || avatar.bones['mixamorig' + bName];
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
            const bone = avatar.bones[bName] 
                   || avatar.bones['mixamorig:' + bName] 
                   || avatar.bones['mixamorig' + bName];
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
