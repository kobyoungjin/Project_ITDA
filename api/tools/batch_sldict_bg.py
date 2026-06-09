"""
batch_sldict_bg.py — sldict URL 영상 배경 제거 배치 처리

sign_source_video 테이블에서 sldict.korean.go.kr URL을 가진 영상을:
  1. sldict에서 mp4 다운로드
  2. rembg 배경 제거 → transparent webm 생성
  3. Supabase Storage(sign_videos)에 업로드
  4. sign_source_video.video_url을 새 webm URL로 업데이트

사용법:
  python api/tools/batch_sldict_bg.py              # 전체 처리
  python api/tools/batch_sldict_bg.py --limit 3    # 테스트 (3개만)
  python api/tools/batch_sldict_bg.py --resume     # 중단 지점부터 재개
"""

import argparse
import cv2
import json
import numpy as np
import os
import sys
import time
import subprocess
import requests
import imageio_ffmpeg
from rembg import new_session, remove
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from api.core.config import settings
from supabase import create_client

# ── 설정 ────────────────────────────────────────────────────────
TEMP_DIR = os.path.join(ROOT, "temp_bg_removal")
PROGRESS_FILE = os.path.join(TEMP_DIR, "progress_sldict.json")
BUCKET = "sign_videos"


def get_supabase():
    key = settings.SUPABASE_SERVICE_KEY or settings.SUPABASE_KEY
    return create_client(settings.SUPABASE_URL, key)


def load_progress():
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"completed": [], "failed": []}


def save_progress(prog):
    os.makedirs(TEMP_DIR, exist_ok=True)
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(prog, f, ensure_ascii=False, indent=2)


def download_video(url, out_path):
    """sldict URL에서 mp4 다운로드"""
    try:
        resp = requests.get(url, timeout=60, stream=True, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        resp.raise_for_status()
        with open(out_path, "wb") as f:
            for chunk in resp.iter_content(8192):
                f.write(chunk)
        size_kb = os.path.getsize(out_path) / 1024
        if size_kb < 10:
            print(f"  [경고] 파일 크기 너무 작음: {size_kb:.0f}KB")
            return False
        return True
    except Exception as e:
        print(f"  [다운로드 실패] {e}")
        return False


def remove_bg_rembg(input_mp4, output_webm, session):
    """rembg로 배경 제거하여 transparent webm 생성"""
    cap = cv2.VideoCapture(input_mp4)
    if not cap.isOpened():
        return False

    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps == 0 or fps != fps:
        fps = 30.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    frame_dir = os.path.join(TEMP_DIR, "frames")
    os.makedirs(frame_dir, exist_ok=True)

    frame_count = 0
    t0 = time.time()

    while cap.isOpened():
        ok, image = cap.read()
        if not ok:
            break

        image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        pil_img = Image.fromarray(image_rgb)

        try:
            pil_out = remove(pil_img, session=session, alpha_matting=True,
                             alpha_matting_foreground_threshold=240,
                             alpha_matting_background_threshold=20,
                             alpha_matting_erode_size=5)
        except (MemoryError, np.core._exceptions._ArrayMemoryError):
            # 고해상도 프레임에서 alpha_matting 메모리 초과 시 폴백
            pil_out = remove(pil_img, session=session, alpha_matting=False)

        rgba = np.array(pil_out)
        bgra = cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGRA)

        cv2.imwrite(os.path.join(frame_dir, f"frame_{frame_count:05d}.png"), bgra)
        frame_count += 1

        if frame_count % 30 == 0:
            elapsed = time.time() - t0
            spd = frame_count / elapsed if elapsed > 0 else 0
            eta = (total - frame_count) / spd if spd > 0 else 0
            print(f"    [{frame_count}/{total}] {spd:.1f}fps ETA {eta:.0f}s", end="\r")

    cap.release()

    if frame_count == 0:
        return False

    # FFmpeg로 webm 생성
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [
        ffmpeg_exe, "-y",
        "-framerate", str(fps),
        "-i", os.path.join(frame_dir, "frame_%05d.png"),
        "-c:v", "libvpx-vp9",
        "-pix_fmt", "yuva420p",
        "-auto-alt-ref", "0",
        "-b:v", "1M",
        output_webm,
    ]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        return False
    finally:
        for f in os.listdir(frame_dir):
            os.remove(os.path.join(frame_dir, f))

    elapsed = time.time() - t0
    size_kb = os.path.getsize(output_webm) / 1024
    print(f"    {frame_count}frames {elapsed:.0f}s {size_kb:.0f}KB")
    return True


