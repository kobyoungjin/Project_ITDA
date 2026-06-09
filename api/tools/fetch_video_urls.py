"""
fetch_video_urls.py — sign_lemma에 등록된 단어 중 영상이 없는 것에 KCISA API로 영상 URL 등록

안정성:
  - 10개 단위 배치 처리 + 진행 저장
  - API 실패 시 3회 재시도
  - 중단 후 --resume으로 이어서 가능
  - 중복 등록 방지 (sign_source_video에 이미 있으면 스킵)

사용법:
  python api/tools/fetch_video_urls.py               # 전체 처리
  python api/tools/fetch_video_urls.py --limit 100   # 100개만
  python api/tools/fetch_video_urls.py --resume       # 중단 지점부터 재개
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

PROGRESS_FILE = os.path.join(ROOT, "temp_bg_removal", "progress_fetch_urls.json")
KCISA_API = "https://api.kcisa.kr/API_CNV_054/request"
MAX_RETRIES = 3
RETRY_DELAY = 2  # 초


def get_supabase():
    key = settings.SUPABASE_SERVICE_KEY or settings.SUPABASE_KEY
    return create_client(settings.SUPABASE_URL, key)


def load_progress():
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"found": [], "not_found": [], "failed": []}


def save_progress(prog):
    os.makedirs(os.path.dirname(PROGRESS_FILE), exist_ok=True)
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(prog, f, ensure_ascii=False, indent=2)


def fetch_video_url(word, api_key):
    """KCISA API로 수어 영상 URL 조회 (재시도 포함)"""
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get(KCISA_API, params={
                "serviceKey": api_key,
                "numOfRows": "1",
                "pageNo": "1",
                "title": word,
            }, timeout=15)

            if resp.status_code != 200:
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_DELAY)
                    continue
                return None

            root = ET.fromstring(resp.text)
            # sldict mp4 URL 추출
            for item in root.iter("item"):
                for field in item:
                    text = (field.text or "").strip()
                    if "sldict" in text and ".mp4" in text and text.startswith("http"):
                        return text
            return None

        except requests.exceptions.Timeout:
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY)
                continue
            return None
        except Exception:
            return None

    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="처리할 최대 개수 (0=전체)")
    parser.add_argument("--resume", action="store_true", help="이전 진행에서 재개")
    args = parser.parse_args()

    sb = get_supabase()
    api_key = getattr(settings, "CULTURE_API_KEY", "") or os.environ.get("CULTURE_API_KEY", "")
    if not api_key:
        print("[에러] CULTURE_API_KEY가 설정되지 않았습니다.")
        return

    # 1. 영상 없는 lemma 목록 조회
    print("[1/3] 영상 없는 lemma 조회 중...")

    # 모든 lemma
    all_lemma = []
    offset = 0
    while True:
        res = sb.table("sign_lemma").select("id, word").range(offset, offset + 999).execute()
        rows = res.data or []
        all_lemma.extend(rows)
        if len(rows) < 1000:
            break
        offset += 1000

    # 영상이 있는 lemma_id
    has_video = set()
    offset = 0
    while True:
        res = sb.table("sign_source_video").select("lemma_id").range(offset, offset + 999).execute()
        rows = res.data or []
        for r in rows:
            has_video.add(r["lemma_id"])
        if len(rows) < 1000:
            break
        offset += 1000

    no_video = [l for l in all_lemma if l["id"] not in has_video]
    print(f"  전체 lemma: {len(all_lemma)}개")
    print(f"  영상 있음: {len(has_video)}개")
    print(f"  영상 없음: {len(no_video)}개")

    # 진행상황
    prog = load_progress() if args.resume else {"found": [], "not_found": [], "failed": []}
    done_ids = set(prog["found"] + prog["not_found"] + prog["failed"])
    remaining = [l for l in no_video if str(l["id"]) not in done_ids]

    if args.limit > 0:
        remaining = remaining[:args.limit]

    print(f"  이미 처리: {len(done_ids)}개")
    print(f"  처리 대상: {len(remaining)}개")
    print()

    if not remaining:
        print("처리할 단어가 없습니다!")
        return

    # 2. KCISA API로 영상 URL 조회 + 등록
    print(f"[2/3] KCISA 영상 URL 조회 시작 ({len(remaining)}개)")
    print("=" * 60)

    t_start = time.time()
    found_count = 0
    not_found_count = 0
    fail_count = 0

    for i, lemma in enumerate(remaining):
        word = lemma["word"]
        lid = lemma["id"]

        # 진행률 표시 (50개마다)
        if i > 0 and i % 50 == 0:
            elapsed = time.time() - t_start
            eta = (elapsed / i) * (len(remaining) - i) / 60
            print(f"  --- [{i}/{len(remaining)}] 발견:{found_count} 없음:{not_found_count} "
                  f"실패:{fail_count} ETA:{eta:.1f}min ---")
            save_progress(prog)

        video_url = fetch_video_url(word, api_key)

        if video_url:
            try:
                sb.table("sign_source_video").insert({
                    "lemma_id": lid,
                    "source": "kcisa",
                    "video_url": video_url,
                    "is_signer_pov": True,
                }).execute()
                prog["found"].append(str(lid))
                found_count += 1
            except Exception as e:
                # 중복 등록 등 DB 에러
                if "duplicate" in str(e).lower() or "already" in str(e).lower():
                    prog["found"].append(str(lid))
                    found_count += 1
                else:
                    prog["failed"].append(str(lid))
                    fail_count += 1
        else:
            prog["not_found"].append(str(lid))
            not_found_count += 1

        # API 속도 제한 방지
        time.sleep(0.3)

    save_progress(prog)

    # 3. 결과
    elapsed_min = (time.time() - t_start) / 60
    print()
    print("=" * 60)
    print(f"[3/3] 완료! {elapsed_min:.1f}분 소요")
    print(f"  영상 발견: {found_count}개")
    print(f"  영상 없음: {not_found_count}개")
    print(f"  API 실패: {fail_count}개")
    print(f"  응답률: {found_count * 100 / max(1, found_count + not_found_count):.1f}%")
    print()
    print(f"  누적: 발견 {len(prog['found'])}개, 없음 {len(prog['not_found'])}개, 실패 {len(prog['failed'])}개")
    print()
    print("다음 단계: 영상 배경 제거")
    print("  python api/tools/batch_sldict_bg.py --resume")


if __name__ == "__main__":
    main()
