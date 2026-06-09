import unicodedata
from api.services.vector_db import vector_db

class RagEngine:
    def __init__(self):
        # 동의어 및 매핑 사전 (RAG 보완용)
        self.synonyms = {
            "감사": "고맙습니다",
            "인사": "안녕하세요",
            "안녕": "안녕하세요",
            "죄송": "미안합니다",
            "사과": "미안합니다",
            "도움": "도와주세요",
        }

    def _normalize(self, text: str) -> str:
        """한글 NFC 정규화 및 공백 제거"""
        if not text: return ""
        return unicodedata.normalize('NFC', text).strip()

    def retrieve_with_emotion(self, query: str, context: str = ""):
        """단순 검색이 아닌 감정 컨텍스트를 고려한 RAG 검색 로직"""
        
        query = self._normalize(query)
        # 검색어 확장 (사용자 쿼리 + 문맥)으로 더 정교하고 따뜻한 매칭
        enhanced_query = f"{query} {context}".strip()
        
        # 1-1. [우선순위] 완전 일치 검색 (Mock 데이터 및 고정 수어 단어 보장)
        exact_match = next((item for item in vector_db.metadata if self._normalize(item['keyword']) == query), None)
        
        if exact_match:
            print(f"[RagEngine] 완전 일치 데이터 발견: {query}")
            best_match = exact_match
        else:
            # 1-2. 동의어 기반 1차 확장 매칭
            synonym_target = self.synonyms.get(query)
            if synonym_target:
                exact_match = next((item for item in vector_db.metadata if self._normalize(item['keyword']) == synonym_target), None)
                if exact_match:
                    print(f"[RagEngine] 동의어 매칭 발견: {query} -> {synonym_target}")
                    best_match = exact_match
                    return self._build_response(best_match)

            # 1-3. [폴백] FAISS 벡터 DB에서 가장 유사한 수어 정보 검색 (top_k=1)
            search_results = vector_db.search(enhanced_query, top_k=1)
            
            if not search_results:
                return {
                    "keyword": query,
                    "warm_translation": "현재 해당 단어의 따뜻한 수어 표현을 지식베이스에서 찾고 있어요.",
                    "video_url": "",
                    "emotions": []
                }
            
            best_match = search_results[0]['data']
            score = search_results[0].get('score', 0)
            
            # [휴리스틱] 엉뚱한 단어 매칭 방지
            q_chars = set(query.replace(" ", ""))
            k_chars = set(best_match['keyword'].replace(" ", ""))
            
            # 의미 기반 검색(RAG)이더라도, 너무 동떨어진 쓰레기값이 매칭되는 것을 막기 위한 필터
            # 유사도가 일정 수준 이상(0.6 이상)이면 글자가 겹치지 않아도 허용
            if not q_chars.intersection(k_chars) and len(query) > 1 and score < 0.6:
                return {
                    "keyword": query,
                    "warm_translation": f"'{query}'에 해당하는 정확한 수어 동작을 아직 배우지 못했어요.",
                    "video_url": "",
                    "emotions": []
                }
        
        return self._build_response(best_match)

    def _build_response(self, best_match):
        return {
            "keyword": best_match['keyword'],
            "warm_translation": best_match['description'],
            "video_url": best_match['video_url'],
            "emotions": best_match['emotions']
        }

rag_engine = RagEngine()
