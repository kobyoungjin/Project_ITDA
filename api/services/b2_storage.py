"""
b2_storage.py — Backblaze B2 스토리지 서비스

Private 버킷 + Auth Token 방식으로 영상을 저장/제공합니다.
Supabase Storage 용량 한계(1GB)를 우회하기 위한 외부 스토리지.

사용:
  from api.services.b2_storage import b2_storage

  # 업로드
  public_url = b2_storage.upload_file("local.webm", "감사.webm")

  # 인증 URL 생성 (프론트엔드 재생용)
  url = b2_storage.get_signed_url("감사.webm")
"""

import os
import time
from b2sdk.v2 import InMemoryAccountInfo, B2Api

_KEY_ID = os.getenv("B2_KEY_ID", "")
_APP_KEY = os.getenv("B2_APP_KEY", "")
_BUCKET_NAME = os.getenv("B2_BUCKET_NAME", "")

# Auth token 캐시 (24시간 유효, 재발급 최소화)
_TOKEN_CACHE = {"token": None, "expires": 0}
_TOKEN_TTL = 86400  # 24시간


class B2Storage:
    def __init__(self):
        self._api = None
        self._bucket = None
        self._base_url = None

    def _ensure_connected(self):
        if self._api is not None:
            return
        if not _KEY_ID or not _APP_KEY:
            raise RuntimeError("B2_KEY_ID / B2_APP_KEY 환경변수가 설정되지 않았습니다")
        info = InMemoryAccountInfo()
        self._api = B2Api(info)
        self._api.authorize_account("production", _KEY_ID, _APP_KEY)
        self._bucket = self._api.get_bucket_by_name(_BUCKET_NAME)
        self._base_url = info.get_download_url()
        print(f"[B2] 연결 완료: {_BUCKET_NAME}")

    def upload_file(self, local_path: str, remote_name: str) -> str:
        """로컬 파일을 B2에 업로드하고 signed URL을 반환합니다."""
        self._ensure_connected()
        content_type = "video/webm" if remote_name.endswith(".webm") else "video/mp4"
        self._bucket.upload_local_file(
            local_file=local_path,
            file_name=remote_name,
            content_type=content_type,
        )
        return self.get_signed_url(remote_name)

    def upload_bytes(self, data: bytes, remote_name: str, content_type: str = "video/webm") -> str:
        """바이트 데이터를 B2에 업로드합니다."""
        self._ensure_connected()
        self._bucket.upload_bytes(data, remote_name, content_type=content_type)
        return self.get_signed_url(remote_name)

    def get_signed_url(self, remote_name: str, duration: int = _TOKEN_TTL) -> str:
        """Private 버킷의 파일에 대한 인증 URL을 생성합니다."""
        self._ensure_connected()
        token = self._get_cached_token(duration)
        return f"{self._base_url}/file/{_BUCKET_NAME}/{remote_name}?Authorization={token}"

    def get_base_info(self) -> dict:
        """프론트엔드에 전달할 B2 기본 정보 (base_url + token)."""
        self._ensure_connected()
        token = self._get_cached_token(_TOKEN_TTL)
        return {
            "base_url": f"{self._base_url}/file/{_BUCKET_NAME}",
            "token": token,
            "expires_in": _TOKEN_TTL,
        }

    def _get_cached_token(self, duration: int) -> str:
        now = time.time()
        if _TOKEN_CACHE["token"] and _TOKEN_CACHE["expires"] > now + 300:
            return _TOKEN_CACHE["token"]
        self._ensure_connected()
        token = self._bucket.get_download_authorization("", duration)
        _TOKEN_CACHE["token"] = token
        _TOKEN_CACHE["expires"] = now + duration
        return token

    def list_files(self, prefix: str = "") -> list:
        """버킷 내 파일 목록을 반환합니다."""
        self._ensure_connected()
        files = []
        for fv in self._bucket.list_file_versions(prefix):
            files.append({
                "name": fv.file_name,
                "size": fv.size,
                "upload_time": fv.upload_timestamp,
            })
        return files


b2_storage = B2Storage()
