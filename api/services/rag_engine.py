from api.services.vector_db import vector_db

class RagEngine:
    def __init__(self):
        pass

    def retrieve_with_emotion(self, query: str, context: str = ""):
        """단순 검색이 아닌 감정 컨텍스트를 고려한 RAG 검색 로직"""
        
        # 검색어 확장 (사용자 쿼리 + 문맥)으로 더 정교하고 따뜻한 매칭
        enhanced_query = f"{query} {context}".strip()
        
        # 1-1. [우선순위] 완전 일치 검색 (Mock 데이터 및 고정 수어 단어 보장)
        exact_match = next((item for item in vector_db.metadata if item['keyword'] == query), None)
        
        if exact_match:
             print(f"[RagEngine] 완전 일치 데이터 발견: {query}")
             best_match = exact_match
        else:
            # 1-2. [폴백] FAISS 벡터 DB에서 가장 유사한 수어 정보 검색 (top_k=1)
            search_results = vector_db.search(enhanced_query, top_k=1)
            
            if not search_results:
                return {
                    "keyword": query,
                    "warm_translation": "현재 해당 단어의 따뜻한 수어 표현을 지식베이스에서 찾고 있어요.",
                    "video_url": "",
                    "emotions": []
                }
            best_match = search_results[0]['data']
            
            # [휴리스틱] 엉뚱한 단어 매칭 방지 (자/모음이 아닌 완성형 글자 기준)
            # 사용자의 입력 쿼리와 RAG가 찾은 키워드 간에 단 한 글자라도 겹치는지 확인
            q_chars = set(query.replace(" ", ""))
            k_chars = set(best_match['keyword'].replace(" ", ""))
            
            # 의미 기반 검색(RAG)이더라도, 너무 동떨어진 쓰레기값이 매칭되는 것을 막기 위한 최소한의 필터
            if not q_chars.intersection(k_chars) and len(query) > 1:
                # 겹치는 글자가 아예 없다면, '대기 중'일 때는 조용히 무시, 그 외에는 안내
                if query == "대기 중":
                    return None
                return {
                    "keyword": query,
                    "warm_translation": f"'{query}' 동작을 분석 중이에요.",
                    "video_url": "",
                    "emotions": []
                }
        
        # 3단계(SLM) 연동 전, 백엔드 자체 RAG 전처리 결과 반환
        return {
            "keyword": best_match['keyword'],
            "warm_translation": best_match['description'],
            "video_url": best_match['video_url'],
            "emotions": best_match['emotions']
        }

rag_engine = RagEngine()
