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

    async def predict_fast(self, raw_data: dict) -> dict:
        """Track 1: 센서 퓨전 기반 경고 레벨 판정 및 1차 예측"""
        meta = raw_data.get("meta_features", {})
        det = raw_data.get("detection_data", {"visual_confidence": 0.0, "audio_confidence": 0.0, "detected_area_m2": 0.0})
        
        # [Cyborg Alpha] 센서 퓨전 가중치 적용 (시각 65%, 음향 35%)
        vis_conf = det.get("visual_confidence", 0.0)
        aud_conf = det.get("audio_confidence", 0.0)
        area = det.get("detected_area_m2", 0.0)
        
        total_confidence = (vis_conf * 0.65) + (aud_conf * 0.35)
        
        # 경고 레벨 판정 (JSON 명세 기준)
        alert_level = "Low"
        if total_confidence > 0.95 and area > 1.0:
            alert_level = "High"
        elif total_confidence > 0.80 or area > 0:
            alert_level = "Medium"
        elif total_confidence > 0.60:
            alert_level = "Low"
            
        # NMS 매핑 (confidence 기준)
        nms_preset = {"eyebrows": "neutral", "mouth": "oo", "head": "tilt"}
        if total_confidence >= 0.90:
            nms_preset = {"eyebrows": "furrowed", "mouth": "cha", "head": "forward"}
        elif total_confidence >= 0.60:
            nms_preset = {"eyebrows": "raised", "mouth": "pa", "head": "neutral"}
            
        return {
            "alert_level": alert_level,
            "confidence_score": total_confidence,
            "nms_guide": nms_preset,
            "text": "위험 감지 분석 중..." 
        }

    async def predict_with_rag(self, fast_prediction: dict, rag_context: dict) -> str:
        """Track 2: 경고 상황에 맞춘 KSL 메시지 합성"""
        alert_level = fast_prediction.get("alert_level", "Low")
        
        # 경고 레벨별 기본 메시지 설정
        ksl_messages = {
            "Low": "주의 구역 내 수상한 움직임이 감지되었습니다.",
            "Medium": "경고: 낙서 행위가 감지되었습니다. 즉시 중단하십시오.",
            "High": "보호 구역 내 낙서 시도 감지. 즉시 중단하십시오. 보안팀이 출동합니다."
        }
        
        base_msg = ksl_messages.get(alert_level, "관찰 중")
        return base_msg

slm_agent = SlmAgent()
