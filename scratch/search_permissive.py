import json
import sys
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')

MISSING = [
    "농어", "들리다", "서툴다", "천천히", "가능하다", "위해", "정확히", 
    "스마트폰", "화면", "배려", "날씨", "맑다", "좋아하다", "앞으로"
]

def search_substrings(word, keys):
    results = []
    # If the word is "농어", also check "농아" and "농인"
    alt_words = [word]
    if word == "농어":
        alt_words = ["농아", "농인"]
    elif word == "들리다":
        alt_words = ["듣다", "들리"]
    elif word == "서툴다":
        alt_words = ["서투", "미숙"]
    elif word == "천천히":
        alt_words = ["느리", "천천"]
    elif word == "가능하다":
        alt_words = ["가능", "수 있다"]
    elif word == "위해":
        alt_words = ["위하", "위해"]
    elif word == "정확히":
        alt_words = ["정확"]
    elif word == "좋아하다":
        alt_words = ["좋아", "선호"]
    elif word == "앞으로":
        alt_words = ["앞으로", "앞"]

    for alt in alt_words:
        for k in keys:
            if alt in k:
                results.append((alt, k))
    return results

def main():
    urls_path = Path("api/data/sign_video_urls.json")
    with open(urls_path, "r", encoding="utf-8") as f:
        urls_data = json.load(f)
        
    keys = list(urls_data.keys())
    
    for w in MISSING:
        print(f"\nWord: {w}")
        res = search_substrings(w, keys)
        if res:
            for alt, k in res[:5]:
                print(f"  Matched alt '{alt}': {k}")
        else:
            print("  No matches")

if __name__ == "__main__":
    main()
