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

import os
import aiohttp
from typing import Any, Dict
from dotenv import load_dotenv

# dotenv 내부 버그(find_dotenv) 우회를 위해 경로를 명확히 지정
load_dotenv(dotenv_path=".env")

# [NEW] Gemini API 연동 설정
try:
    import google.generativeai as genai
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    if GEMINI_API_KEY and GEMINI_API_KEY.strip() and GEMINI_API_KEY != "your_gemini_api_key_here":
        genai.configure(api_key=GEMINI_API_KEY)
        gemini_model = genai.GenerativeModel("gemini-flash-latest")
        print("[SlmAgent] Gemini Flash 최신 모델이 활성화되었습니다 (초고속 모드).")
    else:
        gemini_model = None
except ImportError:
    gemini_model = None


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
]


def _rule_based_predict(meta: Dict[str, Any]) -> str:
    shapes = tuple(meta.get("handshapes") or [])
    regions = meta.get("wrist_regions") or []
    right_region = regions[0] if regions else ""
    movement = (meta.get("movement") or "").lower()

    # 사용자 요청에 의해 RULE_HINTS를 통한 임의 예측을 비활성화합니다.
    # 이제 AI(Ollama) 분석 전까지는 무조건 미인식/대기 상태로 처리됩니다.
    
    # 손이 감지되지 않으면 기본 유휴 상태
    if not shapes:
        return "대기 중"
        
    # 손이 감지되었지만 아직 AI가 분석하기 전 (임시 상태)
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
    def __init__(self, model_name: str = "gemma3:4b"):
        self.model_name = model_name
        self.api_url = "http://localhost:11434/api/generate"
        self._circuit_breaker_until = 0

    async def _call_ai(self, prompt: str, timeout: int = 7) -> str:
        # 1. Gemini API 키가 있으면 무조건 우선 사용 (빠르고 똑똑함)
        if gemini_model:
            try:
                response = await gemini_model.generate_content_async(prompt)
                return response.text.strip()
            except Exception as e:
                print(f"[SlmAgent] Gemini 호출 실패 (Ollama로 우회 시도 안 함): {e}")
                return ""

        # 2. Gemini 키가 없으면 기존 Ollama(로컬) 사용
        import time
        if time.time() < self._circuit_breaker_until:
            return ""
            
        try:
            async with aiohttp.ClientSession() as session:
                payload = {"model": self.model_name, "prompt": prompt, "stream": False}
                async with session.post(self.api_url, json=payload, timeout=timeout) as resp:
                    if resp.status != 200:
                        self._circuit_breaker_until = time.time() + 30
                        return ""
                    data = await resp.json()
                    return (data.get("response") or "").strip()
        except Exception as e:
            print(f"[SlmAgent] Ollama 호출 실패(서킷 브레이커 작동, 30초 우회): {e}")
            self._circuit_breaker_until = time.time() + 30
            return ""

    async def predict_fast(self, raw_data: dict, skip_ollama: bool = False) -> str:
        """
        Track 1: 손 수형 + 상체 포즈 + 이동 요약으로 KSL 단어 1개 추측.
        항상 **문자열** 을 반환 (이전 dict 반환은 계약 오류였음).
        """
        meta = raw_data.get("meta_features") or {}

        if skip_ollama:
            return _rule_based_predict(meta)

        prompt = (
            "당신은 한국 수어(KSL) 통역사입니다. 아래 관찰 정보를 바탕으로, "
            "반드시 제시된 [단어 후보군] 안에서만 정답을 하나 골라 출력하세요. "
            "만약 후보군 중에 매칭되는 것이 전혀 없다면 '미인식'이라고 출력하세요. "
            "절대로 부연 설명을 덧붙이거나 후보군에 없는 단어를 창작하지 마세요.\n\n"
            f"- 손 모양: {meta.get('handshape_summary', '감지 안됨')}\n"
            f"- 손 위치(부위): {meta.get('wrist_regions', '알 수 없음')}\n"
            f"- 상체 포즈: {meta.get('pose_summary', '감지 안됨')}\n"
            f"- 손 움직임: {meta.get('movement', '정지')}\n\n"
            "[단어 후보군]\n"
            "안녕하세요, 사랑합니다, 고맙습니다, 나, 너, 행복해요, 만나다, 가다, 반가워요, 이름, "
            "미안합니다, 힘내세요, 어디에요, 괜찮아요, 도와주세요, 이름이 뭐예요\n\n"
            "정답:"
        )

        raw_text = await self._call_ai(prompt)
        word = _clean_single_word(raw_text)

        # SLM 응답이 비었거나 수상하면 규칙 기반 폴백
        if not word or len(word) < 2 or word.startswith("미인식"):
            word = _rule_based_predict(meta)

        return word

    async def predict_with_rag(self, fast_prediction: str, rag_context: dict) -> str:
        """
        사용자 요청에 의해 장황한 해설(warm_translation)을 제거하고
        핵심 단어(keyword)만 반환하도록 간소화합니다.
        """
        keyword = (rag_context or {}).get("keyword") or fast_prediction or ""
        return keyword or "대기 중"


slm_agent = SlmAgent()
