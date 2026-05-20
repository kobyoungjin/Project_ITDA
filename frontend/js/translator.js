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

// [③ STT] stt-adapter.js 가 window.ITDAStt 를 노출.
// Web Speech API 미지원 브라우저에서도 Whisper WS 폴백으로 동일 UX 유지.
btnMic.addEventListener('click', () => {
  if (!window.ITDAStt) {
    console.warn('[STT] 어댑터 미로드');
    return;
  }
  chatInput.value = '';
  window.ITDAStt.toggle();
});

// 어댑터 상태 → UI 반영
window.addEventListener('itda:stt:state', (e) => {
  const state = e.detail;
  if (state === 'listening') {
    btnMic.classList.add('recording');
    chatInput.placeholder = '말씀해 주세요...';
  } else {
    btnMic.classList.remove('recording');
    chatInput.placeholder = '번역할 내용을 입력하세요...';
    if (state === 'error') {
      emotionOutput.innerHTML = `<span style="color:#ff4757">음성 인식 오류</span>`;
    }
  }
});

// Web Speech / Whisper 어느 쪽이든 결과는 동일 경로로 처리
window.addEventListener('itda:stt:transcript', (e) => {
  const { text, source } = e.detail || {};
  if (!text) return;
  chatInput.value = text;
  console.info(`[STT] (${source}) "${text}"`);
  sendMessage(text);
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

  // [V3 Priority] 사용자 입력 자체가 V3 JSON 에 있으면 RAG 거치지 않고 바로 재생
  // RAG fuzzy match 로 인해 다른 keyword 가 반환되어 V3 를 놓치는 문제 해결
  if (window.ITDAMotionV3) {
    const direct = await window.ITDAMotionV3.load(text);
    if (direct && direct.keyframes?.length) {
      emotionOutput.innerHTML = `<span style="color:var(--accent-cyan); font-weight:800; font-size:1.1rem;">✨ ${text}</span><br/><span style="font-size:0.75rem; color:var(--text-muted)">실제 KSL 모션 데이터 재생</span>`;
      animateAvatar([], text);
      return;   // RAG 경로 건너뜀
    }
  }

  // [JointCache Priority] V3가 없으면 국립국어원 관절 데이터 시도
  if (window.ITDAMotionNPY) {
    const sldict = await window.ITDAMotionNPY.load(text);
    if (sldict && sldict.frames?.length) {
      emotionOutput.innerHTML = `<span style="color:var(--accent-cyan); font-weight:800; font-size:1.1rem;">✨ ${text}</span><br/><span style="font-size:0.75rem; color:var(--text-muted)">국립국어원 관절 데이터(75 pts) 재생</span>`;
      animateAvatar([], text);
      return;
    }
  }

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
      emotionOutput.innerHTML = `<span style="color:var(--accent-cyan); font-weight:800; font-size:1.1rem;">✨ ${data.keyword}</span> ${emotionsHtml}`;

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
      // RAG 엔진에서 완전히 동떨어진 단어로 판별하여 감정 배열이 비어있다면 동작 생략
      if (data.emotions && data.emotions.length > 0) {
        animateAvatar(data.emotions, data.keyword);
      } else if (data.keyword !== text) {
        animateAvatar(data.emotions, data.keyword);
      }
    }
  } catch (err) {
    console.error("[Search Error]", err);
    // [단독 모드 변환] 
    let fallbackKeyword = getAllKeywords().find(k => text.includes(k) || (k === '고맙습니다' && text.includes('감사')));
    
    if (fallbackKeyword) {
      emotionOutput.innerHTML = `<span style="color:#00F2FE; font-weight:800;">[로컬 매칭] : ${fallbackKeyword}</span>`;
      animateAvatar(['행복'], fallbackKeyword);
    } else {
      emotionOutput.innerHTML = `<span style="color:#ffb8b8">"${text}"에 해당하는 수어 동작을 찾지 못했어요. 다른 단어나 짧은 문장으로 입력해 보세요.</span>`;
      // 모르는 단어일 경우 어색한 임의 동작을 하지 않고 대기 상태 유지
    }
  }
}

// --- 전문 수어 리깅 프리셋 (KSL 6대 수형 × 3 마디 정밀 매핑) ---
// 각 손가락마다 3마디(1=MCP/근위, 2=PIP/중위, 3=DIP/원위) 회전값을 지정.
// Pitch(x) = 굴곡 정도 (0=곧게, π/2≈1.57 = 90도 꺾임)
// 백엔드 handshape_analyzer 가 분류하는 FIST/PALM/POINT/V/L/OK 코드와 1:1 매핑됨.
const FULL_CURL = 1.5;   // 거의 90도 굴곡
const HALF_CURL = 0.8;   // 약 45도 굴곡

// 5개 손가락 × 3 마디 모두 곧게 편 상태 (기본값 템플릿)
const _straightFinger = () => ({
  '1': {x:0, y:0, z:0}, '2': {x:0, y:0, z:0}, '3': {x:0, y:0, z:0},
});
// 5개 손가락 × 3 마디 모두 꽉 접은 상태
const _curledFinger = () => ({
  '1': {x:FULL_CURL, y:0, z:0}, '2': {x:FULL_CURL, y:0, z:0}, '3': {x:HALF_CURL, y:0, z:0},
});

function _buildHandPreset(fingerStates) {
  // fingerStates: {Thumb: 'straight'|'curled', Index: ..., ...}
  const out = {};
  for (const [name, state] of Object.entries(fingerStates)) {
    const pose = state === 'curled' ? _curledFinger() : _straightFinger();
    out[`${name}1`] = pose['1'];
    out[`${name}2`] = pose['2'];
    out[`${name}3`] = pose['3'];
  }
  return out;
}

