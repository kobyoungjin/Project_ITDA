import json
from pathlib import Path

WORDS = [
    "안녕하세요", "처음", "만나다", "반갑다", "나", "정말", "이름", "농어", "당신", "무엇",
    "청인", "좋다", "혹시", "말", "잘", "들리다", "네", "아주", "목소리", "참",
    "행복", "발음", "조금", "서툴다", "이해", "부탁", "걱정", "없다", "천천히", "모두",
    "가능하다", "위해", "당연", "더", "정확히", "이야기", "약속", "감사", "안", "때",
    "글씨", "쓰다", "보여주다", "괜찮다", "생각", "스마트폰", "화면", "적다", "배려", "감동",
    "오늘", "날씨", "맞다", "하늘", "맑다", "바람", "시원", "기분", "평소", "어떤",
    "음식", "가장", "좋아하다", "따뜻하다", "국수", "요리", "면", "다음", "같이", "먹다",
    "가다", "와", "꼭", "맛있다", "친절", "대화", "즐겁다", "앞으로", "우리", "자주"
]

def find_best_key(word, keys):
    # 1. Exact match in split keys
    for k in keys:
        parts = [p.strip() for p in k.split(',')]
        if word in parts:
            return k
    # 2. Fuzzy match in split keys
    for k in keys:
        parts = [p.strip() for p in k.split(',')]
        for p in parts:
            if word in p:
                return k
    return None

def main():
    urls_path = Path("api/data/sign_video_urls.json")
    with open(urls_path, "r", encoding="utf-8") as f:
        urls_data = json.load(f)
        
    keys = list(urls_data.keys())
    
    found = {}
    missing = []
    
    for w in WORDS:
        k = find_best_key(w, keys)
        if k:
            found[w] = k
        else:
            missing.append(w)
            
    print(f"Total Words: {len(WORDS)}")
    print(f"Found: {len(found)}")
    print(f"Missing: {len(missing)}")
    
    # Save the mapping
    mapping_path = Path("scratch/dialogue_word_mapping.json")
    with open(mapping_path, "w", encoding="utf-8") as f:
        json.dump({"found": found, "missing": missing}, f, ensure_ascii=False, indent=2)
        
    print(f"Mapping saved to {mapping_path}")
    print("\nMissing words:")
    print(", ".join(missing))

if __name__ == "__main__":
    main()
