import os
import json
import glob
from typing import List, Dict
from api.services.vector_db import vector_db
from api.core.config import settings

class DataPipeline:
    def __init__(self):
        self.api_url = "http://api.kcisa.kr/openapi/service/rest/meta4/getKCPG0504" # 문화데이터광장 샘플
        self.api_key = settings.CULTURE_API_KEY

    def _parse_public_data(self, raw_items: List[Dict]) -> List[Dict]:
        """
        문화데이터광장의 정제되지 않은 원시 데이터를 프론트엔드 약속 규격에 맞게 파싱합니다.
        필수 필드가 없는 데이터는 누락(필터링) 처리하여 불량 데이터를 방지합니다.
        """
        parsed_data = []
        if isinstance(raw_items, dict):
            raw_items = [raw_items] # 단일 객체 응답 예외 처리
            
        for item in raw_items:
            try:
                # 공공데이터 API의 불규칙한 키값(XML->JSON 변환 시 발생) 대응 방어 로직
                keyword = item.get("title", item.get("keyword", ""))
                description = item.get("description", item.get("content", ""))
                video_url = item.get("videoUrl", item.get("url", ""))
                
                # 메타데이터 불량 스킵 로직 (필수 값이 없으면 벡터DB 파괴 방지)
                if not keyword or not description:
                    continue
                    
                # 감정 키워드가 없을 경우를 대비한 방어 로직
                emotions = item.get("emotions", ["일반", "설명"])
                
                parsed_data.append({
                    "keyword": keyword,
                    "description": description,
                    "emotions": emotions,
                    "video_url": video_url
                })
            except Exception as e:
                print(f"[DataPipeline] 파싱 에러 발생 (해당 row 스킵됨): {e}")
                continue
                
        return parsed_data

    # [P3] 키워드 기반 감정 추론 휴리스틱
    # - AI Hub 데이터는 감정 라벨이 없어 모든 항목이 ["일상","정보전달"] 로 찍히는 문제를 완화.
    # - 키워드에 특정 토큰이 포함되면 해당 감정을 부여. 어디에도 매칭 안 되면 일반 태그 유지.
    _EMOTION_HINTS = {
        "인사":    ["안녕", "반갑", "잘가", "잘 자", "만나", "또 만"],
        "감사":    ["고마", "고맙", "감사"],
        "사과":    ["미안", "죄송"],
        "사랑":    ["사랑", "좋아", "애정"],
        "기쁨":    ["행복", "기쁘", "즐겁", "신남", "좋다"],
        "슬픔":    ["슬프", "눈물", "우울", "힘들"],
        "격려":    ["힘내", "파이팅", "응원", "할 수"],
        "경고":    ["조심", "위험", "불이", "경찰", "도와"],
        "의료":    ["병원", "아파", "약", "의사", "머리", "배가"],
        "일상":    ["밥", "물", "화장실", "집", "학교"],
        "가족":    ["엄마", "아빠", "가족", "친구", "형제", "자매"],
        "질문":    ["어디", "언제", "무엇", "왜", "뭐예요"],
    }

    @classmethod
    def _infer_emotions(cls, keyword: str) -> List[str]:
        hits: List[str] = []
        for emotion, tokens in cls._EMOTION_HINTS.items():
            if any(tok in keyword for tok in tokens):
                hits.append(emotion)
        return hits or ["일상", "정보전달"]

    def _import_aihub_json(self) -> List[Dict]:
        """
        AI Hub (유저 로컬 data/morpheme) JSON 데이터 수집.

        [P3] 개선 사항:
          1. 모든 attributes.name 을 수집(이전: [0]만 사용)
          2. 키워드(sentence) 기준 dedupe — 동일 문장 중복 제거
          3. 키워드 기반 감정 태그 자동 추론
          4. 파싱/중복/최종 통계를 로그로 노출
        """
        if not os.path.exists(settings.AI_HUB_DATA_PATH):
            print(f"[DataPipeline] 경고: AI Hub 데이터 경로를 찾을 수 없습니다. ({settings.AI_HUB_DATA_PATH})")
            return []

        json_files = glob.glob(os.path.join(settings.AI_HUB_DATA_PATH, "**", "*.json"), recursive=True)
        total_files = len(json_files)
        print(f"[DataPipeline] AI Hub JSON {total_files}개 발견 → 파싱 및 dedupe 시작")

        seen: Dict[str, Dict] = {}   # keyword → 대표 레코드 (첫 등장)
        parse_errors = 0

        for json_path in json_files:
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    content = json.load(f)

                meta = content.get("metaData", {})
                video_url = meta.get("url", "")

                # 모든 attributes 의 name 을 순서대로 수집
                words: List[str] = []
                for item in content.get("data", []):
                    for attr in item.get("attributes", []):
                        name = (attr.get("name") or "").strip()
                        if name:
                            words.append(name)

                if not words:
                    continue

                sentence = " ".join(words).strip()
                if sentence in seen:
                    continue   # dedupe: 동일 키워드 스킵

                seen[sentence] = {
                    "title": sentence,
                    "content": f"AI Hub 수어 영상. 키워드: {sentence}",
                    "emotions": self._infer_emotions(sentence),
                    "video_url": video_url,
                }
            except Exception as e:
                parse_errors += 1
                if parse_errors <= 3:
                    print(f"[DataPipeline] AI Hub JSON 파싱 에러 ({json_path}): {e}")

        unique_count = len(seen)
        dedup_ratio = (1 - unique_count / total_files) * 100 if total_files else 0
        print(f"[DataPipeline] AI Hub 결과: 파일 {total_files} → 고유 키워드 {unique_count} "
              f"(중복률 {dedup_ratio:.1f}%, 오류 {parse_errors}건)")
        return list(seen.values())

    def fetch_sign_language_data(self) -> List[Dict]:
        """문화데이터광장 API 데이터 수집 및 안전한 파싱 로직 적용"""
        raw_data = []
        is_mock_mode = True # 로컬 테스트 시에는 목업 데이터 파싱을 시뮬레이션
        
        try:
            # 실제 연동 시 주석 해제 (10초 타임아웃으로 백엔드 프리징 방지)
            # params = {"serviceKey": self.api_key, "numOfRows": 100, "pageNo": 1}
            # response = requests.get(self.api_url, params=params, timeout=10)
            # response.raise_for_status()
            # raw_data = response.json().get("response", {}).get("body", {}).get("items", {}).get("item", [])
            # is_mock_mode = False if raw_data else True
            pass
        except Exception as e:
            print(f"[DataPipeline] API 서버 통신 실패, 준비된 목업 데이터로 폴백(Fallback)합니다: {e}")
            is_mock_mode = True
            
        if is_mock_mode:
            # 외부 API에서 들어올 수 있는 여러 필드 네이밍을 시뮬레이션
            raw_data = [
                # --- [인사 및 기본 예절] ---
                {"title": "안녕하세요", "content": "오른손을 펴서 이마에서 가슴으로 내리며 상대방을 존중하는 마음을 담아 가볍게 미소짓습니다. 반가움과 친절함을 나누는 가장 기본적이고 따뜻한 인사입니다.", "emotions": ["반가움", "친절함", "따뜻함"]},
                {"title": "반갑습니다", "content": "두 손을 가슴 앞에서 살짝 맞잡으며 상대를 보고 미소짓는 동작으로 만남의 기쁨을 표현합니다.", "emotions": ["반가움", "기쁨", "환영"]},
                {"title": "고맙습니다", "content": "왼손등 위에 오른손날을 가볍게 두 번 치며, 진심 어린 감사의 마음을 표합니다. 눈을 맞추며 부드럽게 고개를 끄덕이면 온기가 더 잘 전달됩니다.", "emotions": ["감사", "진심", "따뜻함"]},
                {"title": "미안하다", "content": "오른손 엄지와 검지를 모아 이마에 대었다가 떼며 진심으로 사과하는 마음을 전합니다.", "emotions": ["미안함", "진심", "반성"]},
                {"title": "또 만나요", "content": "검지와 중지를 펴서 두 번 굽히며 다음에 다시 만날 것을 기약하는 설렘을 담은 인사입니다.", "emotions": ["기대", "작별", "친근함"]},
                {"title": "잘 자요", "content": "두 손바닥을 합쳐 뺨 아래에 대고 눈을 감으며 편안한 휴식과 안녕을 기원하는 따뜻한 작별 인사입니다.", "emotions": ["편안함", "평온", "축복"]},

                # --- [비상 및 안전] ---
                {"title": "도와주세요", "content": "한 손을 펼쳐 다른 손 아래에서 위로 받쳐주는 동작으로 간절하게 도움을 요청합니다. 당신의 곁에 누군가 꼭 함께할 거라는 믿음을 담았습니다.", "emotions": ["부탁", "의지", "간절함"]},
                {"title": "불이야", "content": "손가락을 흔들며 위로 올리는 불꽃 모양을 한 뒤, 입을 크게 벌려 긴박하게 위험을 알립니다.", "emotions": ["긴박함", "공포", "위험"]},
                {"title": "경찰", "content": "손으로 모자의 챙을 잡는 시늉을 하여 질서와 안전을 지켜주는 존재를 호출합니다.", "emotions": ["안전", "신뢰", "경계"]},
                {"title": "위험해요", "content": "두 팔을 X자로 교차하며 경고의 눈빛을 보내 상대의 안전을 진심으로 걱정하는 마음을 전합니다.", "emotions": ["걱정", "경고", "보호"]},
                {"title": "길을 잃었어요", "content": "손을 이마에 대고 주변을 두리번거리며 당혹스러운 마음과 도움의 손길을 간절히 바라는 상태를 표현합니다.", "emotions": ["당황", "불안", "의지"]},

                # --- [의료 및 건강] ---
                {"title": "아파요", "content": "아픈 부위를 가리키며 얼굴을 찡그려 고통을 표현합니다. 빨리 나으시길 바라는 마음과 위로를 동시에 전하는 감정 공유의 시작입니다.", "emotions": ["고통", "슬픔", "위로"]},
                {"title": "병원", "content": "왼쪽 팔뚝에 주사를 놓는 시늉을 하여 치료를 받을 수 있는 곳임을 나타내며 안심을 돕습니다.", "emotions": ["치료", "희망", "질환"]},
                {"title": "약", "content": "손바닥 위에 작은 알약을 올려 입으로 가져가는 동작을 하여 회복을 위한 정성을 표현합니다.", "emotions": ["회복", "정성", "안정"]},
                {"title": "머리가 아파요", "content": "한 손으로 머리를 짚고 괴로운 표정을 지으며 상대의 공감과 보살핌이 필요함을 알립니다.", "emotions": ["괴로움", "도움", "돌봄"]},
                {"title": "배가 아파요", "content": "배를 손으로 문지르며 불편한 상태를 알립니다. 따뜻한 손길과 배려가 필요한 순간입니다.", "emotions": ["불편", "걱정", "보살핌"]},
                {"title": "의사", "content": "손목의 맥을 짚는 동작으로 전문적인 도움을 줄 수 있는 사람에 대한 신뢰를 표현합니다.", "emotions": ["신뢰", "전문성", "기대"]},

                # --- [일상 및 생활] ---
                {"title": "배고파요", "content": "손으로 배 주위를 가볍게 쓸어내리며 허기진 상태와 식사에 대한 기대를 수줍게 표현합니다.", "emotions": ["기대", "허기", "친근함"]},
                {"title": "밥", "content": "손가락을 모아 입 주위로 가져가는 동작으로 생명을 유지하는 소중한 양식에 대한 감사를 담았습니다.", "emotions": ["일상", "필수", "감사"]},
                {"title": "물", "content": "엄지와 검지를 L자로 만들어 턱 옆에 대며 생명의 근원이 되는 시원함을 갈구하는 마음을 전합니다.", "emotions": ["갈증", "필요", "일상"]},
                {"title": "화장실", "content": "주먹 쥔 손의 새끼손가락을 세워 가볍게 흔들며 조심스럽고 일상적인 생리적 필요를 알립니다.", "emotions": ["필요", "조심스러움", "일상"]},
                {"title": "어디에요", "content": "손바닥을 위로 하여 좌우로 살짝 흔들며 길을 찾는 호기심과 목적지에 대한 열망을 표현합니다.", "emotions": ["호기심", "탐색", "기대"]},
                {"title": "맛있어요", "content": "볼을 손바닥으로 가볍게 치며 환하게 웃어 음식에서 오는 큰 행복과 만족감을 나눕니다.", "emotions": ["행복", "만족", "기쁨"]},
                {"title": "얼마예요", "content": "검지와 엄지를 비비며 가치와 교환에 대한 궁금증을 표현합니다. 서로 존중하는 거래의 시작입니다.", "emotions": ["관심", "궁금함", "현실적"]},

                # --- [감정 및 격려] ---
                {"title": "힘내세요", "content": "두 주먹을 꽉 쥐고 가슴 앞으로 힘있게 내밀며 상대가 어려움을 이겨내길 바라는 뜨거운 응원을 보냅니다.", "emotions": ["응원", "열정", "우정"]},
                {"title": "행복해요", "content": "두 손으로 가슴을 따스하게 쓸어내리며 마음속 가득 차오르는 기쁨과 평온함을 나눕니다.", "emotions": ["기쁨", "평온", "충만함"]},
                {"title": "괜찮아요", "content": "손을 앞으로 내밀어 살짝 흔들며 부드럽게 미소짓습니다. 걱정 말라는 따뜻한 위로와 안심의 표현입니다.", "emotions": ["위로", "안심", "따뜻함"]},
                {"title": "사랑합니다", "content": "두 팔로 자신을 가볍게 안는 동작으로 상대방에게 깊은 애정과 사랑을 전합니다. 온 세상이 따뜻해지는 마법의 언어입니다.", "emotions": ["사랑", "애정", "온기"]},
                {"title": "슬퍼요", "content": "눈가에서 손가락을 내리며 눈물을 시뮬레이션하고 고개를 숙여 마음의 아픔을 함께 나누고 싶어 합니다.", "emotions": ["슬픔", "애상", "공감"]},
                {"title": "무서워요", "content": "가슴 앞에서 두 손을 가볍게 떨며 보호와 위로가 필요한 두려운 마음을 솔직하게 표현합니다.", "emotions": ["두려움", "불안", "보호"]},

                # --- [관계 및 사람] ---
                {"title": "엄마", "content": "엄지손가락을 볼에 대었다가 떼며 세상에서 가장 포근하고 무조건적인 사랑을 주는 존재를 부릅니다.", "emotions": ["그리움", "편안함", "사랑"]},
                {"title": "아빠", "content": "주먹 쥔 손의 엄지를 세워 턱 옆에 대며 든든한 버팀목이 되어주는 존재에 대한 존경을 표합니다.", "emotions": ["든든함", "존경", "신뢰"]},
                {"title": "친구", "content": "검지 두 개를 서로 맞대어 흔들며 서로의 마음이 연결된 다정하고 수평적인 관계를 축복합니다.", "emotions": ["친밀함", "즐거움", "우정"]},
                {"title": "선생님", "content": "오른손 엄지와 검지로 동그라미를 만들어 가슴 높이에서 내밀어 존경과 배움의 의지를 표현합니다.", "emotions": ["존경", "배움", "신뢰"]},
                {"title": "우리", "content": "검지로 자신과 상대를 아우르는 큰 원을 그리며 모두가 하나로 연결되어 있다는 공동체 의식을 나눕니다.", "emotions": ["연결", "일체감", "따뜻함"]},

                # --- [시간 및 자연] ---
                {"title": "오늘", "content": "두 손바닥을 아래로 하여 가슴 높이에서 살짝 누르며 현재 우리가 함께 숨 쉬고 있는 소중한 순간을 나타냅니다.", "emotions": ["현재", "소중함", "일상"]},
                {"title": "내일", "content": "검지를 펴서 턱 옆에서 앞으로 내밀며 다가올 시간들에 대한 희망과 설렘을 표현합니다.", "emotions": ["희망", "미래", "기대"]},
                {"title": "지금", "content": "두 손을 단호하면서도 부드럽게 아래로 내리며 현재의 중요성과 집중을 강조합니다.", "emotions": ["집중", "중요", "현존"]},
                {"title": "덥다", "content": "손등으로 이마의 땀을 닦는 시늉을 하며 뜨거운 열기 속에서도 함께 견뎌내는 활기를 표현합니다.", "emotions": ["열기", "활기", "자연"]},
                {"title": "춥다", "content": "두 팔을 감싸고 몸을 가볍게 떨며 서로의 온기가 필요한 계절을 표현하고 따뜻함을 소망합니다.", "emotions": ["추위", "그리움", "온기"]},
                {"title": "비", "content": "손가락을 아래로 흔들며 대지를 적시는 생명수 같은 비의 풍요로움을 표현합니다.", "emotions": ["풍요", "차분함", "자연"]},

                # --- [기타 유용한 표현] ---
                {"title": "힘들어요", "content": "어깨를 아래로 늘어뜨리고 한숨을 쉬는 시늉을 하며 잠시 쉬어가고 싶은 마음과 위로를 요청합니다.", "emotions": ["피로", "쉼", "위로"]},
                {"title": "할 수 있어요", "content": "주먹을 꽉 쥐고 끄덕이며 자신감과 무한한 가능성을 믿는 긍정의 에너지를 전파합니다.", "emotions": ["자신감", "긍정", "용기"]},
                {"title": "기다려주세요", "content": "손바닥을 앞으로 내밀어 고요하게 멈추며 서로의 속도를 존중하는 배려의 시간을 가집니다.", "emotions": ["인내", "배려", "신중함"]},
                {"title": "좋아하다", "content": "엄지와 검지로 턱을 가볍게 튕기며 마음속에서 피어나는 호감과 설레는 감정을 수줍게 고백합니다.", "emotions": ["호감", "설렘", "기쁨"]},
                {"title": "가다", "content": "손을 앞으로 밀어내며 새로운 세계나 목적지를 향한 발걸음과 모험을 축복합니다.", "emotions": ["모험", "향함", "활동"]},
                {"title": "오다", "content": "손을 자신 쪽으로 당기며 소중한 누군가와의 만남과 환영의 마음을 표현합니다.", "emotions": ["환영", "만남", "기쁨"]},
                {"title": "이름이 뭐예요", "content": "한 손으로 다른 손의 손바닥을 두드리며 질문의 억양으로 고개를 약간 내밉니다. 처음 만나는 사람에게 상냥하게 이름을 묻는 표현입니다.", "emotions": ["호기심", "친근함", "설렘"]},
            ]
            
        # AI Hub 데이터셋 병합
        aihub_parsed = self._import_aihub_json()
        raw_data.extend(aihub_parsed)
            
        # _parse_public_data 함수를 통해 프론트엔드가 요구하는 정제된 규격(JSON)으로 변환
        return self._parse_public_data(raw_data)

    def process_and_store(self, force_refresh=False):
        """데이터 수집 및 FAISS 저장을 수행하는 파이프라인 (항상 새로고침하여 최신 데이터 반영)"""
        # 강제 새로고침이 아니고, 이미 캐시에서 불러온 데이터가 있다면 스킵
        if not force_refresh and vector_db.index.ntotal > 0:
            print("[DataPipeline] 기존 오프라인 캐시가 존재합니다. 데이터 파이프라인 연산을 생략합니다.")
            return len(vector_db.metadata)

        # 새로운 데이터를 위해 기존 인덱스 초기화 (캡슐화된 clear() 사용)
        vector_db.clear()
        
        data = self.fetch_sign_language_data()
        
        texts_to_embed = []
        metas = []
        
        for item in data:
            # 단순 단어가 아닌 의미와 감정을 합친 문맥 벡터화로 RAG 퍼포먼스 극대화
            context = f"키워드: {item['keyword']}, 의미: {item['description']}, 감정: {', '.join(item['emotions'])}"
            texts_to_embed.append(context)
            metas.append(item)
            
        vector_db.add_data(texts_to_embed, metas)
        return len(data)

data_pipeline = DataPipeline()
