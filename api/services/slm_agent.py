import aiohttp
import json

class SlmAgent:
    def __init__(self, model_name="gemma3:4b"):
        self.model_name = model_name
        self.api_url = "http://localhost:11434/api/generate"

    async def _call_ollama(self, prompt: str) -> str:
        try:
            async with aiohttp.ClientSession() as session:
                payload = {
                    "model": self.model_name,
                    "prompt": prompt,
                    "stream": False
                }
                async with session.post(self.api_url, json=payload, timeout=7) as response:
                    if response.status != 200:
                        return ""
                    data = await response.json()
                    return data.get("response", "").strip()
        except Exception as e:
            # 로컬 컴퓨터에 Ollama가 아직 없거나 꺼져있을 때 프로그램이 죽지 않도록 방어(Fallback)
            print(f"[SLM Agent] Ollama 연결 불가 (Fallback 모드 가동): {e}")
            return ""

    async def predict_fast(self, raw_data: dict) -> str:
        """Track 1: 초고속 1차 예측 (빠른 텍스트 반환)"""
        # (원래는 raw_data의 손 좌표를 해석하여 구문 트리로 만듦)
        # 현재 데모를 위해 지정된 프롬프트 전달
        prompt = "손목이 이마에서 가슴으로 부드럽게 내려옵니다. 이 동작이 나타내는 수어의 의미를 1단어로 짧게 추측해줘."
        
        result = await self._call_ollama(prompt)
        if not result:
            return "안녕하세요" # Fallback
        return result

    async def predict_with_rag(self, fast_prediction: str, rag_context: dict) -> str:
        """Track 2: RAG 컨텐츠와 1차 예측을 결합하여 따뜻한 문장 완성"""
        emotions = ", ".join(rag_context.get('emotions', []))
        desc = rag_context.get('warm_translation', '')
        
        prompt = f"""
        당신은 따뜻하고 공감 능력이 뛰어난 수어 통역사입니다.
        현재 분석된 수어 동작의 1차 의미는 '{fast_prediction}'입니다.
        여기에 RAG(지식베이스) 검색 결과인 다음 감정과 상세 의미를 하나로 예쁘게 녹여서 문장을 완성해주세요:
        - 감정: {emotions}
        - 지식베이스 원문: {desc}
        결과만 따뜻한 한국어로 요약 출력하세요:
        """
        
        result = await self._call_ollama(prompt)
        if not result:
            return desc # Fallback
        return result

slm_agent = SlmAgent()
