"""
slm_agent.py ─ [P1] KSL(한국 수어) 통역사 SLM 에이전트

이전 버전은 낙서 감지/보안 경고 로직이 잘못 주입되어 있었습니다.
본 모듈은 Handshape/Pose 분석 결과를 소비해 한국 수어 단어 1개를 예측합니다.

구성:
  - predict_fast(raw)   : Track 1 초고속 예측. Ollama(gemma3:4b) 호출.
                          Ollama 미가용 시 rule-based fallback 로 폴백.
  - predict_with_rag(fast_pred, rag_ctx) : Track 3 최종 온기 합성.
                          RAG 로 찾은 수어 설명/감정을 넣어 따뜻한 문장으로 다듬음.

입력 계약:
  raw["meta_features"] = {
    "handshapes":         List[str],     # ex) ["POINT"]
    "handshape_summary":  str,           # 자연어
    "pose_summary":       str,           # 자연어
    "wrist_regions":      [right, left], # ex) ["얼굴", "가슴"]
    "movement":           str,           # ex) "손목이 위에서 아래로 내려옵니다."
    "hand_count":         int,
  }
"""

from __future__ import annotations

import aiohttp
from typing import Any, Dict


# ── Rule-based fallback 사전 ─────────────────────────────────
# (handshape 1개 or 2개, wrist_region_R, movement 힌트) → 대표 KSL 단어
# Ollama 가 꺼져 있거나 응답이 이상할 때만 사용.
RULE_HINTS = [
    # 수형 · 구역 · 이동 힌트 · 매칭 단어
    (("PALM",),       "얼굴",   "아래",  "안녕하세요"),
    (("PALM", "PALM"),"가슴",   None,    "고맙습니다"),
    (("FIST",),       "얼굴",   None,    "미안합니다"),
    (("FIST",),       "가슴",   None,    "힘내세요"),
    (("POINT",),      "얼굴",   None,    "어디에요"),
    (("POINT",),      "가슴",   None,    "이름이 뭐예요"),
    (("V",),          "얼굴",   None,    "또 만나요"),
    (("L",),          "가슴",   None,    "얼마예요"),
    (("OK",),         "가슴",   None,    "좋아하다"),
    (("PALM", "PALM"),"얼굴",   None,    "사랑합니다"),
    (("PALM",),       "가슴",   "아래",  "괜찮아요"),
    
    # [추가] 핵심 일상 어휘
    (("POINT", "POINT"), "가슴", None,   "수어"),        # 수어 (검지 맞대고 돌리기)
    (("POINT",),         "얼굴", "위",   "학교"),        # 학교
    (("POINT",),         "얼굴", "아래", "어머니"),      # 어머니 (볼 터치)
    (("FIST",),          "얼굴", "위",   "아버지"),      # 아버지 (이마 터치)
    (("PALM",),          "가슴", None,   "나"),          # 나
    (("POINT",),         "가슴", None,   "너"),          # 너
    (("PALM", "PALM"),   "가슴", "아래", "밥"),          # 밥 (먹는 동작)
]


def _rule_based_predict(meta: Dict[str, Any]) -> str:
    shapes = tuple(meta.get("handshapes") or [])
    regions = meta.get("wrist_regions") or []
    right_region = regions[0] if regions else ""
    movement = (meta.get("movement") or "").lower()

    for req_shapes, req_region, req_move, word in RULE_HINTS:
        # 수형 매칭: 순서 무관, 개수 일치
        if sorted(req_shapes) != sorted(shapes):
            continue
        if req_region and req_region not in right_region:
            continue
        if req_move and req_move not in movement:
            continue
        return word

    # 손이 감지되지 않으면 기본 유휴 상태
    if not shapes:
        return "대기 중"
    # 어디에도 매칭 안 되면 수형 이름만 반환
    return f"미인식({'+'.join(shapes)})"


