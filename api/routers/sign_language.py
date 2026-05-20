from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from pathlib import Path
from api.services.rag_engine import rag_engine
from api.services.data_pipeline import data_pipeline
from api.services.motion_extractor import motion_extractor

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
async def refresh_pipeline(force: bool = True):
    """
    데이터 파이프라인을 수동 재실행하여 FAISS 벡터 스토어를 갱신.

    [⑤ FAISS 캐시 무효화]
    force=True (기본) → 기존 캐시를 버리고 AI Hub dedup·감정 추론을 새로 반영
    force=False       → 이미 캐시가 있으면 건너뜀 (빠른 기동용)
    """
    try:
        count = data_pipeline.process_and_store(force_refresh=force)
        mode = "강제 재빌드" if force else "증분 로드"
        return {
            "status": "success",
            "mode": mode,
            "count": count,
            "message": f"{count}개 수어-감정 데이터 처리 성공 ({mode})"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/resolve-motion")
async def resolve_motion(request: dict):
    """
    단어에 해당하는 관절 데이터가 로컬에 있는지 확인하고, 
    없으면 국립국어원 영상을 통해 생성합니다.
    """
    word = request.get("word")
    if not word:
        raise HTTPException(status_code=400, detail="Word is required")
        
    # 1. 이미 존재하는지 확인 (안전한 파일명으로 변환)
    safe_word = word.replace("/", "_").replace(",", "_")
    target_path = Path("frontend/data/ksl_motions") / f"{safe_word}.json"
    if target_path.exists():
        return {"status": "exists", "word": word, "safe_word": safe_word, "message": "Motion already exists"}
        
    # 2. 실시간 추출 시도
    success = motion_extractor.extract_and_save(word)
    if success:
        return {"status": "created", "word": word, "message": "Motion extracted successfully"}
    else:
        # 3. 폴백 (Fuzzy Match 시도 - 이미 추출된 파일 중 이름에 포함된 게 있는지)
        # (이 부분은 추후 고도화 가능)
        raise HTTPException(status_code=404, detail=f"Motion for '{word}' could not be resolved")
@router.get("/list-motions")
async def list_motions():
    """학습 데이터셋(CSV)에서 실제 학습된 단어 목록을 추출하여 반환합니다."""
    from api.services.knn_classifier import get_model_type
    m_type = get_model_type()
    csv_file = "ksl_dataset.csv" if m_type == "main" else "ksl_dataset_dialogue.csv"
    csv_path = Path("api/data/ksl_training") / csv_file
    
    if not csv_path.exists():
        return {"count": 0, "words": []}
    
    try:
        import pandas as pd
        df = pd.read_csv(csv_path, encoding='utf-8')
        if 'label' not in df.columns:
            return {"count": 0, "words": []}
        
        # 중복 제거 및 정렬
        words = sorted(df['label'].unique().tolist())
        return {"count": len(words), "words": words}
    except Exception as e:
        print(f"[API] Error reading dataset: {e}")
        return {"count": 0, "words": []}
