"""
batch_remove_bg.py — Supabase 영상 배경 제거 배치 처리

1. sign_source_video 테이블에서 영상 URL 목록 조회
2. 각 mp4 다운로드 → rembg 배경 제거 → transparent webm 생성
3. webm을 Supabase Storage(sign_videos)에 업로드
4. sign_source_video.video_url을 새 webm URL로 업데이트

사용법:
  python api/tools/batch_remove_bg.py              # 전체 처리
  python api/tools/batch_remove_bg.py --limit 5    # 테스트 (5개만)
  python api/tools/batch_remove_bg.py --resume     # 중단된 지점부터 재개
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
PROGRESS_FILE = os.path.join(TEMP_DIR, "progress.json")
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
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(prog, f, ensure_ascii=False, indent=2)


def download_video(url, out_path):
    """영상 다운로드 (외부 URL 또는 Supabase Storage URL)"""
    try:
        resp = requests.get(url, timeout=60, stream=True)
        resp.raise_for_status()
        with open(out_path, "wb") as f:
            for chunk in resp.iter_content(8192):
                f.write(chunk)
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

        pil_out = remove(pil_img, session=session, alpha_matting=True,
                         alpha_matting_foreground_threshold=240,
                         alpha_matting_background_threshold=20,
                         alpha_matting_erode_size=5)

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
        # 프레임 정리
        for f in os.listdir(frame_dir):
            os.remove(os.path.join(frame_dir, f))

    elapsed = time.time() - t0
    size_kb = os.path.getsize(output_webm) / 1024
    print(f"    {frame_count}frames {elapsed:.0f}s {size_kb:.0f}KB")
    return True


def upload_to_storage(sb, local_path, remote_name):
    """Supabase Storage에 업로드하고 public URL 반환"""
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

    public_url = sb.storage.from_(BUCKET).get_public_url(remote_name)
    return public_url


def update_video_url(sb, video_id, new_url):
    """sign_source_video 테이블의 video_url 업데이트"""
    sb.table("sign_source_video").update(
        {"video_url": new_url}
    ).eq("id", video_id).execute()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="처리할 최대 개수 (0=전체)")
    parser.add_argument("--resume", action="store_true", help="이전 진행상황에서 재개")
    args = parser.parse_args()

    os.makedirs(TEMP_DIR, exist_ok=True)

    sb = get_supabase()
    print("[1/4] Supabase Storage 버킷 영상 목록 조회 중...")

    # sign_videos 버킷에서 mp4 파일만 조회 (실제 업로드된 80개)
    bucket_files = sb.storage.from_(BUCKET).list("", {"limit": 1000})
    mp4_files = [f for f in bucket_files if f["name"].endswith(".mp4")]

    # sign_source_video 테이블에서 버킷 URL을 가진 레코드 매칭
    res = sb.table("sign_source_video").select("id, lemma_id, video_url, duration_s").execute()
    lemma_res = sb.table("sign_lemma").select("id, word").execute()
    lemma_map = {r["id"]: r["word"] for r in lemma_res.data}

    # 버킷 파일명 → DB 레코드 매칭
    videos = []
    for mp4 in mp4_files:
        fname = mp4["name"]
        # DB에서 이 파일을 참조하는 레코드 찾기
        matched = [r for r in res.data if fname in (r.get("video_url") or "")]
        if matched:
            v = matched[0]
            v["word"] = lemma_map.get(v["lemma_id"], f"id_{v['lemma_id']}")
            v["bucket_file"] = fname
            videos.append(v)
        else:
            # DB 매칭 없어도 버킷 파일 자체를 처리
            url = sb.storage.from_(BUCKET).get_public_url(fname)
            videos.append({
                "id": None, "word": fname.replace(".mp4", ""),
                "video_url": url, "duration_s": 4.0, "bucket_file": fname
            })

    print(f"  sign_videos 버킷 mp4: {len(mp4_files)}개")
    print(f"  처리 대상: {len(videos)}개")

    # 진행상황 로드 (bucket_file 이름 기준으로 추적)
    prog = load_progress() if args.resume else {"completed": [], "failed": []}
    completed_set = set(prog["completed"])
    remaining = [v for v in videos if v["bucket_file"] not in completed_set]

    if args.limit > 0:
        remaining = remaining[:args.limit]

    total_dur = sum(v.get("duration_s") or 4.0 for v in remaining)
    print(f"  처리 대상: {len(remaining)}개 (총 {total_dur:.0f}초)")
    print(f"  이미 완료: {len(completed_set)}개")
    print()

    # rembg 세션 초기화 (1회)
    print("[2/4] rembg U2-Net 모델 로딩...")
    session = new_session("u2net")
    print()

    # 처리 시작
    print(f"[3/4] 배경 제거 시작 ({len(remaining)}개)")
    print("=" * 60)

    t_start = time.time()
    for i, v in enumerate(remaining):
        vid_id = v.get("id")
        word = v["word"]
        url = v["video_url"]
        dur = v.get("duration_s") or 4.0
        bucket_file = v["bucket_file"]

        elapsed_total = time.time() - t_start
        if i > 0:
            avg_per = elapsed_total / i
            eta_min = avg_per * (len(remaining) - i) / 60
        else:
            eta_min = 0

        print(f"\n[{i+1}/{len(remaining)}] \"{word}\" ({dur:.1f}s) ETA {eta_min:.0f}min")

        safe_name = bucket_file.replace(".mp4", "")
        mp4_path = os.path.join(TEMP_DIR, f"{safe_name}.mp4")
        webm_path = os.path.join(TEMP_DIR, f"{safe_name}.webm")

        # 다운로드
        if not download_video(url, mp4_path):
            prog["failed"].append(bucket_file)
            save_progress(prog)
            continue

        # 배경 제거
        if not remove_bg_rembg(mp4_path, webm_path, session):
            print(f"  [실패] rembg 처리 실패")
            prog["failed"].append(bucket_file)
            save_progress(prog)
            if os.path.exists(mp4_path):
                os.remove(mp4_path)
            continue

        # 업로드: 원본 mp4 이름 기반으로 webm 저장
        try:
            remote_name = bucket_file.replace(".mp4", "_transparent.webm")
            public_url = upload_to_storage(sb, webm_path, remote_name)

            # DB 레코드가 있으면 video_url 업데이트
            if vid_id:
                update_video_url(sb, vid_id, public_url)
            print(f"  [완료] {remote_name}")
        except Exception as e:
            print(f"  [업로드 실패] {e}")
            prog["failed"].append(bucket_file)
            save_progress(prog)
            continue

        # 정리
        prog["completed"].append(bucket_file)
        save_progress(prog)
        for p in [mp4_path, webm_path]:
            if os.path.exists(p):
                os.remove(p)

    # 완료
    elapsed_min = (time.time() - t_start) / 60
    print()
    print("=" * 60)
    print(f"[4/4] 완료! {elapsed_min:.1f}분 소요")
    print(f"  성공: {len(prog['completed'])}개")
    print(f"  실패: {len(prog['failed'])}개")
    if prog["failed"]:
        print(f"  실패 파일: {prog['failed']}")


if __name__ == "__main__":
    main()
