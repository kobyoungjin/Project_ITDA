/**
 * education.js ─ [⑥ Education Mode] KSL 초급 5단어 학습 MVP
 *
 * ■ 목표
 *   사용자가 카메라 앞에서 수어를 따라 하면, 백엔드 handshape/pose 분석 결과와
 *   정답 프로필(LESSON_PROFILES)을 비교해 실시간 피드백을 제공.
 *
 * ■ 구조
 *   - LESSON_PROFILES : 단어 → {expected_handshape, expected_region, hint}
 *   - LessonEngine    : 현재 목표 단어, 판정 상태(waiting|trying|success|fail) 관리
 *   - itda:hands:analysis · itda:pose:analysis · itda:motion:phase 이벤트 구독
 *   - itda:lesson:feedback 이벤트 발행 → index.html 이 UI 에 반영
 *
 * ■ 활성화 조건
 *   window.ITDAEducation.start(word) 호출 시에만 판정 로직 실행.
 *   평소(번역 모드)에는 건드리지 않음.
 */

// ── 초급 5단어 LESSON 프로필 ──────────────────────────────────
// 각 항목은 "handshape 수형" + "wrist_region 위치 구역" + 선택적 "movement 키워드"
// 로 구성. 현재 인식기 정확도를 감안해 관대한 조건으로 설정.
export const LESSON_PROFILES = {
  "안녕하세요": {
    emoji: "👋",
    hint: "오른손을 펴서(PALM) 얼굴 옆에서 가볍게 흔들어 보세요.",
    expected: {
      handshapes_any: ["PALM"],     // 두 손 중 하나라도 PALM
      region_R: ["얼굴", "얼굴 위"], // 오른손목이 얼굴 근처
    },
  },
  "주먹": {
    emoji: "✊",
    hint: "한 손을 주먹(FIST)으로 쥐어 가슴 앞에 위치시키세요.",
    expected: {
      handshapes_any: ["FIST"],
      region_R: ["가슴"],
    },
  },
  "하나": {
    emoji: "☝️",
    hint: "검지만 펴서(POINT) 앞으로 향하게 해주세요.",
    expected: {
      handshapes_any: ["POINT"],
    },
  },
  "승리": {
    emoji: "✌️",
    hint: "검지와 중지를 펴서(V) 위로 향하게 해보세요.",
    expected: {
      handshapes_any: ["V"],
      region_R: ["얼굴", "얼굴 위"],
    },
  },
  "좋아요": {
    emoji: "👌",
    hint: "엄지와 검지로 동그라미를 만들어(OK) 가슴 앞에 보이세요.",
    expected: {
      handshapes_any: ["OK"],
      region_R: ["가슴"],
    },
  },
};

// ── 판정 로직 ───────────────────────────────────────────────
function _matches(expected, handshapes, poseAnalysis) {
  const reasons = [];
  let ok = true;

  // 수형 비교 — 어떤 손이든 만족하면 OK
  if (expected.handshapes_any) {
    const got = handshapes.map(h => h.handshape).filter(Boolean);
    const hit = expected.handshapes_any.some(s => got.includes(s));
    if (!hit) {
      ok = false;
      reasons.push(`수형이 달라요 (감지됨: ${got.join(',') || '없음'})`);
    }
  }

  // 손목 구역 비교 (오른손 기준)
  if (expected.region_R && poseAnalysis) {
    const region = poseAnalysis.wrist_region_R;
    if (!expected.region_R.includes(region)) {
      ok = false;
      reasons.push(`손 위치가 달라요 (지금: ${region || '감지 안됨'})`);
    }
  }

  return { ok, reasons };
}

// ── 런타임 상태 ─────────────────────────────────────────────
const state = {
  targetWord: null,        // 현재 학습 단어
  latestHands: [],         // 최신 hand_analyses
  latestPose: null,        // 최신 pose_analysis
  status: "idle",          // idle | trying | success
  lastFeedback: "",
};

function _emit(detail) {
  window.dispatchEvent(new CustomEvent('itda:lesson:feedback', { detail }));
}

function _evaluate() {
  if (!state.targetWord) return;
  const profile = LESSON_PROFILES[state.targetWord];
  if (!profile) return;

  const { ok, reasons } = _matches(profile.expected, state.latestHands, state.latestPose);
  if (ok) {
    state.status = "success";
    state.lastFeedback = `정답! "${state.targetWord}" ${profile.emoji}`;
    _emit({ status: "success", word: state.targetWord, message: state.lastFeedback });
  } else {
    state.status = "trying";
    state.lastFeedback = reasons.join(' · ') || "조금만 더!";
    _emit({ status: "trying", word: state.targetWord, message: state.lastFeedback, reasons });
  }
}

// ── 이벤트 구독 ─────────────────────────────────────────────
window.addEventListener('itda:hands:analysis', (e) => {
  state.latestHands = e.detail || [];
  if (state.targetWord && state.status !== "success") _evaluate();
});

window.addEventListener('itda:pose:analysis', (e) => {
  state.latestPose = e.detail || null;
});

// motion_phase === 'stable' 일 때만 최종 판정 확정 (오판 방지)
window.addEventListener('itda:motion:phase', (e) => {
  if (e.detail?.phase === 'stable' && state.targetWord) {
    _evaluate();  // stable 시점 재평가 → UI 에 "확정" 느낌 강화
  }
});

// ── 공개 API ────────────────────────────────────────────────
window.ITDAEducation = {
  /** 학습 시작: 목표 단어 설정. LESSON_PROFILES 에 없으면 false 반환. */
  start(word) {
    if (!LESSON_PROFILES[word]) {
      console.warn(`[Lesson] 지원하지 않는 단어: ${word}`);
      return false;
    }
    state.targetWord = word;
    state.status = "trying";
    state.lastFeedback = "";
    _emit({
      status: "started",
      word,
      hint: LESSON_PROFILES[word].hint,
      emoji: LESSON_PROFILES[word].emoji,
    });
    return true;
  },

  /** 학습 종료 → idle 로 복귀 */
  stop() {
    state.targetWord = null;
    state.status = "idle";
    _emit({ status: "stopped" });
  },

  getState() {
    return { ...state };
  },

  getWords() {
    return Object.keys(LESSON_PROFILES);
  },
};

console.info('[Education] 학습 모드 준비 완료. 단어:', Object.keys(LESSON_PROFILES).join(', '));
