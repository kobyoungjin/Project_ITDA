"""
supabase_video.py — Supabase Storage 수어 영상 관리 (직접 REST API 방식)

supabase Python 패키지 없이 aiohttp로 Storage REST API를 직접 호출합니다.

흐름:
  1. Supabase Storage에서 파일 존재 여부 확인
  2. 없으면 sldict.korean.go.kr에서 다운로드 후 Supabase에 업로드
  3. 공개 URL 반환 → 프론트엔드가 직접 재생 (저장 없음)
"""

import json
import logging
from functools import lru_cache
from pathlib import Path

import aiohttp

from api.core.config import settings

logger = logging.getLogger(__name__)

BUCKET = "sign_videos"

SLDICT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "http://sldict.korean.go.kr/",
}


def _storage_base() -> str:
    return f"{settings.SUPABASE_URL}/storage/v1"


def _auth_header() -> dict:
    return {"Authorization": f"Bearer {settings.SUPABASE_SERVICE_KEY}"}


def _storage_path(keyword: str) -> str:
    safe = keyword.replace("/", "_").replace(" ", "_")
    return f"{safe}.mp4"


def public_url(keyword: str) -> str:
    """Supabase Storage 공개 URL 생성 (존재 여부와 무관)"""
    path = _storage_path(keyword)
    return f"{_storage_base()}/object/public/{BUCKET}/{path}"


@lru_cache(maxsize=1)
def _load_video_index() -> dict:
    path = Path("api/data/sign_video_urls.json")
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _find_source_url(keyword: str) -> str | None:
    """sign_video_urls.json에서 sldict 원본 URL 반환"""
    index = _load_video_index()

    entry = index.get(keyword)
    if entry and entry.get("video_url"):
        return entry["video_url"]

    for k, v in index.items():
        if keyword in k or k in keyword:
            url = v.get("video_url")
            if url:
                return url

    return None


async def _exists_in_storage(path: str) -> bool:
    """Supabase Storage에 파일이 존재하는지 HEAD 요청으로 확인"""
    url = f"{_storage_base()}/object/{BUCKET}/{path}"
    timeout = aiohttp.ClientTimeout(total=5)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.head(url, headers=_auth_header(), timeout=timeout) as resp:
                return resp.status == 200
    except Exception:
        return False


async def _download_from_sldict(source_url: str) -> bytes | None:
    """sldict에서 영상 바이트 다운로드"""
    timeout = aiohttp.ClientTimeout(connect=8, total=30)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(source_url, headers=SLDICT_HEADERS, timeout=timeout) as resp:
                if resp.status != 200:
                    logger.warning("[SupabaseVideo] 다운로드 실패 HTTP %s", resp.status)
                    return None
                return await resp.read()
    except Exception as e:
        logger.warning("[SupabaseVideo] 다운로드 오류: %s", e)
        return None


async def _upload_to_storage(path: str, data: bytes) -> bool:
    """Supabase Storage에 MP4 업로드"""
    url = f"{_storage_base()}/object/{BUCKET}/{path}"
    headers = {
        **_auth_header(),
        "Content-Type": "video/mp4",
        "x-upsert": "true",
    }
    timeout = aiohttp.ClientTimeout(total=60)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, data=data, timeout=timeout) as resp:
                if resp.status in (200, 201):
                    return True
                body = await resp.text()
                logger.error("[SupabaseVideo] 업로드 실패 %s: %s", resp.status, body[:200])
                return False
    except Exception as e:
        logger.error("[SupabaseVideo] 업로드 오류: %s", e)
        return False


async def ensure_video(keyword: str) -> str | None:
    """
    keyword 영상을 Supabase에서 확인하고,
    없으면 sldict에서 다운받아 업로드한 뒤 공개 URL 반환.
    설정 누락 시 None 반환.
    """
    if not settings.SUPABASE_URL or not settings.SUPABASE_SERVICE_KEY:
        logger.error("[SupabaseVideo] SUPABASE_URL / SUPABASE_SERVICE_KEY 미설정")
        return None

    path = _storage_path(keyword)

    # 1. 이미 Supabase에 있으면 바로 URL 반환
    if await _exists_in_storage(path):
        logger.info("[SupabaseVideo] 캐시 히트: %s", keyword)
        return public_url(keyword)

    # 2. 원본 URL 찾기
    source_url = _find_source_url(keyword)
    if not source_url:
        logger.info("[SupabaseVideo] '%s' 원본 영상 없음", keyword)
        return None

    # 3. 다운로드
    logger.info("[SupabaseVideo] '%s' 다운로드 중...", keyword)
    video_bytes = await _download_from_sldict(source_url)
    if not video_bytes:
        return None

    # 4. Supabase에 업로드
    logger.info("[SupabaseVideo] Supabase에 업로드 중 (%d bytes)...", len(video_bytes))
    if await _upload_to_storage(path, video_bytes):
        url = public_url(keyword)
        logger.info("[SupabaseVideo] 완료: %s", url)
        return url

    return None
