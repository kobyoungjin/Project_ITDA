import json, sys
sys.stdout.reconfigure(encoding='utf-8')

with open('api/data/sign_video_urls.json', encoding='utf-8') as f:
    data = json.load(f)

# 최종 20개 단어 목록 (8: 이름, 20: 감사)
targets_words = [
    '나', '너', '안녕', '미안', '사랑', '친구', '집',
    '이름',       # 8번 변경
    '오늘', '내일', '가다', '오다', '먹다', '마시다',
    '알다', '있다', '좋다', '배고프다', '맛있다',
    '감사합니다',  # 20번 변경 - '감사합니다,감사,고맙다' 키 사용
]

found = []
for keyword in targets_words:
    matched = False
    for key in data.keys():
        parts = [p.strip() for p in key.split(',')]
        if keyword in parts:
            found.append({'label': keyword, 'json_key': key, 'url': data[key]['video_url']})
            matched = True
            break
    if not matched:
        print(f'[미매칭] {keyword}')

print(f'매칭된 단어 수: {len(found)}/20')
for i, item in enumerate(found, 1):
    print(f'{i:02d}. [{item["label"]}] {item["json_key"]}')
    print(f'      URL: {item["url"]}')
