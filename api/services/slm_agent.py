"""
slm_agent.py ─ KSL(한국 수어) 문장 구성 SLM 에이전트

KNN 으로 인식된 수어 단어들을 모아 자연스러운 한국어 문장 하나로 합성합니다.
LLM 호출 우선순위는 Gemini(있을 경우) → Ollama(로컬 폴백) 입니다.

  - build_sentence(words) : 인식된 단어 리스트 → 자연스러운 문장 1개
"""

from __future__ import annotations

import os
import aiohttp
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


def _clean_sentence(text: str) -> str:
    """SLM 출력에서 완성된 문장 추출. 특수기호만 제거."""
    if not text:
        return ""
    for ch in ('"', "'", "`", "*", "\n", "\r", "\t"):
        text = text.replace(ch, " ")
    return text.strip()


class SlmAgent:
    def __init__(self, model_name: str = "gemma3:4b"):
        self.model_name = model_name
        self.api_url = "http://localhost:11434/api/generate"
        self._circuit_breaker_until = 0
        self._gemini_breaker = 0  # Gemini 실패 시 일시 중단 시각

    async def _call_ai(self, prompt: str, timeout: int = 7) -> str:
        import time
        # 1. Gemini API 키가 있으면 우선 사용 (서킷 브레이커 확인)
        if gemini_model and time.time() > self._gemini_breaker:
            try:
                response = await gemini_model.generate_content_async(prompt)
                return response.text.strip()
            except Exception as e:
                print(f"[SlmAgent] Gemini 호출 실패 (10분간 중단 및 Ollama 전환): {e}")
                # 403/401 등 인증 오류 시 10분간 중단
                self._gemini_breaker = time.time() + 600
                # 여기서 return 하지 않고 아래 Ollama 로직으로 흘러가게 함

        # 2. Gemini 키가 없거나 실패 시 Ollama(로컬) 사용
        if time.time() < self._circuit_breaker_until:
            return ""

        try:
            async with aiohttp.ClientSession() as session:
                payload = {"model": self.model_name, "prompt": prompt, "stream": False}
                async with session.post(self.api_url, json=payload, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                    if resp.status != 200:
                        self._circuit_breaker_until = time.time() + 30
                        return ""
                    data = await resp.json()
                    return (data.get("response") or "").strip()
        except Exception:
            # Ollama 도 없으면 조용히 빈 값 반환 (호출 측에서 폴백 처리)
            self._circuit_breaker_until = time.time() + 30
            return ""

    async def build_sentence(self, words: list[str]) -> str:
        """
        Sentence Builder — 인식된 여러 단어를 조합해 자연스러운 한국어 문장 하나로 구성합니다.
        """
        if not words:
            return ""
        prompt = (
            "당신은 한국 수어(KSL) 번역가입니다. 사용자가 연속으로 표현한 다음 수어 단어들을 "
            "조합하여 가장 자연스러운 하나의 한국어 문장으로 만들어주세요.\n"
            f"입력 단어들: {', '.join(words)}\n\n"
            "출력 규칙:\n"
            "1. 부연 설명 없이 완성된 문장 하나만 출력하세요.\n"
            "2. 마크다운이나 특수기호를 사용하지 마세요.\n"
            "정답:"
        )
        raw_text = await self._call_ai(prompt)
        return _clean_sentence(raw_text)


slm_agent = SlmAgent()