# Supabase Storage 사용량 추적 (1GB 한도)
_supabase_usage_mb = None
SUPABASE_LIMIT_MB = 960  # 안전 마진 40MB

def _get_supabase_usage(sb):
    """현재 Supabase Storage 사용량(MB)을 계산합니다."""
    global _supabase_usage_mb
    if _supabase_usage_mb is not None:
        return _supabase_usage_mb
    total = 0
    offset = 0
    while True:
        files = sb.storage.from_(BUCKET).list("", {"limit": 1000, "offset": offset})
        if not files:
            break
        for f in files:
            meta = f.get("metadata") if isinstance(f, dict) else None
            if meta:
                total += meta.get("size", 0)
        if len(files) < 1000:
            break
        offset += 1000
    _supabase_usage_mb = total / (1024 * 1024)
    return _supabase_usage_mb


def upload_to_storage(sb, local_path, remote_name):
    """Supabase Storage 우선, 용량 초과 시 B2 자동 전환.
    Supabase(410ms) → 빠름, B2(도메인 연결 후 200ms) → 확장용."""
    global _supabase_usage_mb
    file_size_mb = os.path.getsize(local_path) / (1024 * 1024)

    # Supabase에 여유 있으면 Supabase 우선
    usage = _get_supabase_usage(sb)
    if usage + file_size_mb < SUPABASE_LIMIT_MB:
        with open(local_path, "rb") as f:
            data = f.read()
        try:
            sb.storage.from_(BUCKET).upload(
                remote_name, data,
                file_options={"content-type": "video/webm", "upsert": "true"}
            )
        except Exception as e:
            if "Duplicate" in str(e) or "already exists" in str(e):
                sb.storage.from_(BUCKET).update(
                    remote_name, data,
                    file_options={"content-type": "video/webm"}
                )
            else:
                raise
        _supabase_usage_mb = usage + file_size_mb
        url = sb.storage.from_(BUCKET).get_public_url(remote_name)
        print(f"    [Supabase] {usage + file_size_mb:.0f}/{SUPABASE_LIMIT_MB}MB")
        return url

    # Supabase 용량 부족 → B2로 전환
    if os.environ.get("B2_KEY_ID"):
        from api.services.b2_storage import b2_storage
        url = b2_storage.upload_file(local_path, remote_name)
        print(f"    [B2] Supabase 용량 초과 → B2 저장")
        return url

    raise RuntimeError("Supabase 용량 초과 + B2 미설정")


