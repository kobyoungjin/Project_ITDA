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
# 모델은 환경변수 GEMINI_MODEL 로 오버라이드 가능 (기본: gemini-flash-latest)
GEMINI_MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-flash-latest")
gemini_model = None
gemini_init_error: str | None = None

try:
    import google.generativeai as genai
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    if GEMINI_API_KEY and GEMINI_API_KEY.strip() and GEMINI_API_KEY != "your_gemini_api_key_here":
        genai.configure(api_key=GEMINI_API_KEY)
        gemini_model = genai.GenerativeModel(GEMINI_MODEL_NAME)
        print(f"[SlmAgent] Gemini 모델 활성화: {GEMINI_MODEL_NAME}")
    else:
        gemini_init_error = "GEMINI_API_KEY 가 .env 에 설정되지 않았습니다."
        print(f"[SlmAgent] {gemini_init_error} → Ollama 폴백 사용 예정")
except ImportError as e:
    gemini_init_error = f"google-generativeai 패키지 미설치: {e}. 'pip install google-generativeai' 실행 필요."
    print(f"[SlmAgent] {gemini_init_error}")


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
        self._last_gemini_error: str | None = None

    def status(self) -> dict:
        """문장 구성기 상태 진단 — REST 엔드포인트에서 호출."""
        import time
        return {
            "gemini_available": gemini_model is not None,
            "gemini_model": GEMINI_MODEL_NAME if gemini_model else None,
            "gemini_init_error": gemini_init_error,
            "gemini_cooldown_remaining_s": max(0, int(self._gemini_breaker - time.time())),
            "last_gemini_error": self._last_gemini_error,
            "ollama_url": self.api_url,
            "ollama_cooldown_remaining_s": max(0, int(self._circuit_breaker_until - time.time())),
        }

    async def _call_ai(self, prompt: str, timeout: int = 7) -> str:
        import time
        # 1. Gemini API 키가 있으면 우선 사용 (서킷 브레이커 확인)
        if gemini_model and time.time() > self._gemini_breaker:
            try:
                response = await gemini_model.generate_content_async(prompt)
                return response.text.strip()
            except Exception as e:
                err_text = str(e)
                # ResourceExhausted(429)는 크레딧/쿼터 소진 → 길게 중단, 그 외는 짧게
                is_quota = ("ResourceExhausted" in type(e).__name__) or ("429" in err_text)
                cooldown = 600 if is_quota else 60
                print(f"[SlmAgent] Gemini 호출 실패 ({cooldown}s 중단 후 Ollama 전환): {err_text[:200]}")
                self._gemini_breaker = time.time() + cooldown
                self._last_gemini_error = err_text
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

        한국 수어(KSL)는 한국어와 어순이 다르고 조사가 생략되므로,
        단순 나열이 아닌 한국어로 자연스럽게 재구성된 한 문장을 반환합니다.
        단어가 1개뿐이면 그 단어 자체를 문장 형태로 다듬어 반환합니다.
        """
        if not words:
            return ""
        # 1개 단어는 그대로 반환 (모델 호출 절약)
        if len(words) == 1:
            return words[0]

        prompt = (
            "역할: 당신은 한국 수어(KSL) → 한국어 번역 전문가입니다.\n"
            "한국 수어는 한국어와 어순이 다르고 조사가 생략되므로, "
            "수어 단어 나열을 한국어 화자에게 자연스럽게 들리는 완성된 문장 하나로 재구성하세요.\n\n"
            f"수어 단어 순서: [{', '.join(words)}]\n\n"
            "출력 규칙:\n"
            "1. 완성된 한국어 문장 한 줄만 출력. 다른 말, 마크다운, 따옴표 금지.\n"
            "2. 의문/감탄/명령 등 문맥에 맞는 종결어미 자연스럽게 사용.\n"
            "3. 단어를 절대 변형해 의미를 바꾸지 말 것 (조사·어미만 보충).\n"
            "4. 너무 길어지지 않게 가능하면 30자 이내로.\n"
            "문장:"
        )
        raw_text = await self._call_ai(prompt)
        cleaned = _clean_sentence(raw_text)
        # LLM 양쪽 모두 실패한 경우(빈 문자열) → 단순 띄어쓰기 폴백
        if not cleaned:
            return " ".join(words)
        return cleaned


slm_agent = SlmAgent()
