import requests
from typing import List, Dict
from api.services.vector_db import vector_db
from api.core.config import settings

class DataPipeline:
    def __init__(self):
        self.api_url = "http://api.kcisa.kr/openapi/service/rest/meta4/getKCPG0504" # 문화데이터광장 샘플
        self.api_key = settings.CULTURE_API_KEY

    def _parse_public_data(self, raw_items: List[Dict]) -> List[Dict]:
        """
        문화데이터광장의 정제되지 않은 원시 데이터를 프론트엔드 약속 규격에 맞게 파싱합니다.
        필수 필드가 없는 데이터는 누락(필터링) 처리하여 불량 데이터를 방지합니다.
        """
        parsed_data = []
        if isinstance(raw_items, dict):
            raw_items = [raw_items] # 단일 객체 응답 예외 처리
            
        for item in raw_items:
            try:
                # 공공데이터 API의 불규칙한 키값(XML->JSON 변환 시 발생) 대응 방어 로직
                keyword = item.get("title", item.get("keyword", ""))
                description = item.get("description", item.get("content", ""))
                video_url = item.get("videoUrl", item.get("url", ""))
                
                # 메타데이터 불량 스킵 로직 (필수 값이 없으면 벡터DB 파괴 방지)
                if not keyword or not description:
                    continue
                    
                # 감정 키워드가 없을 경우를 대비한 방어 로직
                emotions = item.get("emotions", ["일반", "설명"])
                
                parsed_data.append({
                    "keyword": keyword,
                    "description": description,
                    "emotions": emotions,
                    "video_url": video_url
                })
            except Exception as e:
                print(f"[DataPipeline] 파싱 에러 발생 (해당 row 스킵됨): {e}")
                continue
                
        return parsed_data

    def fetch_sign_language_data(self) -> List[Dict]:
        """문화데이터광장 API 데이터 수집 및 안전한 파싱 로직 적용"""
        raw_data = []
        is_mock_mode = True # 로컬 테스트 시에는 목업 데이터 파싱을 시뮬레이션
        
        try:
            # 실제 연동 시 주석 해제 (10초 타임아웃으로 백엔드 프리징 방지)
            # params = {"serviceKey": self.api_key, "numOfRows": 100, "pageNo": 1}
            # response = requests.get(self.api_url, params=params, timeout=10)
            # response.raise_for_status()
            # raw_data = response.json().get("response", {}).get("body", {}).get("items", {}).get("item", [])
            # is_mock_mode = False if raw_data else True
            pass
        except Exception as e:
            print(f"[DataPipeline] API 서버 통신 실패, 준비된 목업 데이터로 폴백(Fallback)합니다: {e}")
            is_mock_mode = True
            
        if is_mock_mode:
            # 외부 API에서 들어올 수 있는 여러 필드 네이밍을 시뮬레이션
            raw_data = [
                {
                    "title": "안녕하세요", 
                    "content": "오른손을 펴서 이마에서 가슴으로 내리며 상대방을 존중하는 마음을 담아 가볍게 미소짓습니다. 반가움과 친절함을 나누는 가장 기본적이고 따뜻한 인사입니다.", 
                    "emotions": ["반가움", "친절함", "따뜻함"], 
                    "videoUrl": "http://api.kcisa.kr/sample/hello.mp4"
                },
                {
                    "keyword": "고맙습니다", 
                    "description": "왼손등 위에 오른손날을 가볍게 두 번 치며, 진심 어린 감사의 마음을 표합니다. 눈을 맞추며 부드럽게 고개를 끄덕이면 온기가 더 잘 전달됩니다.", 
                    "emotions": ["감사", "진심", "따뜻함"], 
                    "url": "http://api.kcisa.kr/sample/thanks.mp4"
                },
                {
                    "title": "사랑합니다", 
                    "description": "오른손 주먹을 쥐고 머리 위에서부터 아래로 선을 그리며, 마음속 깊은 애정과 사랑을 부드럽게 상대에게 전달합니다.", 
                    "emotions": ["사랑", "애정", "온기"], 
                    "videoUrl": "http://api.kcisa.kr/sample/love.mp4"
                }
            ]
            
        # _parse_public_data 함수를 통해 프론트엔드가 요구하는 정제된 규격(JSON)으로 변환
        return self._parse_public_data(raw_data)

    def process_and_store(self, force_refresh=False):
        """데이터 수집 및 FAISS 저장을 수행하는 파이프라인"""
        # 강제 새로고침이 아니고, 이미 캐시에서 불러온 데이터가 있다면 스킵
        if not force_refresh and vector_db.index.ntotal > 0:
            print("[DataPipeline] 기존 오프라인 캐시가 존재합니다. 데이터 파이프라인 연산을 생략합니다.")
            return len(vector_db.metadata)

        data = self.fetch_sign_language_data()
        
        texts_to_embed = []
        metas = []
        
        for item in data:
            # 단순 단어가 아닌 의미와 감정을 합친 문맥 벡터화로 RAG 퍼포먼스 극대화
            context = f"키워드: {item['keyword']}, 의미: {item['description']}, 감정: {', '.join(item['emotions'])}"
            texts_to_embed.append(context)
            metas.append(item)
            
        vector_db.add_data(texts_to_embed, metas)
        return len(data)

data_pipeline = DataPipeline()