const RIG_PRESETS = {
  // 주먹: 모든 손가락 접음
  FIST: _buildHandPreset({
    Thumb:'curled', Index:'curled', Middle:'curled', Ring:'curled', Pinky:'curled'
  }),
  // 평손: 모든 손가락 곧게
  PALM: _buildHandPreset({
    Thumb:'straight', Index:'straight', Middle:'straight', Ring:'straight', Pinky:'straight'
  }),
  // 포인팅: 검지만 곧게, 나머지 접음
  POINT: _buildHandPreset({
    Thumb:'curled', Index:'straight', Middle:'curled', Ring:'curled', Pinky:'curled'
  }),
  // V: 검지+중지 곧게, 약지+소지 접음
  V: _buildHandPreset({
    Thumb:'curled', Index:'straight', Middle:'straight', Ring:'curled', Pinky:'curled'
  }),
  // L: 엄지+검지 곧게 (직각), 나머지 접음
  L: _buildHandPreset({
    Thumb:'straight', Index:'straight', Middle:'curled', Ring:'curled', Pinky:'curled'
  }),
  // OK: 엄지+검지 끝이 맞닿음(약간 굽음) + 나머지 곧게
  OK: (() => {
    const p = _buildHandPreset({
      Thumb:'straight', Index:'straight', Middle:'straight', Ring:'straight', Pinky:'straight'
    });
    // 엄지·검지 1-2-3 마디에 살짝 굴곡을 줘 고리 모양 형성
    p.Thumb1 = {x:HALF_CURL*0.6, y:0.4, z:0};
    p.Thumb2 = {x:HALF_CURL*0.6, y:0, z:0};
    p.Index1 = {x:HALF_CURL, y:0.1, z:0};
    p.Index2 = {x:HALF_CURL, y:0, z:0};
    p.Index3 = {x:HALF_CURL*0.5, y:0, z:0};
    return p;
  })(),
};

/**
 * 특정 손(Left/Right)에 수형 프리셋을 본 이름으로 풀어서 적용.
 * 예: FIST 프리셋 → RightHandIndex1/2/3, RightHandMiddle1/2/3, ...
 */
function applyHandPreset(bonesObj, side, presetName) {
  const preset = RIG_PRESETS[presetName];
  if (!preset) return;
  for (const [part, rot] of Object.entries(preset)) {
    bonesObj[side + 'Hand' + part] = rot;
  }
}

// [P0] 백엔드 Handshape 분석 결과를 아바타에 실시간 적용 (follow-along / 교육 모드)
// ws_vision 가 송신하는 itda:hands:analysis 이벤트를 구독.
window.addEventListener('itda:hands:analysis', (e) => {
  const avatar = window.ITDAAvatar5;
  if (!avatar || window.translationModeActive) return; // 번역 재생 중에는 간섭 안 함
  const analyses = e.detail || [];
  const bones = {};
  for (const a of analyses) {
    if (!a || !a.handshape || a.handshape === 'UNKNOWN') continue;
    // MediaPipe handedness 는 카메라 시점이라 좌우 반전됨 → 아바타 기준 반대쪽에 적용
    const side = a.handedness === 'Right' ? 'Left' : 'Right';
    applyHandPreset(bones, side, a.handshape);
  }
  for (const [bName, rot] of Object.entries(bones)) {
    avatar.updateBone(bName, rot, 0.25);
  }
});

