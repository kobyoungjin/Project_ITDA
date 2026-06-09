"""
sldict_crawler.py — 국립국어원 한국수어사전(sldict.korean.go.kr)에서 영상 URL 크롤링

1. 단어 검색 → origin_no 추출
2. origin_no → controlVideoSpeed.do → mp4 URL 추출
3. sign_source_video에 등록

안정성: 3회 재시도, 진행 저장, --resume 지원

사용법:
  python api/tools/sldict_crawler.py                    # 영상 없는 전체 단어
  python api/tools/sldict_crawler.py --limit 32         # 32개만
  python api/tools/sldict_crawler.py --resume            # 중단 지점부터 재개
  python api/tools/sldict_crawler.py --words "학교,집,물" # 특정 단어만
"""

import argparse
import json
import os
import re
import sys
import time
import requests

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from api.core.config import settings
from supabase import create_client

PROGRESS_FILE = os.path.join(ROOT, "temp_bg_removal", "progress_sldict_crawl.json")
SLDICT_SEARCH = "https://sldict.korean.go.kr/front/sign/signList.do"
SLDICT_VIDEO = "https://sldict.korean.go.kr/front/sign/include/controlVideoSpeed.do"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
MAX_RETRIES = 3


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


def search_origin_no(word):
    """sldict 검색 → 첫 번째 origin_no 반환"""
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.post(SLDICT_SEARCH, data={
                "searchKeyword": word,
                "searchCondition": "all",
                "top_category": "CTE",
                "pageIndex": "1",
            }, timeout=15, headers=HEADERS)

            if resp.status_code != 200:
                time.sleep(1)
                continue

            # fnSearchContentsView(\'1352\', \'0\') 패턴
            matches = re.findall(r"fnSearchContentsView\(\s*\\?'(\d+)\\?'\s*,", resp.text)
            if matches:
                return matches[0]

            # 대체 패턴: origin_no=1352
            matches2 = re.findall(r"origin_no=(\d+)", resp.text)
            if matches2:
                return matches2[0]

            return None

        except Exception:
            if attempt < MAX_RETRIES - 1:
                time.sleep(1)
            continue
    return None


def get_video_url(origin_no):
    """origin_no → mp4 URL 추출 (700X466 우선)"""
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.post(SLDICT_VIDEO, data={
                "origin_no": origin_no,
                "speed": "1",
                "size": "700",
            }, timeout=15, headers=HEADERS)

            if resp.status_code != 200:
                time.sleep(1)
                continue

            urls = re.findall(r'https?://[^\"\s<>]+\.mp4[^\"\s<>]*', resp.text)
            # 700X466 우선
            for u in urls:
                if "700X466" in u:
                    return u
            # 320X240이라도 반환
            return urls[0] if urls else None

        except Exception:
            if attempt < MAX_RETRIES - 1:
                time.sleep(1)
            continue
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--words", type=str, default="", help="쉼표 구분 특정 단어")
    args = parser.parse_args()

    sb = get_supabase()

    # 특정 단어 모드
    if args.words:
        target_words = [w.strip() for w in args.words.split(",") if w.strip()]
        print(f"[특정 단어 모드] {len(target_words)}개: {target_words[:10]}...")
    else:
        # 영상 없는 lemma 목록 조회
        print("[1/3] 영상 없는 lemma 조회 중...")
        all_lemma = []
        offset = 0
        while True:
            res = sb.table("sign_lemma").select("id, word").range(offset, offset + 999).execute()
            rows = res.data or []
            all_lemma.extend(rows)
            if len(rows) < 1000:
                break
            offset += 1000

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
        target_words = [l["word"] for l in no_video]
        print(f"  전체 lemma: {len(all_lemma)}개, 영상 있음: {len(has_video)}개, 영상 없음: {len(no_video)}개")

    # 진행상황
    prog = load_progress() if args.resume else {"found": [], "not_found": [], "failed": []}
    done_words = set(prog["found"] + prog["not_found"] + prog["failed"])
    remaining = [w for w in target_words if w not in done_words]

    if args.limit > 0:
        remaining = remaining[:args.limit]

    print(f"  이미 처리: {len(done_words)}개, 처리 대상: {len(remaining)}개")
    print()

    if not remaining:
        print("처리할 단어가 없습니다!")
        return

    # lemma word→id 매핑
    lemma_map = {}
    offset = 0
    while True:
        res = sb.table("sign_lemma").select("id, word").range(offset, offset + 999).execute()
        rows = res.data or []
        for r in rows:
            lemma_map[r["word"]] = r["id"]
        if len(rows) < 1000:
            break
        offset += 1000

    # 크롤링 시작
    print(f"[2/3] sldict 크롤링 시작 ({len(remaining)}개)")
    print("=" * 60)

    t_start = time.time()
    found = 0
    not_found = 0
    fail = 0

    for i, word in enumerate(remaining):
        # 진행률 (50개마다)
        if i > 0 and i % 50 == 0:
            elapsed = time.time() - t_start
            eta = (elapsed / i) * (len(remaining) - i) / 60
            print(f"  --- [{i}/{len(remaining)}] 발견:{found} 없음:{not_found} "
                  f"실패:{fail} ETA:{eta:.1f}min ---")
            save_progress(prog)

        # 1) 검색 → origin_no
        origin_no = search_origin_no(word)
        if not origin_no:
            prog["not_found"].append(word)
            not_found += 1
            continue

        # 2) origin_no → video URL
        video_url = get_video_url(origin_no)
        if not video_url:
            prog["not_found"].append(word)
            not_found += 1
            continue

        # 3) DB 등록
        lid = lemma_map.get(word)
        if lid:
            try:
                sb.table("sign_source_video").insert({
                    "lemma_id": lid,
                    "source": "sldict",
                    "video_url": video_url,
                    "is_signer_pov": True,
                    "width": 700,
                    "height": 466,
                }).execute()
            except Exception as e:
                if "duplicate" not in str(e).lower():
                    prog["failed"].append(word)
                    fail += 1
                    continue

        prog["found"].append(word)
        found += 1

        # API 부하 방지
        time.sleep(0.5)

    save_progress(prog)

    # 결과
    elapsed_min = (time.time() - t_start) / 60
    print()
    print("=" * 60)
    print(f"[3/3] 완료! {elapsed_min:.1f}분 소요")
    print(f"  영상 발견: {found}개")
    print(f"  영상 없음: {not_found}개")
    print(f"  실패: {fail}개")
    print(f"  응답률: {found * 100 / max(1, found + not_found):.1f}%")
    print()
    print(f"  누적: 발견 {len(prog['found'])}개, 없음 {len(prog['not_found'])}개")
    print()
    print("다음 단계: 배경 제거")
    print("  python api/tools/batch_sldict_bg.py --resume")


if __name__ == "__main__":
    main()
