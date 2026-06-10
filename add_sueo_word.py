"""
일회성 학습 스크립트: '수어' 단어를 KSL KNN 모델에 추가.

흐름:
  1) 대화(dialogue) 모델 활성화
  2) sldict 의 수어 영상 다운로드
  3) MediaPipe 로 랜드마크 추출 + CSV 누적
  4) KNN 재학습 + .pkl 갱신

사용: python add_sueo_word.py
"""
import sys
from pathlib import Path

# 백엔드 코드를 import 가능하게 프로젝트 루트를 PYTHONPATH 에 추가
sys.path.insert(0, str(Path(__file__).resolve().parent))

import httpx
from api.routers.collect import _process_video_file, train_knn_model
from api.services.knn_classifier import set_model_type

# ── 설정 ────────────────────────────────────────────────
LABEL = "수어"  # 학습할 라벨 (단순화). 사전 컨벤션이라면 "수어,수화,수화 언어"
VIDEO_URL = "https://sldict.korean.go.kr/multimedia/multimedia_files/convert/20221014/1040162/MOV000360639_700X466.mp4"

DATA_DIR = Path("api/data/ksl_training")
TEMP_PATH = DATA_DIR / "temp_sueo_download.mp4"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}


def main():
    print("=" * 60)
    print(f" '{LABEL}' 단어 KNN 학습 추가")
    print("=" * 60)

    # ── 1) 대화 모델 활성화 ───────────────────────────────
    print("\n[1/4] 대화(dialogue) 모델 활성화...")
    set_model_type("dialogue")
    print("  -> OK")

    # ── 2) 영상 다운로드 ──────────────────────────────────
    print(f"\n[2/4] 영상 다운로드 중...")
    print(f"  URL: {VIDEO_URL}")
    try:
        with httpx.Client(timeout=60.0, headers=HEADERS, follow_redirects=True) as client:
            resp = client.get(VIDEO_URL)
            if resp.status_code != 200:
                print(f"  ERROR: HTTP {resp.status_code}")
                return 1
            if len(resp.content) < 1000:
                print(f"  ERROR: file too small ({len(resp.content)} bytes)")
                return 1
            with open(TEMP_PATH, "wb") as f:
                f.write(resp.content)
            print(f"  -> {len(resp.content):,} bytes 저장: {TEMP_PATH}")
    except Exception as e:
        print(f"  ERROR: {e}")
        return 1

    # ── 3) 랜드마크 추출 + CSV 누적 ───────────────────────
    print(f"\n[3/4] MediaPipe 랜드마크 추출 중...")
    source = f"url:{VIDEO_URL}"
    try:
        saved = _process_video_file(TEMP_PATH, LABEL, source)
        print(f"  -> {saved}개 샘플 CSV에 저장됨")
        if saved == 0:
            print("  WARNING: 추출된 샘플이 없음. 영상에서 손이 안 잡혔을 수 있음.")
    except Exception as e:
        print(f"  ERROR: {e}")
        return 1
    finally:
        if TEMP_PATH.exists():
            TEMP_PATH.unlink()
            print(f"  -> 임시 파일 정리됨")

    if saved == 0:
        return 1

    # ── 4) KNN 재학습 ─────────────────────────────────────
    print(f"\n[4/4] KNN 모델 재학습 중...")
    try:
        result = train_knn_model(n_neighbors=5)
        if not result.get("ok"):
            print(f"  ERROR: {result.get('message')}")
            return 1
        print(f"  -> 정확도: {result.get('accuracy')}")
        print(f"  -> 전체 라벨 수: {result.get('label_count')}")
        print(f"  -> 학습 샘플 수: {result.get('samples')}")
        labels = result.get('labels', [])
        if LABEL in labels:
            print(f"  -> '{LABEL}' 라벨이 모델에 포함됨 ✓")
        else:
            print(f"  -> WARNING: '{LABEL}' 라벨이 학습 결과에 없음")
    except Exception as e:
        print(f"  ERROR: {e}")
        return 1

    print("\n" + "=" * 60)
    print(" 완료! 다음 단계: git commit + push hf-deploy")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
