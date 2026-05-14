import json
import random

def get_daily_words():
    with open('api/data/sign_video_urls.json', 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    keys = list(data.keys())
    
    # 일상생활 키워드 리스트
    daily_keywords = [
        '안녕', '고맙', '미안', '사랑', '이름', '어디', '언제', '무엇', '왜', 
        '어떻게', '좋아', '괜찮', '먹다', '마시다', '가다', '오다', '집', 
        '학교', '회사', '사람', '친구', '가족', '오늘', '내일', '어제', 
        '지금', '돈', '밥', '물', '커피', '전화', '공부', '운동', '인사', '부탁'
    ]
    
    # 키워드가 포함된 단어들 필터링
    filtered = [k for k in keys if any(kw in k for kw in daily_keywords)]
    
    # 20개 랜덤 선택 (랜덤 시드 고정)
    random.seed(42)
    selected = random.sample(filtered, min(len(filtered), 20))
    
    return selected

if __name__ == "__main__":
    words = get_daily_words()
    print(json.dumps(words, ensure_ascii=False))
