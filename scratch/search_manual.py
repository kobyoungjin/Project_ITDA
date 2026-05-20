import json
import sys
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')

def main():
    urls_path = Path("api/data/sign_video_urls.json")
    with open(urls_path, "r", encoding="utf-8") as f:
        urls_data = json.load(f)
    keys = list(urls_data.keys())
    
    queries = {
        "휴대폰/핸드폰/전화": ["휴대폰", "핸드폰", "전화"],
        "화면/액정": ["화면", "액정"],
        "배려/양보/동정": ["배려", "양보", "동정"],
        "날씨/기상/온도": ["날씨", "기상", "온도"],
        "맑다/깨끗/하늘": ["맑다", "깨끗", "하늘"],
        "좋아하다/선호/기뻐": ["좋아하다", "좋아", "선호", "기뻐"],
        "서투르다/서툴다": ["서투르", "서툴", "미숙"],
        "천천히/느리다/서서히": ["천천히", "느리다", "서서히", "천천하다"]
    }
    
    for category, words in queries.items():
        print(f"\nCategory: {category}")
        found = False
        for w in words:
            for k in keys:
                if w in k:
                    print(f"  Matched '{w}': {k}")
                    found = True
        if not found:
            print("  No matches")

if __name__ == "__main__":
    main()
