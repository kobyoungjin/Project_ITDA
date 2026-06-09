import unicodedata
from supabase import create_client, Client
from api.core.config import settings


class SupabaseService:
    """
    신 스키마(sign_lemma / sign_motion / sign_alias) 기반 Supabase 서비스.

    조회 우선순위:
      1. v_sign_canonical 뷰 — word 로 exact match (is_canonical=true 보장)
      2. v_sign_canonical_by_alias 뷰 — alias 로 조회 (사랑합니다 → 사랑)
      3. 하드코딩 SYNONYMS 테이블 → canonical 단어로 재시도
      4. [폴백] 구 테이블 sign_language_data — 신 스키마 이전 완료 전까지 유지

    응답 포맷 (motion_data):
      {
        "id": word,
        "version": "v3",
        "source": "mediapipe-v27",
        "space": "world",
        "fps": float,
        "frame_count": int,
        "parent_chain": {...},
        "keyframes": [{time, bones, morphs}, ...]
      }
    """

    SYNONYMS = {
        # 감사/인사
        "감사": "감사", "고맙습니다": "감사", "고맙다": "감사", "고마워": "감사",
        "고마워요": "감사", "고맙구만": "감사", "고맙구나": "감사", "고맙죠": "감사",
        "감사해요": "감사", "감사합니다": "감사", "감사드립니다": "감사",
        "인사": "안녕하세요", "안녕하세요": "안녕하세요", "안녕": "안녕하세요",
        "미안": "미안합니다", "죄송": "미안합니다", "미안해": "미안합니다",
        "미안해요": "미안합니다", "죄송합니다": "미안합니다", "죄송해요": "미안합니다",

        # 가족
        "엄마": "어머니", "어머니": "어머니", "아빠": "아버지", "아버지": "아버지",
        "선생님": "선생님", "선생": "선생님",
        "친구": "친구",

        # 시간/일상
        "오늘": "오늘", "내일": "내일", "어제": "어제",
        "지금": "지금",
        "밥": "밥", "식사": "밥",
        "물": "물",

        # 감정/상태
        "사랑": "사랑", "사랑해": "사랑", "사랑해요": "사랑", "사랑합니다": "사랑",
        "사랑하다": "사랑", "사랑했어": "사랑", "사랑했어요": "사랑",
        "슬퍼": "슬프다", "슬픔": "슬프다", "슬퍼요": "슬프다",
        "슬펐어": "슬프다", "슬프구나": "슬프다",
        "기뻐": "기쁘다", "기쁨": "기쁘다", "좋아": "기쁘다",
        "기뻤어": "기쁘다", "기쁘구나": "기쁘다",
        "몰라": "모르다", "모르겠어": "모르다", "모름": "모르다",
        "몰라요": "모르다", "모르겠어요": "모르다",
        "두렵다": "두려움", "무섭다": "두려움", "무서워": "두려움",
        "무서워요": "두려움", "무섭구나": "두려움",

        # ── ㅂ불규칙 활용형 ──────────────────────────────────────
        "반갑다": "반갑다", "반가워": "반갑다", "반가워요": "반갑다",
        "반갑습니다": "반갑다", "반갑구만": "반갑다", "반갑구나": "반갑다",
        "반가웠어": "반갑다", "반가웠어요": "반갑다", "반가웠습니다": "반갑다",
        "반갑죠": "반갑다", "반가워서": "반갑다", "반가운": "반갑다",
        "반갑다고": "반갑다", "반갑다며": "반갑다", "반갑다면서": "반갑다",
        "반갑게": "반갑다",
        "아름답다": "아름답다", "아름다워": "아름답다", "아름다워요": "아름답다",
        "아름다웠어": "아름답다", "아름다운": "아름답다", "아름답게": "아름답다",
        "어렵다": "어렵다", "어려워": "어렵다", "어려워요": "어렵다",
        "어려웠어": "어렵다", "어려운": "어렵다", "어렵게": "어렵다",
        "쉽다": "쉽다", "쉬워": "쉽다", "쉬워요": "쉽다",
        "쉬웠어": "쉽다", "쉬운": "쉽다", "쉽게": "쉽다",
        "즐겁다": "즐겁다", "즐거워": "즐겁다", "즐거워요": "즐겁다",
        "즐거웠어": "즐겁다", "즐거운": "즐겁다", "즐겁게": "즐겁다", "즐겁구나": "즐겁다",
        "귀엽다": "귀엽다", "귀여워": "귀엽다", "귀여워요": "귀엽다",
        "귀여웠어": "귀엽다", "귀여운": "귀엽다", "귀엽게": "귀엽다",
        "덥다": "덥다", "더워": "덥다", "더워요": "덥다",
        "더웠어": "덥다", "더운": "덥다", "덥게": "덥다",
        "춥다": "춥다", "추워": "춥다", "추워요": "춥다",
        "추웠어": "춥다", "추운": "춥다", "춥게": "춥다",
        "맵다": "맵다", "매워": "맵다", "매워요": "맵다",
        "매웠어": "맵다", "매운": "맵다", "맵게": "맵다",
        "가볍다": "가볍다", "가벼워": "가볍다", "가벼워요": "가볍다",
        "가벼웠어": "가볍다", "가벼운": "가볍다", "가볍게": "가볍다",
        "무겁다": "무겁다", "무거워": "무겁다", "무거워요": "무겁다",
        "무거웠어": "무겁다", "무거운": "무겁다", "무겁게": "무겁다",
        "뜨겁다": "뜨겁다", "뜨거워": "뜨겁다", "뜨거워요": "뜨겁다",
        "뜨거웠어": "뜨겁다", "뜨거운": "뜨겁다", "뜨겁게": "뜨겁다",
        "차갑다": "차갑다", "차가워": "차갑다", "차가워요": "차갑다",
        "차가웠어": "차갑다", "차가운": "차갑다", "차갑게": "차갑다",
        "부드럽다": "부드럽다", "부드러워": "부드럽다", "부드러워요": "부드럽다",
        "부드러웠어": "부드럽다", "부드러운": "부드럽다", "부드럽게": "부드럽다",

        # ── ㄷ불규칙 활용형 ──────────────────────────────────────
        "걷다": "걷다", "걸어": "걷다", "걸어요": "걷다",
        "듣다": "듣다", "들어": "듣다", "들어요": "듣다", "들리다": "듣다",
        "묻다": "묻다", "물어": "묻다", "물어요": "묻다",

        # ── 르불규칙 활용형 ──────────────────────────────────────
        "모르다": "모르다", "몰라": "모르다", "몰라요": "모르다",
        "빠르다": "빠르다", "빨라": "빠르다", "빨라요": "빠르다",
        "다르다": "다르다", "달라": "다르다", "달라요": "다르다",

        # ── ㅎ불규칙 활용형 ──────────────────────────────────────
        "파랗다": "파랗다", "파래": "파랗다", "파래요": "파랗다",
        "빨갛다": "빨갛다", "빨개": "빨갛다", "빨개요": "빨갛다",
        "노랗다": "노랗다", "노래": "노랗다", "노래요": "노랗다",
        "하얗다": "하얗다", "하얘": "하얗다", "하얘요": "하얗다",
        "까맣다": "까맣다", "까매": "까맣다", "까매요": "까맣다",

        # ── 기타 자주 쓰는 불규칙 ────────────────────────────────
        "예쁘다": "예쁘다", "이뻐": "예쁘다", "예뻐": "예쁘다",
        "예뻐요": "예쁘다", "이뻐요": "예쁘다",
        "괜찮다": "괜찮다", "괜찮아": "괜찮다", "괜찮아요": "괜찮다",
        "괜찮았어": "괜찮다", "괜찮구나": "괜찮다",
        "맛있다": "맛있다", "맛있어": "맛있다", "맛있어요": "맛있다",
        "재미있다": "재미있다", "재밌어": "재미있다", "재밌어요": "재미있다",

        # 장소/기타
        "학교": "학교", "공부": "공부",

        # ── 시나리오 1~20번 핵심 단어 (로컬 낱글자 분절 방지) ─────────────────────────
        # "인사" 는 위에서 이미 정의 (line 34)
        "처음": "처음", "만나다": "만나다", "반갑다": "반갑다",
        "나": "나", "이름": "이름", "농인": "농인", "당신": "당신", "무엇": "무엇",
        "청인": "건청인", "좋다": "좋다",
        "혹시": "혹시", "말": "말", "잘": "잘", "들리다": "듣다",
        "네": "네", "아주": "아주", "목소리": "목소리", "참": "참",
        "행복": "행복", "발음": "발음", "조금": "조금", "서툴다": "어렵다",
        "이해": "이해", "부탁": "부탁",
        "걱정": "걱정", "없다": "없다", "천천히": "느리다", "모두": "모두",
        "가능하다": "가능", "가능": "가능",
        "위해": "위하다", "위하다": "위하다",
        "당연": "당연하다", "더": "더", "정확히": "정확", "이야기": "이야기", "약속": "약속",
        "안": "안", "때": "때", "글씨": "글자",
        "쓰다": "쓰다", "보여주다": "보여주다", "괜찮다": "괜찮다",
        "생각": "생각", "스마트폰": "휴대전화", "화면": "모니터",
        "적다": "적다",
        "배려": "친절", "감동": "감동", "오늘": "오늘", "날씨": "기상",
        "맞다": "맞다", "하늘": "하늘", "맑다": "기상", "바람": "바람",
        "시원": "시원하다", "기분": "기분",
        "평소": "평소", "어떤": "어떤", "음식": "식사", "가장": "가장", "좋아하다": "좋다",
        "따뜻하다": "따뜻하다", "국수": "국수", "요리": "요리",
        "면": "면", "다음": "다음", "같이": "같이", "먹다": "먹다", "가다": "가다",
        "와": "와", "꼭": "꼭", "맛있다": "맛있다",
        "친절": "친절", "대화": "대화", "정말": "정말",
        "즐겁다": "즐겁다", "앞으로": "앞", "우리": "우리", "자주": "자주",
    }

    def __init__(self):
        self.url = settings.SUPABASE_URL
        # service_role 키가 있으면 RLS 우회 가능 → 우선 사용
        self.key = settings.SUPABASE_SERVICE_KEY or settings.SUPABASE_KEY
        self.client: Client = None
        self._words_canonical: list[str] = []
        self._lookup: dict[str, str] = {}

        if self.url and self.key:
            self.client = create_client(self.url, self.key)
            self._refresh_word_cache()

    @staticmethod
    def _norm(text: str) -> str:
        if not text:
            return ""
        return unicodedata.normalize("NFC", text).strip()

    def _refresh_word_cache(self) -> None:
        """
        신 스키마의 sign_lemma + sign_alias 를 캐시.

        - sign_lemma.word → canonical
        - sign_alias.alias → lemma.word (canonical)
        """
        try:
            # 1) 표제어 목록 (신 스키마)
            res_lemma = self.client.table("sign_lemma").select("word").execute()
            new_words = [r["word"] for r in (res_lemma.data or []) if r.get("word")]

            # 2) alias 목록 (신 스키마)
            res_alias = (
                self.client
                .table("sign_alias")
                .select("alias, sign_lemma(word)")
                .execute()
            )
            alias_map: dict[str, str] = {}
            for r in (res_alias.data or []):
                alias = r.get("alias")
                lemma_info = r.get("sign_lemma") or {}
                canonical = lemma_info.get("word") if isinstance(lemma_info, dict) else None
                if alias and canonical:
                    alias_map[self._norm(alias)] = canonical

        except Exception as e:
            print(f"[SupabaseService] 신 스키마 캐시 실패 → 구 스키마 폴백: {e}")
            # 구 스키마 폴백
            try:
                res_old = self.client.table("sign_language_data").select("word").execute()
                new_words = [r["word"] for r in (res_old.data or []) if r.get("word")]
            except Exception as e2:
                print(f"[SupabaseService] 구 스키마 캐시도 실패: {e2}")
                return
            alias_map = {}

        self._words_canonical = new_words
        self._lookup.clear()

        for canonical in new_words:
            self._lookup[self._norm(canonical)] = canonical
            # 구 스키마 콤마 alias 호환 ('사랑,사랑합니다' 형태)
            for piece in canonical.split(","):
                p = self._norm(piece)
                if p and p not in self._lookup:
                    self._lookup[p] = canonical

        # 신 스키마 alias 추가
        for alias_norm, canonical in alias_map.items():
            if alias_norm not in self._lookup:
                self._lookup[alias_norm] = canonical

        print(
            f"[SupabaseService] 캐시 완료: "
            f"canonical={len(new_words)}, alias 포함={len(self._lookup)}"
        )

    def resolve(self, query: str) -> str | None:
        """입력 단어를 canonical word 로 해석. 매칭 실패 시 None."""
        if not query:
            return None
        q = self._norm(query)
        hit = self._lookup.get(q)
        if hit:
            return hit
        # 하드코딩 동의어 → canonical 재시도
        synonym = self.SYNONYMS.get(q)
        if synonym:
            hit = self._lookup.get(self._norm(synonym))
            if hit:
                return hit
        return None

    def get_motion_data(self, word: str):
        """
        단어의 canonical 모션 데이터를 반환.

        조회 순서:
          1. v_sign_canonical 뷰 (신 스키마, is_canonical=true)
          2. v_sign_canonical_by_alias 뷰 (alias → canonical)
          3. 구 sign_language_data (폴백)
        """
        if not self.client:
            return None

        canonical = self.resolve(word)
        if not canonical:
            # SYNONYMS에서 직접 찾기 (resolve 캐시 미스 대비)
            syn = self.SYNONYMS.get(self._norm(word))
            canonical = syn if syn else word

        # ── 0단계: 비디오 URL 조회 (투명 webm 우선) ───────────────────
        video_url = None
        # canonical 및 SYNONYMS 대체어에서 순차 탐색
        video_candidates = [canonical]
        syn_target = self.SYNONYMS.get(self._norm(canonical))
        if syn_target and syn_target != canonical:
            video_candidates.append(syn_target)
        for vc in video_candidates:
            if video_url:
                break
            try:
                url_res = self.client.table("sign_lemma").select("sign_source_video(video_url)").eq("word", vc).execute()
                if url_res.data and url_res.data[0].get("sign_source_video"):
                    for vid in url_res.data[0]["sign_source_video"]:
                        if "sign_videos" in vid.get("video_url", ""):
                            video_url = vid["video_url"]
                            break
                    if not video_url:
                        video_url = url_res.data[0]["sign_source_video"][0]["video_url"]
            except Exception as e:
                print(f"[SupabaseService] video_url 조회 실패 ({vc}): {e}")

        # ── 1단계: 신 스키마 v_sign_canonical 뷰 ─────────────────────
        try:
            res = (
                self.client
                .table("v_sign_canonical")
                .select("word, algo_version, fps, frame_count, parent_chain, keyframes")
                .eq("word", canonical)
                .limit(1)
                .execute()
            )
            if res.data:
                row = res.data[0]
                motion = self._build_motion_payload(row)
                if video_url:
                    motion["video_url"] = video_url
                print(f"[SupabaseService] 신 스키마 조회 성공: {canonical} ({row.get('algo_version')})")
                return {"word": row["word"], "motion_data": motion, "resolved_from": word}
        except Exception as e:
            print(f"[SupabaseService] v_sign_canonical 조회 실패: {e}")

        # ── 2단계: v_sign_canonical_by_alias 뷰 (alias 검색) ─────────
        try:
            res_alias = (
                self.client
                .table("v_sign_canonical_by_alias")
                .select("query, canonical_word, algo_version, fps, frame_count, parent_chain, keyframes")
                .eq("query", word)
                .limit(1)
                .execute()
            )
            if res_alias.data:
                row = res_alias.data[0]
                motion = self._build_motion_payload(row, word_key="canonical_word")
                if video_url:
                    motion["video_url"] = video_url
                print(f"[SupabaseService] alias 조회 성공: {word} → {row.get('canonical_word')}")
                return {
                    "word": row["canonical_word"],
                    "motion_data": motion,
                    "resolved_from": word,
                }
        except Exception as e:
            print(f"[SupabaseService] v_sign_canonical_by_alias 조회 실패: {e}")

        # ── 3단계: 구 스키마 sign_language_data 폴백 ─────────────────
        try:
            res_old = (
                self.client
                .table("sign_language_data")
                .select("word, keypoints_json")
                .eq("word", canonical)
                .execute()
            )
            if res_old.data:
                data = res_old.data[0]
                payload = data["keypoints_json"]
                if isinstance(payload, list) and payload:
                    payload = payload[-1]
                
                # [Optimization] version 정보를 source 필드로 복사하여 프론트엔드 리타겟팅 보정에 활용
                if isinstance(payload, dict):
                    version = payload.get("version", "v26.0-master")
                    if "source" not in payload:
                        payload["source"] = version
                    if video_url:
                        payload["video_url"] = video_url
                
                print(f"[SupabaseService] 구 스키마 폴백 성공: {canonical} ({payload.get('source')})")
                return {"word": data["word"], "motion_data": payload, "resolved_from": word}
        except Exception as e:
            print(f"[SupabaseService] 구 스키마 폴백 실패: {e}")

        # ── 4단계: 모션 데이터 없어도 video_url이 있으면 영상만 반환 ────
        if video_url:
            print(f"[SupabaseService] 모션 없음, 영상만 반환: {canonical} ({video_url[-50:]})")
            return {
                "word": canonical,
                "motion_data": {"video_url": video_url, "keyframes": []},
                "resolved_from": word,
            }

        return None

    def get_all_video_urls(self) -> dict:
        """sign_videos 버킷의 투명 webm URL을 단어별로 일괄 반환."""
        if not self.client:
            return {}
        try:
            res = self.client.table("sign_source_video").select(
                "lemma_id, video_url"
            ).like("video_url", "%sign_videos%").execute()

            lemma_res = self.client.table("sign_lemma").select("id, word").execute()
            lemma_map = {r["id"]: r["word"] for r in lemma_res.data}

            result = {}
            for r in res.data:
                word = lemma_map.get(r["lemma_id"])
                url = r.get("video_url", "")
                if word and url:
                    result[word] = url
            return result
        except Exception as e:
            print(f"[SupabaseService] get_all_video_urls 실패: {e}")
            return {}

    def _build_motion_payload(self, row: dict, word_key: str = "word") -> dict:
        """
        신 스키마 row → motion_loader_v3.js 호환 포맷 변환.

        motion_loader_v3 가 기대하는 최소 필드:
          { id, version, source, space, fps, parent_chain, keyframes }
        keyframes 각 항목: { time, bones: {name: {x,y,z,w}}, morphs: {...} }
        """
        word = row.get(word_key, "")
        keyframes_raw = row.get("keyframes") or []
        parent_chain = row.get("parent_chain") or {}

        # 신 스키마 keyframe 키: "time" (float), "bones", "morphs"
        # motion_loader_v3 도 동일 키를 기대하므로 그대로 사용 가능.
        # 단, bones 값이 dict({x,y,z,w})인지 확인 후 그대로 전달.
        keyframes = []
        for kf in keyframes_raw:
            if not isinstance(kf, dict):
                continue
            bones = kf.get("bones") or {}
            morphs = kf.get("morphs") or {}
            keyframes.append({
                "time": kf.get("time", 0.0),
                "bones": bones,
                "morphs": morphs,
            })

        return {
            "id": word,
            "version": "v3",
            "source": row.get("algo_version") or "mediapipe-v27",
            "space": "world",                   # _applyInterpolated world 경로 사용
            "fps": row.get("fps", 30.0),
            "frame_count": row.get("frame_count", len(keyframes)),
            "parent_chain": parent_chain,
            "keyframes": keyframes,
        }

    def get_all_words(self) -> list[str]:
        """canonical 단어 목록 반환 (신 + 구 스키마 합산)."""
        if self._words_canonical:
            return list(self._words_canonical)
        if not self.client:
            return []
        try:
            res = self.client.table("sign_lemma").select("word").execute()
            words = [r["word"] for r in (res.data or [])]
            if not words:
                # 구 스키마 폴백
                res2 = self.client.table("sign_language_data").select("word").execute()
                words = [r["word"] for r in (res2.data or [])]
            self._words_canonical = words
            return words
        except Exception as e:
            print(f"[SupabaseService] get_all_words 실패: {e}")
            return []

    def get_aliases(self) -> dict[str, str]:
        """디버그/관리자용: 정규화된 alias → canonical 매핑 전체."""
        return dict(self._lookup)


supabase_service = SupabaseService()
