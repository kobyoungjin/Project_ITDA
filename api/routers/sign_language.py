from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from api.services.rag_engine import rag_engine
from api.services.data_pipeline import data_pipeline

router = APIRouter()

class SearchRequest(BaseModel):
    query: str
    context: Optional[str] = ""

class SearchResponseData(BaseModel):
    keyword: str
    warm_translation: str
    video_url: str
    emotions: List[str]

class SearchResponse(BaseModel):
    status: str
    data: SearchResponseData

@router.post("/search", response_model=SearchResponse)
async def search_sign_language(request: SearchRequest):
    """주어진 문장이나 쿼리로 '온기'가 담긴 수어 데이터를 검색합니다."""
    try:
        result = rag_engine.retrieve_with_emotion(request.query, request.context)
        return SearchResponse(
            status="success",
            data=SearchResponseData(**result)
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/refresh-pipeline")
async def refresh_pipeline():
    """데이터 파이프라인을 수동으로 재실행하여 FAISS 벡터 스토어를 갱신합니다."""
    try:
        count = data_pipeline.process_and_store()
        return {"status": "success", "message": f"{count}개의 수어-감정 데이터 처리 성공"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
