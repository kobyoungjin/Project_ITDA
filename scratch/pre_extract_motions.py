import sys
from pathlib import Path

# 루트 경로 추가
ROOT_DIR = Path(__file__).parent.parent.resolve()
sys.path.append(str(ROOT_DIR))

from api.services.motion_extractor import MotionExtractor, DIALOGUE_WORDS_MAP

def main():
    print("[ITDA Pre-Extractor] 대화 모델 80단어 관절 데이터 일괄 자동 빌드 시작...")
    
    extractor = MotionExtractor()
    output_dir = ROOT_DIR / "frontend" / "data" / "ksl_motions"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    words = list(DIALOGUE_WORDS_MAP.keys())
    total = len(words)
    skipped = 0
    success = 0
    failed = 0
    
    for idx, word in enumerate(words, 1):
        safe_name = extractor.get_safe_name(word)
        target_file = output_dir / f"{safe_name}.json"
        
        if target_file.exists():
            print(f"[{idx}/{total}] [SKIP] '{word}' -> 이미 파일이 존재합니다: {target_file.name}")
            skipped += 1
            continue
            
        print(f"[{idx}/{total}] [BUILD] '{word}' 데이터 추출 시작...")
        try:
            ok = extractor.extract_and_save(word)
            if ok:
                print(f"  └ [SUCCESS] '{word}' 추출 완료 및 저장 완료!")
                success += 1
            else:
                print(f"  └ [FAILED] '{word}' 비디오 또는 랜드마크 추출 실패.")
                failed += 1
        except Exception as e:
            print(f"  └ [ERROR] '{word}' 빌드 중 오류 발생: {e}")
            failed += 1
            
    print("\n==================================================")
    print(f"  빌드 작업 완료! (총 {total}단어)")
    print(f"  - 스킵(이미 존재): {skipped}")
    print(f"  - 성공(신규 추출): {success}")
    print(f"  - 실패: {failed}")
    print("==================================================")

if __name__ == "__main__":
    main()
