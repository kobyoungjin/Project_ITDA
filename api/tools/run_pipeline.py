"""
run_pipeline.py

AI Hub 한국수어 데이터 → 아바타 키프레임 JSON 전체 파이프라인 실행기

■ 실행 방법
  # 1단계: API 키 유효성 확인만 (다운로드 없음)
  python api/tools/run_pipeline.py --check

  # 2단계: 라벨 데이터만 다운로드 + 변환 (빠름, 권장)
  python api/tools/run_pipeline.py --labels-only

  # 3단계: 라벨 + 원천영상 모두 다운로드 + MediaPipe 추출 (느림)
  python api/tools/run_pipeline.py --full

  # 개수 제한 테스트 (처음 50개만)
  python api/tools/run_pipeline.py --labels-only --limit 50

■ 출력 결과
  api/data/ksl_motions/
    안녕하세요.json     ← 키프레임 모션 데이터
    고맙습니다.json
    ...
    index.json          ← 전체 수어 목록 인덱스
"""

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from api.tools.aihub_downloader import AIHubDownloader
from api.tools.keyframe_converter import convert_and_save, build_index, MAX_ACTIONS


def check_api_key():
    """API 키 유효성만 확인합니다 (다운로드 없음)."""
    print("=" * 60)
    print("[ITDA] AI Hub API Key 유효성 확인")
    print("=" * 60)
    try:
        downloader = AIHubDownloader()
        files = downloader.list_files()
        if files:
            print("\n✅ API Key 정상 - 데이터셋 파일 목록 조회 성공")
            print(f"   다운로드 가능한 파일: {len(files)}개")
        else:
            print("\n⚠️  파일 목록이 비어 있습니다.")
            print("   → 데이터셋 활용 신청이 아직 미승인 상태일 수 있습니다.")
            print("   → aihub.or.kr > 데이터셋 109(수어 영상) > 활용신청 확인")
    except ValueError as e:
        print(f"\n❌ {e}")
    except Exception as e:
        print(f"\n❌ 오류: {e}")


def run_labels_only(limit: int | None = None):
    """
    라벨(JSON) 데이터만 다운로드 후 키프레임으로 변환합니다.
    원천영상(MP4)은 받지 않으므로 빠르게 처리됩니다.
    """
    print("=" * 60)
    print("[ITDA] 파이프라인 시작 - 라벨 전용 모드")
    print("=" * 60)
    t0 = time.perf_counter()

    # 1. 다운로드 + 파싱
    downloader = AIHubDownloader()
    records = downloader.run(labels_only=True)

    if not records:
        print("\n❌ 다운로드된 레코드 없음. API Key 또는 데이터셋 승인 상태를 확인하세요.")
        return

    # 2. 개수 제한 적용
    if limit:
        records = records[:limit]
        print(f"\n[파이프라인] 제한 적용: {limit}개만 변환")

    # 3. 키프레임 변환 + 저장
    saved = convert_and_save(records)

    # 4. 인덱스 생성
    build_index(saved)

    elapsed = time.perf_counter() - t0
    print(f"\n{'=' * 60}")
    print(f"[ITDA] 완료! 총 {len(saved)}개 수어 모션 생성 ({elapsed:.1f}초)")
    print(f"  저장 위치: api/data/ksl_motions/")
    print(f"  다음 단계: run_pipeline.py --update-db 로 RAG DB 업데이트")
    print("=" * 60)


def run_full(limit: int | None = None):
    """
    원천영상까지 다운로드 후 MediaPipe 로 골격을 추출합니다.
    AI Hub 라벨에 keypoints 가 없는 경우 사용합니다.
    """
    print("=" * 60)
    print("[ITDA] 파이프라인 시작 - 영상 + MediaPipe 추출 모드")
    print("⚠️  원천영상 다운로드는 수십 GB 일 수 있습니다.")
    print("=" * 60)

    confirm = input("계속 진행하시겠습니까? (y/N): ").strip().lower()
    if confirm != "y":
        print("취소됨.")
        return

    downloader = AIHubDownloader()
    records = downloader.run(labels_only=False)

    # 원천영상 기반 레코드는 frames 가 없으므로 영상 경로로 추출
    # (향후 구현: skeleton_extractor.extract_from_video 호출)
    print("\n[알림] 원천영상 기반 MediaPipe 추출은 향후 업데이트 예정입니다.")
    print("       현재는 라벨 JSON 의 keypoints 만 사용합니다.")
    run_labels_only(limit)


def update_rag_db():
    """
    변환된 키프레임 JSON 을 기존 RAG 벡터 DB 에 추가합니다.
    (aihub 수어는 기존 mock 데이터와 함께 검색됩니다)
    """
    import json as _json
    from pathlib import Path as _Path

    ksl_dir = ROOT / "api" / "data" / "ksl_motions"
    index_path = ksl_dir / "index.json"

    if not index_path.exists():
        print("❌ index.json 없음. 먼저 --labels-only 를 실행하세요.")
        return

    with open(index_path, encoding="utf-8") as f:
        index = _json.load(f)

    actions = index.get("actions", [])
    print(f"[RAG] {len(actions)}개 수어를 벡터 DB 에 추가합니다...")

    sys.path.insert(0, str(ROOT))
    from api.services.vector_db import vector_db

    texts, metas = [], []
    for action in actions:
        motion_path = ksl_dir / f"{action}.json"
        if not motion_path.exists():
            continue
        with open(motion_path, encoding="utf-8") as f:
            motion = _json.load(f)

        context = f"키워드: {action}, 수어 모션 데이터, 키프레임: {len(motion['keyframes'])}개"
        texts.append(context)
        metas.append({
            "keyword":     action,
            "description": f"{action} 수화 동작 ({len(motion['keyframes'])}개 키프레임)",
            "emotions":    [],
            "video_url":   "",
            "motion_file": str(motion_path),   # 키프레임 파일 경로 추가
        })

    vector_db.add_data(texts, metas)
    print(f"[RAG] ✅ {len(texts)}개 추가 완료. 현재 DB 총 항목: {vector_db.index.ntotal}")


# ── CLI 진입점 ─────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ITDA KSL 데이터 파이프라인")
    parser.add_argument("--check",       action="store_true", help="API Key 유효성 확인만")
    parser.add_argument("--labels-only", action="store_true", help="라벨 JSON만 다운로드 (권장)")
    parser.add_argument("--full",        action="store_true", help="원천영상 + MediaPipe 추출")
    parser.add_argument("--update-db",   action="store_true", help="변환된 모션을 RAG DB에 추가")
    parser.add_argument("--limit",       type=int, default=None, help="변환할 수어 개수 제한 (테스트용)")
    args = parser.parse_args()

    if args.check:
        check_api_key()
    elif args.labels_only:
        run_labels_only(limit=args.limit)
    elif args.full:
        run_full(limit=args.limit)
    elif args.update_db:
        update_rag_db()
    else:
        print("사용법:")
        print("  python api/tools/run_pipeline.py --check")
        print("  python api/tools/run_pipeline.py --labels-only")
        print("  python api/tools/run_pipeline.py --labels-only --limit 50")
        print("  python api/tools/run_pipeline.py --update-db")
        parser.print_help()