// ══════════════════════════════════════════════════════════════
// [Tier 1] MOTION_PROFILES_V1 — 레거시(2단계 · 간이 prop 방식)
// ══════════════════════════════════════════════════════════════
// 4/21 이전 작성. Arm / ForeArm / Spine / Neck 정도만 지정.
// V2 가 없는 단어의 폴백으로 유지. 신규 작성 금지.
const MOTION_PROFILES_V1 = {
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
  "미안하다": [
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

// ══════════════════════════════════════════════════════════════
// [Tier 1] MOTION_PROFILES_V2 — 해부학적 정밀 프로필 (2026-04-22)
// ══════════════════════════════════════════════════════════════
// 규약:
//   각 step = { duration, easing, bones, handshape_R?, handshape_L?, morphs? }
//   bones  : Shoulder / Arm / ForeArm / Hand / Spine / Neck 를 모두 포함
//   handshape_R/L : "PALM"|"FIST"|"POINT"|"V"|"L"|"OK" → RIG_PRESETS 로 자동 확장되어
//                   손가락 5개 × 3마디 = 15개 본이 모두 셋팅됨
//   easing : "linear"|"easeIn"|"easeOut"|"easeInOut"
//
// 완성도 기준: shoulder + arm + forearm + hand + 5finger×3joint + spine/neck 모두 지정
const MOTION_PROFILES_V2 = {
  "안녕하세요": {
    description: "오른손 PALM 을 얼굴 옆에서 가볍게 흔들고 가슴 앞으로 내리며 인사",
    // V2.4: Arm.x 축소(-0.5→-0.3), Arm.y 제거(Euler 복합회전 방지), Step 4 하강 명확
    steps: [
      // 1) 준비: 오른팔 약간만 올리고 팔꿈치 굽혀 손이 얼굴 옆 높이
      {
        duration: 500, easing: "easeOut",
        bones: {
          Spine:         {x: 0.05, y: 0, z: 0},
          Neck:          {x: 0.05, y: 0, z: 0},
          RightArm:      {x: -0.3, y: 0, z: -0.2},   // 살짝 올리고(-17°) 살짝 앞(-11°)
          RightForeArm:  {x: -1.0, y: 0, z: 0},      // 팔꿈치 57° 굽힘
          RightHand:     {x: 0, y: 0.2, z: 0},       // 손목만 살짝 팔목 틀어 손바닥 앞쪽
        },
        handshape_R: "PALM",
        morphs: { mouthSmile: 0.3, eyeWideLeft: 0.1, eyeWideRight: 0.1 }
      },
      // 2) 손 바깥 흔듦
      {
        duration: 350, easing: "easeInOut",
        bones: {
          RightArm:      {x: -0.3, y: 0, z: -0.2},
          RightForeArm:  {x: -1.0, y: 0.25, z: 0},
          RightHand:     {x: 0, y: 0.2, z: 0.1},
        },
        handshape_R: "PALM",
        morphs: { mouthSmile: 0.5 }
      },
      // 3) 손 안쪽 흔듦
      {
        duration: 350, easing: "easeInOut",
        bones: {
          RightArm:      {x: -0.3, y: 0, z: -0.2},
          RightForeArm:  {x: -1.0, y: -0.2, z: 0},
          RightHand:     {x: 0, y: 0.1, z: -0.1},
        },
        handshape_R: "PALM",
        morphs: { mouthSmile: 0.6 }
      },
      // 4) 팔 내림 + 목례 (하강 명확히)
      {
        duration: 600, easing: "easeIn",
        bones: {
          Spine:         {x: 0.1, y: 0, z: 0},
          Neck:          {x: 0.15, y: 0, z: 0},
          RightArm:      {x: 0.1, y: 0, z: -0.3},    // 양수 x = T-pose 아래로 내림
          RightForeArm:  {x: -0.6, y: 0, z: 0},      // 굽힘 완화
          RightHand:     {x: 0, y: 0, z: 0},
        },
        handshape_R: "PALM",
        morphs: { mouthSmile: 0.4 }
      }
    ]
  },

  "고맙습니다": {
    description: "양손 PALM 을 가슴 앞에서 모으고 고개 숙여 감사 표현",
    // V2.4: Arm.x 양수로 T-pose 아래로 내려서 가슴 높이 확보, Arm.z 앞쪽으로
    steps: [
      // 1) 준비: 양팔을 T-pose 아래로 살짝 내리며 앞쪽으로 모음 (LeftArm.z 는 미러링으로 양수)
      {
        duration: 500, easing: "easeOut",
        bones: {
          Spine:         {x: 0.05, y: 0, z: 0},
          Neck:          {x: 0.05, y: 0, z: 0},
          LeftArm:       {x: 0.2, y: 0, z:  0.7},     // Left: z 양수 = 앞
          RightArm:      {x: 0.2, y: 0, z: -0.7},     // Right: z 음수 = 앞 (미러)
          LeftForeArm:   {x: -1.2, y: -0.4, z: 0},
          RightForeArm:  {x: -1.2, y:  0.4, z: 0},
          LeftHand:      {x: 0, y: 0, z: 0},
          RightHand:     {x: 0, y: 0, z: 0},
        },
        handshape_L: "PALM",
        handshape_R: "PALM",
        morphs: { mouthSmile: 0.35 }
      },
      // 2) Peak: 오른손이 왼손등 터치 + 고개 숙임
      {
        duration: 500, easing: "easeInOut",
        bones: {
          Spine:         {x: 0.15, y: 0, z: 0},
          Neck:          {x: 0.2, y: 0, z: 0},
          LeftArm:       {x: 0.2, y: 0, z:  0.7},
          RightArm:      {x: 0.2, y: 0, z: -0.75},
          LeftForeArm:   {x: -1.2, y: -0.4, z: 0},
          RightForeArm:  {x: -1.3, y:  0.55, z: 0},
          LeftHand:      {x: 0.1, y: 0, z: 0},
          RightHand:     {x: 0.15, y: 0, z: 0},
        },
        handshape_L: "PALM",
        handshape_R: "PALM",
        morphs: { mouthSmile: 0.55, eyeWideLeft: 0.2, eyeWideRight: 0.2 }
      },
      // 3) 복귀 전 단계
      {
        duration: 600, easing: "easeIn",
        bones: {
          Spine:         {x: 0.05, y: 0, z: 0},
          Neck:          {x: 0.05, y: 0, z: 0},
          LeftArm:       {x: 0.1, y: 0, z:  0.3},
          RightArm:      {x: 0.1, y: 0, z: -0.3},
          LeftForeArm:   {x: -0.4, y: -0.15, z: 0},
          RightForeArm:  {x: -0.4, y:  0.15, z: 0},
          LeftHand:      {x: 0, y: 0, z: 0},
          RightHand:     {x: 0, y: 0, z: 0},
        },
        handshape_L: "PALM",
        handshape_R: "PALM",
        morphs: { mouthSmile: 0.3 }
      }
    ]
  },

  "사랑합니다": {
    description: "양손 PALM 을 가슴 앞에서 교차하여 포개며 사랑 표현",
    // V2.4: 가슴 높이 확보 위해 Arm.x 양수, ForeArm.y 크게 교차
    steps: [
      // 1) 준비: 양팔을 T-pose 아래 가슴 높이로 내리고 앞으로 (LeftArm.z 미러)
      {
        duration: 500, easing: "easeOut",
        bones: {
          Spine:         {x: 0.05, y: 0, z: 0},
          Neck:          {x: 0, y: 0, z: 0},
          LeftArm:       {x: 0.25, y: 0, z:  0.8},    // Left: z 양수 = 앞
          RightArm:      {x: 0.25, y: 0, z: -0.8},    // Right: z 음수 = 앞
          LeftForeArm:   {x: -1.3, y: -0.3, z: 0},
          RightForeArm:  {x: -1.3, y:  0.3, z: 0},
          LeftHand:      {x: 0, y: 0, z: 0},
          RightHand:     {x: 0, y: 0, z: 0},
        },
        handshape_L: "PALM",
        handshape_R: "PALM",
        morphs: { mouthSmile: 0.4, eyeWideLeft: 0.2, eyeWideRight: 0.2 }
      },
      // 2) Peak: 양손 가슴 중앙에서 교차
      {
        duration: 650, easing: "easeInOut",
        bones: {
          Spine:         {x: 0.07, y: 0, z: 0},
          Neck:          {x: 0.03, y: 0, z: 0},
          LeftArm:       {x: 0.25, y: 0, z:  0.85},
          RightArm:      {x: 0.25, y: 0, z: -0.85},
          LeftForeArm:   {x: -1.5, y: -0.75, z: 0},
          RightForeArm:  {x: -1.5, y:  0.75, z: 0},
          LeftHand:      {x: 0.1, y: 0, z: 0},
          RightHand:     {x: 0.1, y: 0, z: 0},
        },
        handshape_L: "PALM",
        handshape_R: "PALM",
        morphs: { mouthSmile: 0.75, eyeWideLeft: 0.35, eyeWideRight: 0.35 }
      },
      // 3) 복귀 전 단계
      {
        duration: 600, easing: "easeIn",
        bones: {
          Spine:         {x: 0, y: 0, z: 0},
          Neck:          {x: 0, y: 0, z: 0},
          LeftArm:       {x: 0.1, y: 0, z:  0.3},
          RightArm:      {x: 0.1, y: 0, z: -0.3},
          LeftForeArm:   {x: -0.4, y: -0.15, z: 0},
          RightForeArm:  {x: -0.4, y:  0.15, z: 0},
          LeftHand:      {x: 0, y: 0, z: 0},
          RightHand:     {x: 0, y: 0, z: 0},
        },
        handshape_L: "PALM",
        handshape_R: "PALM",
        morphs: { mouthSmile: 0.4 }
      }
    ]
  },

  // ════════════════════════════════════════════════════════════
  // [V2.6+ 자율 생성] 아래 7개는 실측 convention(ZYX, LeftArm.z 미러)
  // 을 적용해 일괄 작성. 사용자 시각 검수 전까지 근사치.
  // 규약:
  //   - RightArm.x 음수=UP 양수=DOWN / RightArm.z 음수=FORWARD
  //   - LeftArm.z 는 부호 반대(Right 음수면 Left 양수)
  //   - ForeArm.x 음수=팔꿈치 UP(얼굴 쪽)
  //   - ForeArm.y: Right 양수=중앙, Left 음수=중앙 (대칭)
  // ════════════════════════════════════════════════════════════

  "미안하다": {
    description: "오른손 PALM 을 가슴(심장 부근)에 대고 상체를 살짝 숙여 사과",
    steps: [
      // 1) 오른손을 가슴 앞으로 올림 (팔꿈치 굽혀 손이 가슴 중앙)
      {
        duration: 500, easing: "easeOut",
        bones: {
          Spine: {x: 0.05, y: 0, z: 0},
          Neck:  {x: 0.05, y: 0, z: 0},
          RightArm:     {x: 0.15, y: 0, z: -0.7},
          RightForeArm: {x: -1.3, y: 0.4, z: 0},
          RightHand:    {x: 0, y: 0, z: 0},
        },
        handshape_R: "PALM",
        morphs: { mouthFrownLeft: 0.2, mouthFrownRight: 0.2, browInnerUp: 0.3 }
      },
      // 2) 가슴에 손 댄 채 상체+목 숙임 (사과)
      {
        duration: 600, easing: "easeInOut",
        bones: {
          Spine: {x: 0.22, y: 0, z: 0},
          Neck:  {x: 0.28, y: 0, z: 0},
          RightArm:     {x: 0.15, y: 0, z: -0.7},
          RightForeArm: {x: -1.3, y: 0.4, z: 0},
          RightHand:    {x: 0.1, y: 0, z: 0},
        },
        handshape_R: "PALM",
        morphs: { mouthFrownLeft: 0.4, mouthFrownRight: 0.4, browInnerUp: 0.5, Sad: 0.6 }
      },
      // 3) 천천히 복귀
      {
        duration: 700, easing: "easeIn",
        bones: {
          Spine: {x: 0.05, y: 0, z: 0},
          Neck:  {x: 0.05, y: 0, z: 0},
          RightArm:     {x: 0.08, y: 0, z: -0.3},
          RightForeArm: {x: -0.5, y: 0.15, z: 0},
          RightHand:    {x: 0, y: 0, z: 0},
        },
        handshape_R: "PALM",
        morphs: { Sad: 0.3 }
      }
    ]
  },

  "네": {
    description: "오른 주먹 FIST 를 가슴 높이에서 위아래로 부드럽게 끄덕임(긍정)",
    steps: [
      // 1) 오른손을 가슴 높이로 올림 (주먹)
      {
        duration: 350, easing: "easeOut",
        bones: {
          Neck: {x: 0.1, y: 0, z: 0},
          RightArm:     {x: 0.1, y: 0, z: -0.5},
          RightForeArm: {x: -1.0, y: 0.2, z: 0},
          RightHand:    {x: 0, y: 0, z: 0},
        },
        handshape_R: "FIST",
        morphs: { mouthSmile: 0.25 }
      },
      // 2) 아래로 끄덕 (고개도 함께)
      {
        duration: 300, easing: "easeInOut",
        bones: {
          Neck: {x: 0.25, y: 0, z: 0},
          RightArm:     {x: 0.25, y: 0, z: -0.5},
          RightForeArm: {x: -0.7, y: 0.2, z: 0},
          RightHand:    {x: 0.2, y: 0, z: 0},
        },
        handshape_R: "FIST",
        morphs: { mouthSmile: 0.3 }
      },
      // 3) 다시 위로
      {
        duration: 300, easing: "easeInOut",
        bones: {
          Neck: {x: 0.05, y: 0, z: 0},
          RightArm:     {x: 0.1, y: 0, z: -0.5},
          RightForeArm: {x: -1.0, y: 0.2, z: 0},
          RightHand:    {x: 0, y: 0, z: 0},
        },
        handshape_R: "FIST",
        morphs: { mouthSmile: 0.35 }
      }
    ]
  },

  "아니오": {
    description: "오른손 PALM 을 얼굴 옆에서 좌우로 크게 흔들며 부정",
    steps: [
      // 1) 손을 얼굴 옆으로 올림 (손바닥 앞)
      {
        duration: 400, easing: "easeOut",
        bones: {
          RightArm:     {x: -0.4, y: 0, z: -0.25},
          RightForeArm: {x: -1.1, y: 0, z: 0},
          RightHand:    {x: 0, y: 0.2, z: 0},
        },
        handshape_R: "PALM",
        morphs: { browLowererLeft: 0.3, browLowererRight: 0.3 }
      },
      // 2) 바깥으로 흔듦 (크게)
      {
        duration: 300, easing: "easeInOut",
        bones: {
          Neck: {x: 0, y: -0.15, z: 0},
          RightArm:     {x: -0.4, y: 0, z: -0.25},
          RightForeArm: {x: -1.1, y: 0.5, z: 0},
          RightHand:    {x: 0, y: 0.3, z: 0.15},
        },
        handshape_R: "PALM",
        morphs: { browLowererLeft: 0.4, browLowererRight: 0.4 }
      },
      // 3) 안쪽으로 흔듦
      {
        duration: 300, easing: "easeInOut",
        bones: {
          Neck: {x: 0, y: 0.15, z: 0},
          RightArm:     {x: -0.4, y: 0, z: -0.25},
          RightForeArm: {x: -1.1, y: -0.4, z: 0},
          RightHand:    {x: 0, y: -0.25, z: -0.15},
        },
        handshape_R: "PALM",
        morphs: { browLowererLeft: 0.4, browLowererRight: 0.4 }
      },
      // 4) 한 번 더 바깥 (좌우로 총 2회 흔듦 효과)
      {
        duration: 300, easing: "easeInOut",
        bones: {
          Neck: {x: 0, y: -0.1, z: 0},
          RightArm:     {x: -0.4, y: 0, z: -0.25},
          RightForeArm: {x: -1.1, y: 0.4, z: 0},
          RightHand:    {x: 0, y: 0.2, z: 0.1},
        },
        handshape_R: "PALM",
        morphs: { browLowererLeft: 0.2, browLowererRight: 0.2 }
      }
    ]
  },

  "도와주세요": {
    description: "왼손 PALM(받침) 위에 오른 주먹을 올려 위로 들어올리며 도움 청함",
    steps: [
      // 1) 왼손을 손바닥 위로 향하게(받침) 가슴 앞 중앙으로
      {
        duration: 500, easing: "easeOut",
        bones: {
          Spine: {x: 0.03, y: 0, z: 0},
          LeftArm:      {x: 0.3, y: 0, z:  0.8},
          RightArm:     {x: 0.3, y: 0, z: -0.8},
          LeftForeArm:  {x: -1.1, y: -0.4, z: 0},
          RightForeArm: {x: -1.1, y:  0.4, z: 0},
          LeftHand:     {x: -0.2, y: 0, z: 0},  // 손바닥 위로 향하게 wrist 회전
          RightHand:    {x: 0, y: 0, z: 0},
        },
        handshape_L: "PALM",
        handshape_R: "FIST",
        morphs: { browInnerUp: 0.3, mouthFrownLeft: 0.15 }
      },
      // 2) 오른 주먹이 왼손 위에 얹힘, 함께 살짝 올라감 (부탁의 제스처)
      {
        duration: 600, easing: "easeInOut",
        bones: {
          Spine: {x: 0.03, y: 0, z: 0},
          LeftArm:      {x: 0.15, y: 0, z:  0.8},
          RightArm:     {x: 0.15, y: 0, z: -0.8},
          LeftForeArm:  {x: -1.15, y: -0.4, z: 0},
          RightForeArm: {x: -1.15, y:  0.4, z: 0},
          LeftHand:     {x: -0.2, y: 0, z: 0},
          RightHand:    {x: 0, y: 0, z: 0},
        },
        handshape_L: "PALM",
        handshape_R: "FIST",
        morphs: { browInnerUp: 0.5, Sad: 0.3 }
      },
      // 3) 복귀
      {
        duration: 600, easing: "easeIn",
        bones: {
          Spine: {x: 0, y: 0, z: 0},
          LeftArm:      {x: 0.1, y: 0, z:  0.3},
          RightArm:     {x: 0.1, y: 0, z: -0.3},
          LeftForeArm:  {x: -0.4, y: -0.1, z: 0},
          RightForeArm: {x: -0.4, y:  0.1, z: 0},
          LeftHand:     {x: 0, y: 0, z: 0},
          RightHand:    {x: 0, y: 0, z: 0},
        },
        handshape_L: "PALM",
        handshape_R: "PALM",
        morphs: { browInnerUp: 0.2 }
      }
    ]
  },

  "기뻐요": {
    description: "양손 PALM 을 가슴에서 바깥 위로 펼치며 기쁨 표현",
    steps: [
      // 1) 양손을 가슴 앞에 모음
      {
        duration: 400, easing: "easeOut",
        bones: {
          LeftArm:      {x: 0.2, y: 0, z:  0.6},
          RightArm:     {x: 0.2, y: 0, z: -0.6},
          LeftForeArm:  {x: -1.1, y: -0.3, z: 0},
          RightForeArm: {x: -1.1, y:  0.3, z: 0},
        },
        handshape_L: "PALM",
        handshape_R: "PALM",
        morphs: { mouthSmile: 0.5 }
      },
      // 2) 양손을 바깥 위로 활짝 펼침
      {
        duration: 550, easing: "easeInOut",
        bones: {
          Spine: {x: -0.05, y: 0, z: 0},  // 상체 약간 펴짐
          LeftArm:      {x: -0.3, y: 0, z:  0.3},  // 위+바깥
          RightArm:     {x: -0.3, y: 0, z: -0.3},
          LeftForeArm:  {x: -0.5, y:  0.1, z: 0},
          RightForeArm: {x: -0.5, y: -0.1, z: 0},
          LeftHand:     {x: 0, y: 0, z: 0},
          RightHand:    {x: 0, y: 0, z: 0},
        },
        handshape_L: "PALM",
        handshape_R: "PALM",
        morphs: { mouthSmile: 0.9, eyeWideLeft: 0.3, eyeWideRight: 0.3 }
      },
      // 3) 복귀
      {
        duration: 600, easing: "easeIn",
        bones: {
          Spine: {x: 0, y: 0, z: 0},
          LeftArm:      {x: 0.1, y: 0, z:  0.2},
          RightArm:     {x: 0.1, y: 0, z: -0.2},
          LeftForeArm:  {x: -0.3, y: 0, z: 0},
          RightForeArm: {x: -0.3, y: 0, z: 0},
        },
        handshape_L: "PALM",
        handshape_R: "PALM",
        morphs: { mouthSmile: 0.5 }
      }
    ]
  },

  "슬퍼요": {
    description: "양손을 얼굴 앞에서 천천히 아래로 내리며 슬픔(눈물 흐르는 이미지)",
    steps: [
      // 1) 손을 얼굴 옆으로 올림
      {
        duration: 500, easing: "easeOut",
        bones: {
          Spine: {x: 0.05, y: 0, z: 0},
          Neck:  {x: 0.1, y: 0, z: 0},
          LeftArm:      {x: -0.3, y: 0, z:  0.25},
          RightArm:     {x: -0.3, y: 0, z: -0.25},
          LeftForeArm:  {x: -1.3, y: -0.1, z: 0},
          RightForeArm: {x: -1.3, y:  0.1, z: 0},
        },
        handshape_L: "PALM",
        handshape_R: "PALM",
        morphs: { mouthFrownLeft: 0.4, mouthFrownRight: 0.4, browInnerUp: 0.6, Sad: 0.7 }
      },
      // 2) 천천히 아래로 내림 (가슴 → 허리)
      {
        duration: 800, easing: "easeInOut",
        bones: {
          Spine: {x: 0.1, y: 0, z: 0},
          Neck:  {x: 0.2, y: 0, z: 0},
          LeftArm:      {x: 0.5, y: 0, z:  0.4},
          RightArm:     {x: 0.5, y: 0, z: -0.4},
          LeftForeArm:  {x: -0.7, y: -0.2, z: 0},
          RightForeArm: {x: -0.7, y:  0.2, z: 0},
        },
        handshape_L: "PALM",
        handshape_R: "PALM",
        morphs: { mouthFrownLeft: 0.6, mouthFrownRight: 0.6, browInnerUp: 0.8, Sad: 0.9 }
      },
      // 3) 복귀
      {
        duration: 700, easing: "easeIn",
        bones: {
          Spine: {x: 0.05, y: 0, z: 0},
          Neck:  {x: 0.1, y: 0, z: 0},
          LeftArm:      {x: 0.2, y: 0, z:  0.2},
          RightArm:     {x: 0.2, y: 0, z: -0.2},
          LeftForeArm:  {x: -0.3, y: 0, z: 0},
          RightForeArm: {x: -0.3, y: 0, z: 0},
        },
        handshape_L: "PALM",
        handshape_R: "PALM",
        morphs: { mouthFrownLeft: 0.3, Sad: 0.4 }
      }
    ]
  },

  "이름": {
    description: "오른 V 수형(검지+중지)을 이마 옆에 대었다가 떼며 이름 질문/지칭",
    steps: [
      // 1) V 수형을 이마 옆으로
      {
        duration: 400, easing: "easeOut",
        bones: {
          RightArm:     {x: -0.4, y: 0, z: -0.2},
          RightForeArm: {x: -1.3, y: 0.1, z: 0},
          RightHand:    {x: 0, y: 0.1, z: 0},
        },
        handshape_R: "V",
        morphs: { eyeWideLeft: 0.2, eyeWideRight: 0.2 }
      },
      // 2) 이마에 가볍게 터치
      {
        duration: 300, easing: "easeInOut",
        bones: {
          RightArm:     {x: -0.5, y: 0, z: -0.2},
          RightForeArm: {x: -1.5, y: 0.1, z: 0},
          RightHand:    {x: 0.1, y: 0.1, z: 0},
        },
        handshape_R: "V",
        morphs: { eyeWideLeft: 0.3, eyeWideRight: 0.3 }
      },
      // 3) 앞쪽으로 내밀기 (질문 제스처)
      {
        duration: 450, easing: "easeInOut",
        bones: {
          RightArm:     {x: -0.1, y: 0, z: -0.7},
          RightForeArm: {x: -0.6, y: 0.1, z: 0},
          RightHand:    {x: 0, y: 0, z: 0},
        },
        handshape_R: "V",
        morphs: { browInnerUp: 0.4, mouthSmile: 0.2 }
      }
    ]
  },
};

// ── 프로필 셀렉터: V2 우선, 없으면 V1 폴백 ──────────────────
// window.ITDAMotion.version = 'v2'|'v1' 로 강제 지정 가능 (A/B 비교용)
window.ITDAMotion = window.ITDAMotion || { version: 'v2' };

function getProfile(keyword) {
  const v = window.ITDAMotion.version;
  if (v !== 'v1' && MOTION_PROFILES_V2[keyword]) {
    return { source: 'v2', steps: MOTION_PROFILES_V2[keyword].steps };
  }
  const legacy = MOTION_PROFILES_V1[keyword];
  if (legacy) return { source: 'v1', steps: legacy };
  return null;
}

function getAllKeywords() {
  // V2 키 + V1 키 (중복 제거), GENERIC/default 는 외부 검색에서 제외
  const excluded = new Set(["GENERIC_EXPLANATION", "default"]);
  const set = new Set([...Object.keys(MOTION_PROFILES_V2), ...Object.keys(MOTION_PROFILES_V1)]);
  return [...set].filter(k => !excluded.has(k));
}

// ── Easing 함수 테이블 ──────────────────────────────────────
const EASING_FNS = {
  linear:    t => t,
  easeIn:    t => t * t,
  easeOut:   t => t * (2 - t),
  easeInOut: t => t < 0.5 ? 2*t*t : -1 + (4 - 2*t)*t,
};

// ── Step 전처리: handshape_R/L 문자열을 15개 손가락 본으로 펼치기 ──
function _expandStep(stepData) {
  const bones = { ...(stepData.bones || {}) };
  if (stepData.handshape_R) applyHandPreset(bones, 'Right', stepData.handshape_R);
  if (stepData.handshape_L) applyHandPreset(bones, 'Left',  stepData.handshape_L);
  return { ...stepData, bones };
}

// [감정명 -> 아바타 모프] 매핑 헬퍼
const EMOTION_MORPH_MAP = {
  "기쁨": { mouthSmile: 0.5, eyeWideLeft: 0.1 },
  "행복": { mouthSmile: 0.7, eyeWideLeft: 0.2 },
  "슬픔": { Sad: 0.6, mouthFrownLeft: 0.4 },
  "긴박": { Surprised: 0.7, eyeWideLeft: 0.5 },
  "감사": { mouthSmile: 0.4, Neck: {x:0.1} },
  "정보전달": { Surprised: 0.1, mouthSmile: 0.1 }
};

// 감정 morph 적용 헬퍼 추출
function _applyEmotions(emotions, avatar) {
  if (!emotions?.length) return;
  for (const emName of emotions) {
    const effect = EMOTION_MORPH_MAP[emName];
    if (effect) {
      for (const [m, v] of Object.entries(effect)) {
        if (typeof v === 'number') avatar.setMorphTarget(m, v);
      }
    }
  }
}

/**
 * 3D 수어 애니메이션 엔진 (Quaternion Slerp 기반)
 */
async function animateAvatar(emotions, keyword) {
  const avatar = window.ITDAAvatar5;
  if (!avatar) return;

  // [Debug] Idle 애니메이션이 팔 본을 덮어쓰는 것을 방지하기 위해 번역 재생 직전 정지
  avatar.stopIdle?.();

  // [Option A / V3] MediaPipe 로 추출된 keyframe JSON 이 있으면 우선 재생
  if (window.ITDAMotionV3 && window.ITDAMotion?.version !== 'v1') {
    try {
      const motion = await window.ITDAMotionV3.load(keyword);
      if (motion && motion.keyframes?.length) {
        _applyEmotions(emotions, avatar);
        window.translationModeActive = true;
        await window.ITDAMotionV3.play(keyword);
        return;
      }
    } catch (e) {
      console.warn('[Motion] V3 로드 실패, V2 폴백:', e.message);
    }
  }

  // [NEW] 국립국어원 관절 데이터 (75 pts) 재생 시도
  if (window.ITDAMotionNPY) {
    try {
      const joints = await window.ITDAMotionNPY.load(keyword);
      if (joints && joints.frames?.length) {
        _applyEmotions(emotions, avatar);
        window.translationModeActive = true;
        await window.ITDAMotionNPY.play(keyword);
        return; 
      }
    } catch (e) {
      console.warn('[Motion] NPY 로드 실패:', e.message);
    }
  }

  window.translationModeActive = true;
  if (translationTimeout) clearTimeout(translationTimeout);

  // 1. 단어 기반 프로필 찾기 — V2(해부학) 우선, V1(레거시) 폴백, Fuzzy Match 포함
  let resolved = getProfile(keyword);
  let resolvedKey = keyword;
  if (!resolved) {
    const foundKey = getAllKeywords().find(k => keyword.includes(k));
    resolved = foundKey ? getProfile(foundKey) : null;
    if (foundKey) resolvedKey = foundKey;
  }
  if (!resolved) {
    // 둘 다 없으면 GENERIC_EXPLANATION (V1 전용)
    resolved = { source: 'v1', steps: MOTION_PROFILES_V1["GENERIC_EXPLANATION"] };
    resolvedKey = "GENERIC_EXPLANATION";
  }
  const profile = resolved.steps;
  console.log(`[Motion] "${keyword}" → "${resolvedKey}" (source=${resolved.source})`);

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
   * 단계별 동작 실행 (Quaternion Slerp + handshape_R/L 자동 확장 + easing 함수)
   */
  const playStep = async (rawStep) => {
    // V2: handshape 문자열 → 15개 손가락 본으로 확장 (V1 은 변화 없음)
    const stepData = _expandStep(rawStep);
    const duration = stepData.duration || 500;
    const easeFn = EASING_FNS[stepData.easing] || EASING_FNS.easeOut;
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
          // [V2.5 Fix] Euler order를 ZYX 로 명시: Z(forward)를 먼저 적용하고
          // 그 결과 방향에서 X(up/down)를 적용해야 x 성분이 손실되지 않음.
          // 기본 XYZ 순서에선 X 먼저 적용되어 local Z가 기울어지면서 x 효과 희석됨.
          const eulerObj = new THREE.Euler(euler.x, euler.y || 0, euler.z || 0, 'ZYX');
          targetQuats[bName] = new THREE.Quaternion().setFromEuler(eulerObj);
        }
      }
    }

    return new Promise((resolve) => {
      function update(now) {
        const elapsed = now - startTime;
        const progress = Math.min(elapsed / duration, 1.0);
        const ease = easeFn(progress);

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
    // [Tier1] 마지막 재생 단어를 UI 쪽으로 통지 → A/B 토글 시 즉시 재생 가능
    window.dispatchEvent(new CustomEvent('itda:motion:played', {
      detail: { keyword: resolvedKey, source: resolved.source, emotions }
    }));
  } catch (err) {
    console.error('[Motion] Error:', err);
    avatar.reset();
    window.translationModeActive = false;
  }
}

// ── [Tier1] 외부에서 호출 가능한 리플레이 API (V2↔V1 비교용) ──
window.ITDATranslator = {
  replay(keyword) {
    if (!keyword) return;
    animateAvatar([], keyword);
  },
  getVersion() { return window.ITDAMotion?.version || 'v2'; },
  getV2Words() { return Object.keys(MOTION_PROFILES_V2); },
};

// ══════════════════════════════════════════════════════════════
// [DEBUG] Rig 축 Convention 실측 도구 — console 에서 호출
// ══════════════════════════════════════════════════════════════
// 목적: 수화 모션이 계속 틀리는 이유를 좌표계 오해로 가정하고,
//       본 하나만 한 축으로 회전시켜 시각적 결과를 관찰해 convention 확정.
//
// 사용 예:
//   ITDADebug.listBones('arm')           // 팔 관련 본 이름 나열
//   ITDADebug.rotate('RightArm','x',-0.5) // 단일 본·단일 축 회전
//   ITDADebug.reset()                      // 모든 본 복구
//   ITDADebug.stopIdle()                   // Idle 클립 정지 (간섭 제거)
window.ITDADebug = {
  listBones(filter = '') {
    const avatar = window.ITDAAvatar5;
    if (!avatar) return '[Debug] 아바타 미로드';
    const all = Object.keys(avatar.bones);
    const re = filter ? new RegExp(filter, 'i') : null;
    const hit = re ? all.filter(n => re.test(n)) : all;
    console.table(hit);
    return hit;
  },
  rotate(boneName, axis, value) {
    const avatar = window.ITDAAvatar5;
    if (!avatar) return '[Debug] 아바타 미로드';
    const bone = avatar.bones[boneName]
            || avatar.bones['mixamorig:' + boneName]
            || avatar.bones['mixamorig' + boneName];
    if (!bone) {
      console.warn(`[Debug] 본 찾기 실패: ${boneName}`);
      return null;
    }
    const rot = { x: 0, y: 0, z: 0 };
    rot[axis] = value;
    // [V2.5] 엔진과 동일한 ZYX 순서로 적용
    bone.rotation.set(rot.x, rot.y, rot.z, 'ZYX');
    console.info(`[Debug] ${bone.name}.${axis} = ${value} (order=ZYX) 적용`);
    return bone.name;
  },
  // [V2.5] 다축 조합 테스트용
  rotateAll(boneName, x = 0, y = 0, z = 0) {
    const avatar = window.ITDAAvatar5;
    if (!avatar) return;
    const bone = avatar.bones[boneName]
            || avatar.bones['mixamorig:' + boneName];
    if (!bone) return console.warn(`[Debug] 본 없음: ${boneName}`);
    bone.rotation.set(x, y, z, 'ZYX');
    console.info(`[Debug] ${bone.name} = (${x},${y},${z}) ZYX 적용`);
  },
  reset() {
    const avatar = window.ITDAAvatar5;
    if (!avatar) return;
    avatar.reset();
    console.info('[Debug] 모든 본 초기 상태 복구');
  },
  stopIdle() {
    // avatar.js 가 export 하지 않은 mixer 에 접근하기 위한 해킹
    // Three.js scene 에서 찾아서 모든 action 정지
    const avatar = window.ITDAAvatar5;
    if (!avatar || !avatar.bones) return '[Debug] 아바타 미로드';
    const firstBone = Object.values(avatar.bones)[0];
    // root 쪽으로 올라가 model 찾기
    let node = firstBone;
    while (node.parent) node = node.parent;
    // Three.js scene 찾기 - userData 에 mixer 없으므로 mixer 직접 접근 어려움
    // 대신 traverse 로 animationClips 확인
    console.info('[Debug] Idle mixer 는 translator.js 에서 직접 정지 필요. stopAnim() 사용 권장.');
  },
};

console.info('[Debug] ITDADebug 준비됨. 콘솔에서 ITDADebug.listBones("arm") 또는 ITDADebug.rotate("RightArm","z",-0.5) 시도.');
