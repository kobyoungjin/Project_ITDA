import os
import sys
import json
import anyio
import joblib
from pathlib import Path

# Add project root to python path
sys.path.append(str(Path(__file__).parent.parent))

# Import collect module to monkey patch
import api.routers.collect

# Monkey patch paths
CUSTOM_CSV = Path("api/data/ksl_training/ksl_dataset_dialogue.csv")
CUSTOM_MODEL = Path("api/data/ksl_training/knn_model_dialogue.pkl")

api.routers.collect.CSV_PATH = CUSTOM_CSV
api.routers.collect.MODEL_PATH = CUSTOM_MODEL

from api.routers.collect import collect_from_url, train_knn_model

DIALOGUE_WORDS_MAP = {
    "안녕하세요": "안녕하세요,안녕하십니까,안녕히 가십시오,안녕히 계세요",
    "처음": "처음,시작,우선,초",
    "만나다": "만나다",
    "반갑다": "반갑다,반기다,재미,흥,흥취,희열,즐겁다,즐기다",
    "나": "자신,나,저,내",
    "정말": "사실,정말,진짜,참,맞다,정말로",
    "이름": "이름,명,성명,성함",
    "농어": "농인,농아인",
    "당신": "당신",
    "무엇": "어느,무엇,어떤,무슨,뭐,아무,어디",
    "청인": "난청인,난청자",
    "좋다": "좋다,선",
    "혹시": "혹시,혹,혹여",
    "말": "말,말하다,언어",
    "잘": "잘하다,잘",
    "들리다": "듣다,소리,소식,청각",
    "네": "너,네,자네",
    "아주": "크다,꽤,매우,몹시,무척,아주,대,대단히",
    "목소리": "목소리,음성,발음,목청,언성,부르다",
    "참": "사실,정말,진짜,참,맞다,정말로",
    "행복": "행복,복",
    "발음": "목소리,음성,발음,목청,언성,부르다",
    "조금": "작다,다소,약간,조금,약소하다,자그마하다,적다,조그마하다",
    "서툴다": "미숙하다",
    "이해": "이해,납득,양해",
    "부탁": "당부,부탁,요청,청하다,요구",
    "걱정": "걱정,근심,상심,시름,염려,우수,괴롭다",
    "없다": "없다,비다",
    "천천히": "지각,지체,늦다,굼뜨다,느리다,더디다,천천하다,서서히",
    "모두": "모두,온통,전부,전체,제반,모든,온,다,모조리,몽땅,죄다",
    "가능하다": "가능,할 수 있다",
    "위해": "위하다,-러",
    "당연": "당연하다,마땅하다,응당하다",
    "더": "더,게다가,더구나,추가,더욱,더군다나",
    "정확히": "명확하다,정확,똑똑하다,뚜렷하다,명료하다,명백하다,분명하다,선명하다,확실하다,단연,역력하다,장장하다,틀림없이",
    "이야기": "이야기,강의,설교",
    "약속": "꼭,약속,-야,필수,필시",
    "감사": "감사합니다,감사,고맙다",
    "안": "속,내부,안쪽,안",
    "때": "더럽다,때,불결,지저분하다",
    "글씨": "서예,붓글씨,붓글",
    "쓰다": "이론,쓰다",
    "보여주다": "보여주다",
    "괜찮다": "괜찮다,무방하다",
    "생각": "생각,견해,사고,신경,의견,의사,의식,여기다",
    "스마트폰": "휴대전화,핸드폰,휴대폰,휴대전화기",
    "화면": "백지,용지,종이",
    "적다": "필기,쓰다,적다,쓰기,저술,서술",
    "배려": "양보",
    "감동": "감동",
    "오늘": "오늘,금일,이번,오늘날,현재",
    "날씨": "하늘,개다",
    "맞다": "사실,정말,진짜,참,맞다,정말로",
    "하늘": "하늘,개다",
    "맑다": "결백,깔끔하다,깨끗하다,말끔하다,산뜻하다,소박하다,순결,순수,정결,청결",
    "바람": "바람,바람이 불다,가을,불다",
    "시원": "시원하다,평화,화평",
    "기분": "감정,기분,정서",
    "평소": "평상,평상시,평소",
    "어떤": "어느,무엇,어떤,무슨,뭐,아무,어디",
    "음식": "식당,음식점",
    "가장": "일등,으뜸,제일,최고,가장,맨,수석",
    "좋아하다": "좋다,선",
    "따뜻하다": "남쪽,남,따뜻하다,봄,포근하다",
    "국수": "국수,면",
    "요리": "요리",
    "면": "국수,면",
    "다음": "미래,다음,앞날,앞길,장래,장차,향후",
    "같이": "함께,같이,동반,랑,아울러,더불다,-끼리",
    "먹다": "막다,막히다,먹다",
    "가다": "가다",
    "와": "와,과,하고",
    "꼭": "꼭,약속,-야,필수,필시",
    "맛있다": "맛있다,맛나다,맛",
    "친절": "친절,대우,접대,서비스,대접",
    "대화": "대화,대담",
    "즐겁다": "반갑다,반기다,재미,흥,흥취,희열,즐겁다,즐기다",
    "앞으로": "미래,다음,앞날,앞길,장래,장차,향후",
    "우리": "우리,저희",
    "자주": "반복,거듭,수시로,자꾸,자주,잦다,여러 번,연거푸,재차,빈번히"
}

async def main():
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    print("[ITDA Dialogue Model] Dialogue vocabulary separate training started.")
    
    # 1. Clear old dialogue CSV
    if CUSTOM_CSV.exists():
        os.remove(CUSTOM_CSV)
        print(f"Old dialogue CSV deleted.")
        
    # 2. Load JSON
    urls_path = Path("api/data/sign_video_urls.json")
    with open(urls_path, "r", encoding="utf-8") as f:
        urls_data = json.load(f)
        
    count = 0
    total = len(DIALOGUE_WORDS_MAP)
    success_count = 0
    
    for simple_label, json_key in DIALOGUE_WORDS_MAP.items():
        count += 1
        info = urls_data.get(json_key)
        if not info or not info.get("video_url"):
            print(f"[{count}/{total}] Warning: '{simple_label}' (key: {json_key}) not found. Skipping.")
            continue
            
        url = info.get("video_url")
        print(f"[{count}/{total}] Processing '{simple_label}'... ({url})")
        try:
            res = await collect_from_url(simple_label, url)
            if res.get("ok"):
                success_count += 1
                print(f"  Success: {res.get('saved_samples')} samples.")
            else:
                print(f"  Failed: {res.get('message')}")
        except Exception as e:
            print(f"  Error processing '{simple_label}': {e}")
            
    # 3. Train
    print(f"\nStarting KNN Model training with {success_count} words...")
    res = train_knn_model(n_neighbors=5)
    
    if res.get("ok"):
        print(f"Training Complete! Saved separate model to: {CUSTOM_MODEL}")
        print(f"Total {res.get('samples')} samples, {res.get('label_count')} words learned.")
        print(f"Estimated Accuracy: {res.get('accuracy')}%")
    else:
        print(f"Training Failed: {res.get('message')}")

if __name__ == "__main__":
    anyio.run(main)
