import sys
from pathlib import Path

# Add project root to sys.path
project_root = Path(__file__).parent.parent
sys.path.append(str(project_root))

from api.services.motion_extractor import motion_extractor, DIALOGUE_WORDS_MAP

def extract_all():
    words = list(DIALOGUE_WORDS_MAP.keys())
    total = len(words)
    print(f"총 {total}개 단어의 모션(NPY 관절 데이터) 추출을 시작합니다.")
    
    success_count = 0
    fail_count = 0
    
    for i, word in enumerate(words):
        print(f"[{i+1}/{total}] '{word}' 추출 중...")
        success = motion_extractor.extract_and_save(word)
        if success:
            success_count += 1
        else:
            fail_count += 1
            
    print(f"\n추출 완료! (성공: {success_count}, 실패: {fail_count})")

if __name__ == "__main__":
    extract_all()