def _clean_single_word(text: str) -> str:
    """SLM 출력에서 한 단어만 추출. 따옴표/공백/설명 제거."""
    if not text:
        return ""
    # 마크다운 · 따옴표 · 줄바꿈 제거
    for ch in ('"', "'", "`", "*", "\n", "\r", "\t"):
        text = text.replace(ch, " ")
    # 첫 줄의 첫 번째 토큰만
    parts = [p for p in text.split() if p]
    return parts[0][:20] if parts else ""


class SlmAgent:
    def __init__(self, model_name: str = "qwen3:4b", timeout_fast: int = 30, timeout_rag: int = 30):
        self.model_name = model_name
        self.api_url = "http://localhost:11434/api/generate"
        self.timeout_fast = timeout_fast
        self.timeout_rag = timeout_rag

    async def _call_ollama(self, prompt: str, timeout: int = 7) -> str:
        try:
            async with aiohttp.ClientSession() as session:
                payload = {"model": self.model_name, "prompt": prompt, "stream": False}
                async with session.post(self.api_url, json=payload, timeout=timeout) as resp:
                    if resp.status != 200:
                        return ""
                    data = await resp.json()
                    return (data.get("response") or "").strip()
        except Exception as e:
            print(f"[SlmAgent] Ollama 호출 실패(fallback 사용): {e}")
            return ""

    async def predict_fast(self, raw_data: dict) -> str:
        """
        Track 1: 손 수형 + 상체 포즈 + 이동 요약으로 KSL 단어 1개 추측.
        항상 **문자열** 을 반환 (이전 dict 반환은 계약 오류였음).
        """
        meta = raw_data.get("meta_features") or {}

        prompt = (
            "당신은 한국 수어(KSL) 통역사입니다. 아래 관찰 정보를 보고 "
            "가장 가능성 높은 한국어 단어 **한 개** 만 출력하세요. 설명 금지.\n"
            f"- 손 수형: {meta.get('handshape_summary', '감지 안됨')}\n"
            f"- 상체 포즈: {meta.get('pose_summary', '감지 안됨')}\n"
            f"- 손 이동: {meta.get('movement', '정지')}\n"
            "예시 단어 후보: 안녕하세요, 고맙습니다, 미안합니다, 사랑합니다, "
            "힘내세요, 또 만나요, 어디에요, 괜찮아요, 도와주세요, 이름이 뭐예요\n"
            "정답:"
        )

        raw_text = await self._call_ollama(prompt, timeout=self.timeout_fast)
        word = _clean_single_word(raw_text)

        # SLM 응답이 비었거나 수상하면 규칙 기반 폴백
        if not word or len(word) < 2 or word.startswith("미인식"):
            word = _rule_based_predict(meta)

        return word

    async def predict_with_rag(self, fast_prediction: str, rag_context: dict) -> str:
        """
        Track 3: 1차 예측 단어 + RAG 결과(따뜻한 설명/감정)를 결합해
        최종 한 문장으로 다듬기. Ollama 미가용 시 RAG 원문을 그대로 사용.
        """
        keyword = (rag_context or {}).get("keyword") or fast_prediction or ""
        warm = (rag_context or {}).get("warm_translation") or ""
        emotions = ", ".join((rag_context or {}).get("emotions") or [])

        # RAG 설명이 충분히 길면 그 자체가 이미 따뜻한 문장 → Ollama 건너뜀
        if warm and len(warm) >= 20:
            return warm

        prompt = (
            "당신은 청각장애인과 비장애인을 잇는 따뜻한 통역사입니다.\n"
            f"수어 단어: {keyword}\n"
            f"담긴 감정: {emotions}\n"
            f"기본 설명: {warm}\n"
            "위 내용을 바탕으로 친근하고 자연스러운 한 문장(최대 40자)으로 다듬어 주세요.\n"
            "문장:"
        )
        result = await self._call_ollama(prompt, timeout=self.timeout_rag)
        result = result.strip() if result else ""
        return result or warm or keyword or "대기 중"


slm_agent = SlmAgent()
