"""
convert_npy_to_json.py ─ *_joints.npy 파일을 프론트엔드용 JSON으로 변환
"""

import argparse
import json
import numpy as np
from pathlib import Path

# ── 설정 ──────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_DIR = BASE_DIR / "frontend" / "data" / "joint_cache"


def main():
    parser = argparse.ArgumentParser(
        description="*_joints.npy 파일들을 프론트엔드 joint_cache JSON으로 변환"
    )
    parser.add_argument(
        "--npy-dir", required=True, type=Path,
        help="*_joints.npy 파일들이 있는 디렉토리",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR,
        help=f"JSON 출력 디렉토리 (기본: {DEFAULT_OUTPUT_DIR})",
    )
    args = parser.parse_args()

    npy_dir: Path = args.npy_dir
    output_dir: Path = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    if not npy_dir.exists():
        print(f"오류: {npy_dir} 폴더를 찾을 수 없습니다.")
        return

    npy_files = list(npy_dir.glob("*_joints.npy"))
    print(f"총 {len(npy_files)}개의 npy 파일을 발견했습니다.")

    for npy_path in npy_files:
        try:
            # 파일명에서 단어 추출 (예: '두려움_joints.npy' -> '두려움')
            word = npy_path.name.replace("_joints.npy", "")

            # npy 로드 → (frames, 225) -> list of lists
            data = np.load(npy_path)
            frames = data.tolist()

            output_path = output_dir / f"{word}.json"
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump({
                    "word": word,
                    "fps": 30,  # 원본은 보통 30fps
                    "frames": frames
                }, f, ensure_ascii=False)

            print(f"  > [Converted] {word} -> {output_path.name}")

        except Exception as e:
            print(f"  > [Error] {npy_path.name}: {e}")


if __name__ == "__main__":
    main()
