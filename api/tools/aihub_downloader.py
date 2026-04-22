"""
aihub_downloader.py

AI Hub(aihub.or.kr) 한국수어 데이터셋(103) 다운로드 클라이언트

■ API 구조 (aihubshell v0.6 분석 결과)
  파일 목록: GET https://api.aihub.or.kr/info/103.do
  다운로드:  GET https://api.aihub.or.kr/down/0.6/103.do?fileSn={fileSn}
             Header: apikey: {API_KEY}
  응답 형식: .tar 파일 (내부에 .zip 들이 있음)

■ 데이터셋 103 파일 구성
  [morpheme]  수어 단어/형태소 라벨 (수 MB ~ 100MB) ← 우선 다운로드
  [keypoint]  뼈대 좌표 데이터 (9~14GB)
  [video]     원천 영상 (20~118GB)

■ fileSn 목록 (info/103.do에서 확인)
  morpheme (Training):
    39581 - 01_crowd_morpheme.zip        (8 MB)
    39584 - 01_real_sen_morpheme.zip     (81 MB)
    39601 - 01_real_word_morpheme.zip    (110 MB)
  morpheme (Validation):
    39475 - 01_crowd_morpheme.zip        (930 KB)
    39478 - 01_real_word_morpheme.zip    (14 MB)
    494853 - 01_real_sen_morpheme.zip    (10 MB)
  keypoint (Synthetic, 가장 작음):
    39617 - 01_syn_sen_keypoint.zip      (828 MB)
    39618 - 01_syn_word_keypoint.zip     (1023 MB)
"""

import sys
import json
import tarfile
import zipfile
import requests
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from api.core.config import settings

# ── 상수 ──────────────────────────────────────────────────────
AIHUB_BASE    = "https://api.aihub.or.kr"
DATASET_KEY   = "103"
API_VERSION   = "0.6"
DOWNLOAD_DIR  = ROOT / "api" / "data" / "aihub_raw"

# 다운로드 우선순위: morpheme(라벨) 먼저, 작은 것부터
PRIORITY_FILES = [
    # Validation morpheme (가장 작음 → 구조 확인용)
    {"fileSn": "39475",  "name": "val_crowd_morpheme",    "size": "930KB",  "type": "morpheme"},
    {"fileSn": "494853", "name": "val_sen_morpheme",      "size": "10MB",   "type": "morpheme"},
    {"fileSn": "39478",  "name": "val_word_morpheme",     "size": "14MB",   "type": "morpheme"},
    # Training morpheme
    {"fileSn": "39581",  "name": "train_crowd_morpheme",  "size": "8MB",    "type": "morpheme"},
    {"fileSn": "39584",  "name": "train_sen_morpheme",    "size": "81MB",   "type": "morpheme"},
    {"fileSn": "39601",  "name": "train_word_morpheme",   "size": "110MB",  "type": "morpheme"},
    # Synthetic keypoint (최소 크기)
    {"fileSn": "39617",  "name": "syn_sen_keypoint",      "size": "828MB",  "type": "keypoint"},
    {"fileSn": "39618",  "name": "syn_word_keypoint",     "size": "1023MB", "type": "keypoint"},
]