def make_safe_filename(word, video_id):
    """ID 기반 안전한 파일명 생성 (Supabase Storage는 한글 키 거부)"""
    return f"sign_{video_id}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="처리할 최대 개수 (0=전체)")
    parser.add_argument("--resume", action="store_true", help="이전 진행상황에서 재개")
    args = parser.parse_args()

    os.makedirs(TEMP_DIR, exist_ok=True)
    sb = get_supabase()

    # ── 1. sldict URL을 가진 미처리 영상 조회 ──
    print("[1/4] sldict 미처리 영상 조회 중...")

    # 전체 sign_source_video 조회 (sldict URL만)
    all_rows = []
    offset = 0
    page_size = 500
    while True:
        res = sb.table("sign_source_video").select(
            "id, lemma_id, video_url, duration_s"
        ).like(
            "video_url", "%sldict.korean.go.kr%"
        ).range(offset, offset + page_size - 1).execute()
        rows = res.data or []
        all_rows.extend(rows)
        if len(rows) < page_size:
            break
        offset += page_size

    # lemma 이름 매핑
    lemma_res = sb.table("sign_lemma").select("id, word").execute()
    lemma_map = {r["id"]: r["word"] for r in (lemma_res.data or [])}

    for r in all_rows:
        r["word"] = lemma_map.get(r["lemma_id"], f"unknown_{r['lemma_id']}")

    print(f"  sldict URL 영상: {len(all_rows)}개")

    # 진행상황 로드
    prog = load_progress() if args.resume else {"completed": [], "failed": []}
    completed_ids = set(str(x) for x in prog["completed"])
    remaining = [r for r in all_rows if str(r["id"]) not in completed_ids]

    if args.limit > 0:
        remaining = remaining[:args.limit]

    print(f"  이미 완료: {len(completed_ids)}개")
    print(f"  처리 대상: {len(remaining)}개")
    print()

    if not remaining:
        print("처리할 영상이 없습니다!")
        return

    # ── 2. rembg 모델 로딩 ──
    print("[2/4] rembg U2-Net 모델 로딩...")
    session = new_session("u2net")
    print()

    # ── 3. 배치 처리 ──
    print(f"[3/4] 배경 제거 시작 ({len(remaining)}개)")
    print("=" * 60)

    t_start = time.time()
    success_count = 0
    fail_count = 0

    for i, v in enumerate(remaining):
        vid_id = v["id"]
        word = v["word"]
        url = v["video_url"]
        dur = v.get("duration_s") or 4.0

        elapsed_total = time.time() - t_start
        if i > 0:
            avg_per = elapsed_total / i
            eta_min = avg_per * (len(remaining) - i) / 60
        else:
            eta_min = 0

        print(f"\n[{i+1}/{len(remaining)}] \"{word}\" ({dur:.1f}s) ETA {eta_min:.0f}min")

        safe_name = make_safe_filename(word, vid_id)
        mp4_path = os.path.join(TEMP_DIR, f"{safe_name}.mp4")
        webm_path = os.path.join(TEMP_DIR, f"{safe_name}.webm")

        # 다운로드
        if not download_video(url, mp4_path):
            prog["failed"].append(str(vid_id))
            save_progress(prog)
            fail_count += 1
            continue

        # 배경 제거
        if not remove_bg_rembg(mp4_path, webm_path, session):
            print(f"  [실패] rembg 처리 실패")
            prog["failed"].append(str(vid_id))
            save_progress(prog)
            fail_count += 1
            if os.path.exists(mp4_path):
                os.remove(mp4_path)
            continue

        # 업로드
        try:
            remote_name = f"{safe_name}_transparent.webm"
            public_url = upload_to_storage(sb, webm_path, remote_name)
            update_video_url(sb, vid_id, public_url)
            print(f"  [완료] {word} → {remote_name}")
            success_count += 1
        except Exception as e:
            print(f"  [업로드 실패] {e}")
            prog["failed"].append(str(vid_id))
            save_progress(prog)
            fail_count += 1
            continue

        # 정리
        prog["completed"].append(str(vid_id))
        save_progress(prog)
        for p in [mp4_path, webm_path]:
            if os.path.exists(p):
                os.remove(p)

    # ── 4. 완료 ──
    elapsed_min = (time.time() - t_start) / 60
    print()
    print("=" * 60)
    print(f"[4/4] 완료! {elapsed_min:.1f}분 소요")
    print(f"  성공: {success_count}개")
    print(f"  실패: {fail_count}개")
    print(f"  누적 완료: {len(prog['completed'])}개")
    if prog["failed"]:
        print(f"  실패 ID: {prog['failed'][:20]}{'...' if len(prog['failed']) > 20 else ''}")


def update_video_url(sb, video_id, new_url):
    sb.table("sign_source_video").update(
        {"video_url": new_url}
    ).eq("id", video_id).execute()


if __name__ == "__main__":
    main()
