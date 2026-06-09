"""
sync_local_to_supabase.py — 로컬 인덱스 단어를 Supabase sign_lemma에 일괄 등록

로컬 index.json의 5,987개 단어 중 sign_lemma에 없는 단어를 등록하고,
KCISA API를 통해 영상 URL을 조회하여 sign_source_video에도 등록합니다.

사용법:
  python api/tools/sync_local_to_supabase.py              # 전체 동기화
  python api/tools/sync_local_to_supabase.py --limit 50   # 50개만 테스트
  python api/tools/sync_local_to_supabase.py --lemma-only  # lemma만 등록 (영상 조회 안 함)
  python api/tools/sync_local_to_supabase.py --resume      # 중단 지점부터 재개
"""

import argparse
import json
import os
import sys
import time
import requests
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from api.core.config import settings
from supabase import create_client

LOCAL_INDEX = os.path.join(ROOT, "frontend", "data", "ksl_motions", "index.json")
PROGRESS_FILE = os.path.join(ROOT, "temp_bg_removal", "progress_sync.json")
KCISA_API = "https://api.kcisa.kr/API_CNV_054/request"


def get_supabase():
    key = settings.SUPABASE_SERVICE_KEY or settings.SUPABASE_KEY
    return create_client(settings.SUPABASE_URL, key)


def load_progress():
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"synced": [], "failed": []}


def save_progress(prog):
    os.makedirs(os.path.dirname(PROGRESS_FILE), exist_ok=True)
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(prog, f, ensure_ascii=False, indent=2)


def fetch_kcisa_video_url(word, api_key):
    """KCISA API로 수어 영상 URL 조회"""
    if not api_key:
        return None
    try:
        resp = requests.get(KCISA_API, params={
            "serviceKey": api_key,
            "numOfRows": "1",
            "pageNo": "1",
            "title": word,
        }, timeout=10)
        if resp.status_code != 200:
            return None

        # XML 파싱
        root = ET.fromstring(resp.text)
        # URL 추출 시도
        for item in root.iter("item"):
            url_el = item.find("url") or item.find("referenceIdentifier")
            if url_el is not None and url_el.text:
                url = url_el.text.strip()
                if url.endswith(".mp4") or "sldict" in url:
                    return url
        # alternativeTitle이나 description에서 URL 추출 시도
        for item in root.iter("item"):
            for field in item:
                if field.text and ("sldict" in field.text or ".mp4" in field.text):
                    text = field.text.strip()
                    if text.startswith("http"):
                        return text
    except Exception as e:
        pass
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--lemma-only", action="store_true", help="lemma만 등록, 영상 조회 안 함")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()

    sb = get_supabase()
    api_key = getattr(settings, 'CULTURE_API_KEY', '') or os.environ.get('CULTURE_API_KEY', '')

    # 1. 로컬 인덱스 로드
    print("[1/4] 로컬 인덱스 로드 중...")
    with open(LOCAL_INDEX, "r", encoding="utf-8") as f:
        idx = json.load(f)
    local_words = idx.get("actions", [])
    # 한글 포함 단어만 (WORD0001 등 코드 제외)
    local_words = [w for w in local_words if any('가' <= ch <= '힣' for ch in w)]
    print(f"  로컬 한글 단어: {len(local_words)}개")

    # 2. 기존 sign_lemma 단어 조회
    print("[2/4] 기존 sign_lemma 조회 중...")
    existing = set()
    offset = 0
    while True:
        res = sb.table("sign_lemma").select("word").range(offset, offset + 999).execute()
        rows = res.data or []
        for r in rows:
            existing.add(r["word"])
        if len(rows) < 1000:
            break
        offset += 1000
    print(f"  기존 lemma: {len(existing)}개")

    # 3. 미등록 단어 필터링
    missing = [w for w in local_words if w not in existing]
    print(f"  미등록 단어: {len(missing)}개")

    # 진행상황
    prog = load_progress() if args.resume else {"synced": [], "failed": []}
    synced_set = set(prog["synced"])
    remaining = [w for w in missing if w not in synced_set]

    if args.limit > 0:
        remaining = remaining[:args.limit]

    print(f"  이미 동기화: {len(synced_set)}개")
    print(f"  처리 대상: {len(remaining)}개")
    print()

    if not remaining:
        print("동기화할 단어가 없습니다!")
        return

    # 4. 배치 등록
    print(f"[3/4] sign_lemma 등록 시작 ({len(remaining)}개)")
    print("=" * 60)

    t_start = time.time()
    batch_size = 50  # Supabase upsert 배치 크기
    success = 0
    fail = 0

    for batch_start in range(0, len(remaining), batch_size):
        batch = remaining[batch_start:batch_start + batch_size]
        batch_data = [{"word": w} for w in batch]

        try:
            sb.table("sign_lemma").upsert(
                batch_data, on_conflict="word"
            ).execute()

            for w in batch:
                prog["synced"].append(w)
            success += len(batch)

            elapsed = time.time() - t_start
            done = batch_start + len(batch)
            total = len(remaining)
            eta = (elapsed / done) * (total - done) / 60 if done > 0 else 0
            print(f"  [{done}/{total}] +{len(batch)}개 등록 (ETA {eta:.1f}min)")

        except Exception as e:
            print(f"  [배치 실패] {batch_start}~{batch_start+len(batch)}: {e}")
            for w in batch:
                prog["failed"].append(w)
            fail += len(batch)

        save_progress(prog)

    print()
    print(f"  lemma 등록 완료: 성공 {success}개, 실패 {fail}개")

    # 5. 영상 URL 조회 (옵션)
    if not args.lemma_only and api_key:
        print()
        print(f"[4/4] KCISA 영상 URL 조회 ({len(remaining)}개)")
        print("=" * 60)

        # 새로 등록된 lemma의 ID 조회
        video_count = 0
        for i, w in enumerate(remaining):
            if i % 100 == 0 and i > 0:
                print(f"  [{i}/{len(remaining)}] 영상 {video_count}개 발견")

            # lemma_id 조회
            lr = sb.table("sign_lemma").select("id").eq("word", w).execute()
            if not lr.data:
                continue
            lemma_id = lr.data[0]["id"]

            # 이미 sign_source_video에 있으면 스킵
            existing_vid = sb.table("sign_source_video").select("id").eq("lemma_id", lemma_id).execute()
            if existing_vid.data:
                continue

            # KCISA API로 영상 URL 조회
            video_url = fetch_kcisa_video_url(w, api_key)
            if video_url:
                try:
                    sb.table("sign_source_video").insert({
                        "lemma_id": lemma_id,
                        "source": "kcisa",
                        "video_url": video_url,
                        "is_signer_pov": True,
                    }).execute()
                    video_count += 1
                except Exception as e:
                    pass

            # API 속도 제한 방지
            time.sleep(0.3)

        print(f"  영상 URL 등록: {video_count}개")
    else:
        if args.lemma_only:
            print("[4/4] --lemma-only 옵션: 영상 조회 생략")
        elif not api_key:
            print("[4/4] CULTURE_API_KEY 없음: 영상 조회 생략")

    elapsed_min = (time.time() - t_start) / 60
    print()
    print("=" * 60)
    print(f"완료! {elapsed_min:.1f}분 소요")
    print(f"  lemma 등록: {success}개")
    print(f"  총 lemma: {len(existing) + success}개")


if __name__ == "__main__":
    main()
