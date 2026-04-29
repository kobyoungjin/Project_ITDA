import os
import json
import numpy as np
from pathlib import Path

# ── 설정 ──────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent
INTEL_SYL_DIR = Path(r"C:\Users\ComHolic\Downloads\intel_SYL-master")
NPY_DIR = INTEL_SYL_DIR / ".joint_cache"
OUTPUT_DIR = BASE_DIR / "frontend" / "data" / "joint_cache"

# ── 초기화 ───────────────────────────────────────────────────
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

def main():
    if not NPY_DIR.exists():
        print(f"오류: {NPY_DIR} 폴더를 찾을 수 없습니다.")
        return
        
    npy_files = list(NPY_DIR.glob("*_joints.npy"))
    print(f"총 {len(npy_files)}개의 npy 파일을 발견했습니다.")
    
    for npy_path in npy_files:
        try:
            # 파일명에서 단어 추출 (예: '두려움_joints.npy' -> '두려움')
            word = npy_path.name.replace("_joints.npy", "")
            
            # npy 로드
            data = np.load(npy_path)
            # (frames, 225) -> list of lists
            frames = data.tolist()
            
            output_path = OUTPUT_DIR / f"{word}.json"
            
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump({
                    "word": word,
                    "fps": 30, # 원본은 보통 30fps
                    "frames": frames
                }, f, ensure_ascii=False)
            
            print(f"  > [Converted] {word} -> {output_path.name}")
            
        except Exception as e:
            print(f"  > [Error] {npy_path.name}: {e}")

if __name__ == "__main__":
    main()
