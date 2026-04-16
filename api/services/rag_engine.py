from api.services.vector_db import vector_db

class RagEngine:
    def __init__(self):
        pass

    def retrieve_with_emotion(self, query: str, context: str = ""):
        """단순 검색이 아닌 감정 컨텍스트를 고려한 RAG 검색 로직"""
        
        # 검색어 확장 (사용자 쿼리 + 문맥)으로 더 정교하고 따뜻한 매칭
        enhanced_query = f"{query} {context}".strip()
        
        # FAISS 벡터 DB에서 가장 유사한 수어 정보 검색 (top_k=1)
        search_results = vector_db.search(enhanced_query, top_k=1)
        
        if not search_results:
            return {
                "keyword": query,
                "warm_translation": "현재 해당 단어의 따뜻한 수어 표현을 지식베이스에서 찾고 있어요. 더 많은 언어를 배우도록 하겠습니다.",
                "video_url": "",
                "emotions": []
            }
            
        best_match = search_results[0]['data']
        
        # 3단계(SLM) 연동 전, 백엔드 자체 RAG 전처리 결과 반환
        return {
            "keyword": best_match['keyword'],
            "warm_translation": best_match['description'],
            "video_url": best_match['video_url'],
            "emotions": best_match['emotions']
        }

rag_engine = RagEngine()
