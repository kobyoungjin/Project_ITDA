"""
video_proxy.py — 수어 영상 URL 제공 라우터

GET /api/video/url/{keyword}
  → Supabase에 있으면 즉시 URL 반환
  → 없으면 sldict 다운로드 후 Supabase 업로드 → URL 반환
  → 둘 다 실패하면 404
"""

from fastapi import APIRouter, HTTPException

from api.services.supabase_video import ensure_video

router = APIRouter()


@router.get("/url/{keyword}")
async def get_video_url(keyword: str):
    """
    keyword에 해당하는 수어 영상의 Supabase 공개 URL을 반환합니다.
    Supabase에 없으면 자동으로 다운로드 후 업로드합니다.
    """
    url = await ensure_video(keyword)
    if not url:
        raise HTTPException(
            status_code=404,
            detail=f"'{keyword}'에 해당하는 영상을 찾을 수 없습니다"
        )
    return {"keyword": keyword, "url": url}