class AIHubDownloader:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or settings.AIHUB_API_KEY
        if not self.api_key:
            raise ValueError(
                "[AIHub] API Key 없음.\n"
                ".env 파일에 AIHUB_API_KEY=발급받은키 형식으로 입력하세요."
            )
        self.session = requests.Session()
        self.session.headers.update({"apikey": self.api_key})

    # ── 파일 목록 조회 ─────────────────────────────────────────
    def list_files(self) -> list[dict]:
        url = f"{AIHUB_BASE}/info/{DATASET_KEY}.do"
        try:
            resp = requests.get(url, timeout=15)
            content = resp.content.decode("utf-8", errors="replace")
            # .zip 라인에서 fileSn 파싱
            files = []
            for line in content.splitlines():
                if ".zip" in line and "|" in line:
                    parts = [p.strip() for p in line.split("|")]
                    if len(parts) >= 3:
                        name = parts[0].split("/")[-1].replace(".zip", "").strip("├─└─ ")
                        size = parts[1].strip()
                        file_sn = parts[2].strip()
                        files.append({"fileSn": file_sn, "name": name, "size": size})
            print(f"[AIHub] 파일 목록: {len(files)}개")
            return files
        except Exception as e:
            print(f"[AIHub] 목록 조회 실패: {e}")
            return PRIORITY_FILES

    # ── 단일 파일 다운로드 ─────────────────────────────────────
    def download_file(self, file_sn: str, file_name: str) -> Optional[Path]:
        DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
        dest = DOWNLOAD_DIR / f"{file_name}.tar"

        if dest.exists():
            print(f"[AIHub] 캐시 사용: {dest.name}")
            return dest

        url = f"{AIHUB_BASE}/down/{API_VERSION}/{DATASET_KEY}.do"
        params = {"fileSn": file_sn}
        print(f"[AIHub] 다운로드: {file_name} (fileSn={file_sn})")

        try:
            with self.session.get(url, params=params, stream=True, timeout=600) as resp:
                # 응답이 에러 텍스트인지 확인
                ct = resp.headers.get("Content-Type", "")
                if "text" in ct:
                    msg = resp.content.decode("utf-8", errors="replace")[:300]
                    if "401" in msg or "403" in msg or "apikey" in msg.lower():
                        print(f"[AIHub] 인증 실패: {msg}")
                        return None
                    print(f"[AIHub] 서버 응답: {msg}")

                total = int(resp.headers.get("content-length", 0))
                downloaded = 0
                with open(dest, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=1024 * 512):
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total:
                            pct = downloaded / total * 100
                            mb = downloaded / 1_000_000
                            print(f"\r  {pct:5.1f}%  {mb:.1f} MB", end="", flush=True)

            print(f"\n[AIHub] 완료: {dest} ({dest.stat().st_size / 1_000_000:.1f} MB)")
            return dest

        except Exception as e:
            print(f"\n[AIHub] 다운로드 실패: {e}")
            if dest.exists():
                dest.unlink()
            return None

    # ── tar 압축 해제 ─────────────────────────────────────────
    def extract_tar(self, tar_path: Path) -> Path:
        extract_dir = DOWNLOAD_DIR / tar_path.stem
        extract_dir.mkdir(parents=True, exist_ok=True)

        if list(extract_dir.iterdir()):
            print(f"[AIHub] 이미 해제됨: {extract_dir.name}")
            return extract_dir

        print(f"[AIHub] tar 해제: {tar_path.name}")
        try:
            with tarfile.open(tar_path, "r:*") as t:
                t.extractall(extract_dir)
        except tarfile.TarError:
            # tar가 아닌 경우 zip으로 시도
            print("[AIHub] tar 실패 -> zip 시도")
            with zipfile.ZipFile(tar_path, "r") as z:
                z.extractall(extract_dir)

        # 내부 zip 파일 해제
        for zp in extract_dir.rglob("*.zip"):
            subdir = zp.parent / zp.stem
            if not subdir.exists():
                print(f"  zip 해제: {zp.name}")
                with zipfile.ZipFile(zp, "r") as z:
                    z.extractall(subdir)

        return extract_dir

    # ── morpheme JSON 파싱 ────────────────────────────────────
    def parse_morpheme_json(self, extract_dir: Path) -> list[dict]:
        """
        AI Hub 수어(103) morpheme JSON 파싱.
        morpheme 파일은 수어 단어 레이블(형태소)과 타이밍을 담고 있음.

        예시 스키마:
        {
          "id": "NIA_SL_SEN0001",
          "data": [
            { "start": 0, "end": 45, "gloss": "안녕하세요" },
            { "start": 46, "end": 90, "gloss": "감사합니다" }
          ]
        }
        """
        records = []
        json_files = sorted(extract_dir.rglob("*.json"))
        print(f"[AIHub] morpheme JSON {len(json_files)}개 파싱...")

        sample_shown = False
        for jf in json_files:
            try:
                with open(jf, encoding="utf-8") as f:
                    raw = json.load(f)

                if not sample_shown:
                    print(f"[샘플 스키마] {jf.name}:")
                    print(json.dumps(raw, ensure_ascii=False, indent=2)[:800])
                    sample_shown = True

                # 스키마 유연 파싱 (AI Hub는 버전마다 키 이름이 다를 수 있음)
                file_id = raw.get("id") or raw.get("fileId") or jf.stem
                data = raw.get("data") or raw.get("annotations") or []

                for seg in data:
                    gloss = (
                        seg.get("gloss") or seg.get("label") or
                        seg.get("word") or seg.get("text") or ""
                    ).strip()
                    if not gloss:
                        continue

                    records.append({
                        "action":    gloss,
                        "file_id":   file_id,
                        "start":     seg.get("start", 0),
                        "end":       seg.get("end", 0),
                        "duration":  (seg.get("end", 0) - seg.get("start", 0)) / 30,
                        "fps":       30,
                        "frames":    [],  # keypoint 데이터는 별도 파일에 있음
                        "source":    str(jf),
                    })

            except Exception as e:
                print(f"  경고 {jf.name}: {e}")

        print(f"[AIHub] 파싱 완료: {len(records)}개 수어 세그먼트")
        # 고유 수어 단어 수
        unique = len(set(r["action"] for r in records))
        print(f"[AIHub] 고유 수어 단어: {unique}개")
        return records

    # ── morpheme 전용 실행 (빠른 라벨 확보) ─────────────────
    def run_morpheme_only(self) -> list[dict]:
        """morpheme(라벨) 파일만 다운로드하고 고유 수어 단어 목록을 반환합니다."""
        print("=" * 60)
        print("[AIHub] 수어 morpheme(라벨) 다운로드 시작")
        print("=" * 60)

        morpheme_files = [f for f in PRIORITY_FILES if f["type"] == "morpheme"]
        all_records = []

        for fi in morpheme_files:
            print(f"\n[{fi['name']}] ({fi['size']})")
            tar_path = self.download_file(fi["fileSn"], fi["name"])
            if tar_path is None:
                continue
            extract_dir = self.extract_tar(tar_path)
            records = self.parse_morpheme_json(extract_dir)
            all_records.extend(records)

        print(f"\n[AIHub] 총 {len(all_records)}개 수어 레코드")
        return all_records

    # ── keypoint 다운로드 (morpheme 이후) ──────────────────
    def run_with_keypoints(self) -> list[dict]:
        """synthetic keypoint 파일(가장 작음)을 함께 다운로드합니다."""
        all_records = self.run_morpheme_only()
        kp_files = [f for f in PRIORITY_FILES if f["type"] == "keypoint"]
        for fi in kp_files:
            print(f"\n[keypoint] {fi['name']} ({fi['size']})")
            tar_path = self.download_file(fi["fileSn"], fi["name"])
            if tar_path:
                self.extract_tar(tar_path)
        return all_records


# ── 단독 실행 ─────────────────────────────────────────────────
if __name__ == "__main__":
    dl = AIHubDownloader()
    dl.run_morpheme_only()
