"""
문장 → 모션 단어 배열 변환기.

단어 사전 = Supabase aliases (정확 인식 우선) ∪ 로컬 KSL 모션 인덱스.
알고리즘 = longest-match greedy.

사용 예:
    tokenizer.tokenize("안녕하세요 감사합니다")
    → [
        {word: "안녕하세요", source: "local", canonical: "안녕하세요"},
        {word: "감사합니다", source: "supabase", canonical: "감사"},
      ]
"""

import json
import os
import unicodedata
from typing import Optional

from api.services.supabase_service import supabase_service


# 로컬 KSL 모션 인덱스 위치. frontend 가 fetch 하는 것과 동일 파일.
_LOCAL_INDEX_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "frontend", "data", "ksl_motions", "index.json",
)
# 한글 단어 → WORDxxxx 코드 매핑 파일
_LOCAL_MAPPING_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "frontend", "data", "ksl_motions", "_mapping.json",
)


def _norm(text: str) -> str:
    if not text:
        return ""
    return unicodedata.normalize("NFC", text).strip()


class MotionTokenizer:
    """단어 사전 기반 longest-match greedy 토크나이저.

    longest-match 실패 시 활용어미·조사를 스트리핑하여 어간 재탐색.
    한국 수어(KSL)는 문법 어미를 표현하지 않으므로, 어간만 추출하면 됨.
    """

    # 분절 시 단어 경계로 취급할 구두점 / 공백.
    # 주의: '_' 는 단어 일부 (예: '두려움_A' 변형 인덱스) → boundary 에서 제외.
    _BOUNDARY_CHARS = set(" \t\n\r,./?!:;~()[]{}\"'·…—-—·　")

    # ── 활용어미 (긴 패턴 우선) ──────────────────────────────────
    # 한국 수어(KSL)는 문법 어미를 표현하지 않으므로 어간만 추출.
    _VERB_SUFFIXES = [
        # 격식체 (합쇼체)
        "하였습니다", "했습니다", "이었습니다", "였습니다",
        "합니다", "입니다", "습니다", "ㅂ니다",
        # 격식 의문
        "하였습니까", "했습니까", "합니까", "입니까", "습니까", "ㅂ니까",
        # 비격식 높임 (해요체)
        "하였어요", "했어요", "이에요", "예요",
        "해요", "어요", "아요",
        # 반말 (해체)
        "하였어", "했어", "이야", "야",
        "해", "어", "아",
        # 과거
        "하였다", "했다", "었다", "았다", "였다",
        # 기본형 / 연결 / 종결
        "하다", "되다", "이다",
        "하고", "하면", "해서", "하여", "하니", "하게",
        "하는", "했던", "할",
        # 존칭
        "하세요", "하십시오", "하셨", "하십니까",
        "세요", "십시오",
        # 종결어미 (추가)
        "구만", "구나", "군요", "군", "네요", "네",
        "지요", "죠", "잖아요", "잖아",
        "거든요", "거든", "던데요", "던데",
        "더라고요", "더라고", "더라", "더군요", "더군",
        "ㄹ게요", "ㄹ게", "ㄹ래요", "ㄹ래",
        "을게요", "을게", "을래요", "을래",
        "겠습니다", "겠어요", "겠어", "겠다", "겠지",
        # 연결어미 (추가)
        "으면서", "면서", "으면", "니까", "으니까",
        "지만", "는데", "ㄴ데", "어도", "아도",
        "어서", "아서", "으려고", "려고",
        "으러", "러", "다가", "다면", "라면",
        "듯이", "처럼", "만큼",
        # 인용 (간접화법)
        "다고요", "다고", "라고요", "라고",
        "냐고요", "냐고", "자고요", "자고",
        "다며", "라며", "다면서", "라면서",
        "다니", "다니까",
        # 관형사형 / 명사형 / 부사형
        "하는", "했던", "할", "한",
        "음", "ㅁ", "기",
        "게", "도록", "듯",
        "ㄴ", "은", "운", "을", "ㄹ",
    ]

    # ── 조사 (긴 패턴 우선) ───────────────────────────────────
    _PARTICLES = [
        "에서는", "에서도", "으로는", "으로부터", "으로서",
        "에게는", "에게도", "한테는", "한테도",
        "으로", "에서", "에게", "한테", "까지", "부터", "마저", "조차",
        "에는", "에도", "이란", "이라", "이든", "든지",
        "은", "는", "이", "가",
        "을", "를", "와", "과", "도", "만", "에",
        "의", "로", "서", "요",
    ]

    # ── 불규칙 활용 어간 매핑 ─────────────────────────────────
    # 활용 시 어간이 변하는 용언. {변형된 어간: 사전 등재 어간}
    # suffix 스트리핑 후 어간이 사전에 없으면 이 테이블로 복원 시도.
    _IRREGULAR_STEMS = {
        # ㅂ불규칙: 어간 끝 'ㅂ' → '워/와/우' 로 변환
        "반가": "반갑다", "고마": "고맙다", "아름다": "아름답다",
        "어려": "어렵다", "쉬": "쉽다", "무서": "무섭다",
        "즐거": "즐겁다", "슬퍼": "슬프다", "기뻐": "기쁘다",
        "차가": "차갑다", "뜨거": "뜨겁다", "부드러": "부드럽다",
        "가벼": "가볍다", "무거": "무겁다", "귀여": "귀엽다",
        "더": "덥다", "추": "춥다", "매": "맵다",
        # ㄷ불규칙: 어간 끝 'ㄷ' → 'ㄹ'
        "걸": "걷다", "들": "듣다", "물": "묻다",
        "깨달": "깨닫다", "실": "싣다",
        # ㅅ불규칙: 어간 끝 'ㅅ' 탈락
        "나": "낫다", "지": "짓다", "잇": "잇다",
        # 르불규칙: '르' → 'ㄹ라/ㄹ러'
        "몰": "모르다", "빨": "빠르다", "다": "다르다",
        "골": "고르다",
        # ㅎ불규칙: 어간 끝 'ㅎ' 탈락
        "파라": "파랗다", "빨가": "빨갛다", "노라": "노랗다",
        "하야": "하얗다", "까마": "까맣다",
        # 기타 자주 쓰는 불규칙
        "이뻐": "예쁘다", "예뻐": "예쁘다",
    }

    def __init__(self):
        # 정규화 단어 → 출처/카노니컬 매핑
        # value: ("supabase"|"local", canonical)
        self._dict: dict[str, tuple[str, str]] = {}
        self._build()

    def _build(self) -> None:
        # 1) 로컬 인덱스 적재 — _mapping.json(한글→코드) 우선, 그 다음 파일명이 한글인 JSON 파일
        local_count = 0
        ksl_dir = os.path.dirname(_LOCAL_INDEX_PATH)

        # 1-a) _mapping.json: {"한글단어": "WORDxxxx", ...} 형태
        try:
            with open(_LOCAL_MAPPING_PATH, "r", encoding="utf-8") as f:
                mapping = json.load(f)
            for word, code in mapping.items():
                if word == "total" or not isinstance(word, str):
                    continue
                key = _norm(word)
                if key and key not in self._dict:
                    self._dict[key] = ("local", code)  # canonical = WORDxxxx 코드
                    local_count += 1
        except FileNotFoundError:
            print(f"[Tokenizer] _mapping.json 없음: {_LOCAL_MAPPING_PATH}")
        except Exception as e:
            print(f"[Tokenizer] _mapping.json 적재 실패: {e}")

        # 1-b) 파일명이 한글인 JSON (감사.json, 가족.json 등) — 매핑에 없는 단어 보완
        try:
            for fname in os.listdir(ksl_dir):
                if not fname.endswith(".json"):
                    continue
                stem = fname[:-5]  # 확장자 제거
                # 한글이 포함된 파일명만 (WORD0001, index, _mapping 제외)
                if stem.startswith("_") or stem == "index" or not any(
                    '가' <= ch <= '힣' for ch in stem
                ):
                    continue
                key = _norm(stem)
                if key and key not in self._dict:
                    self._dict[key] = ("local", stem)
                    local_count += 1
        except Exception as e:
            print(f"[Tokenizer] 파일명 스캔 실패: {e}")

        # 1-c) index.json actions — WORDxxxx 코드 자체도 사전에 넣어야 재생 가능 (낱글자 제외)
        try:
            with open(_LOCAL_INDEX_PATH, "r", encoding="utf-8") as f:
                idx = json.load(f)
            for action in idx.get("actions", []):
                key = _norm(action)
                # 한글이 없고 길이가 2글자 이하인 경우(낱글자 오염) 스킵
                if not key or (len(key) <= 2 and not any('가' <= ch <= '힣' for ch in key)):
                    continue
                if key not in self._dict:
                    self._dict[key] = ("local", action)
                    local_count += 1
        except FileNotFoundError:
            print(f"[Tokenizer] 로컬 인덱스 없음: {_LOCAL_INDEX_PATH}")
        except Exception as e:
            print(f"[Tokenizer] 로컬 인덱스 적재 실패: {e}")

        # 2) Supabase alias 적재 (이미 normalize 된 lookup 그대로 사용)
        supa_count = 0
        for alias, canonical in supabase_service.get_aliases().items():
            if alias and alias not in self._dict:
                self._dict[alias] = ("supabase", canonical)
                supa_count += 1

        # 3) Supabase SYNONYMS 흡수 — '고맙습니다' → '감사' 같은 사용자 발화 형태도 사전에 포함.
        #    [중요] canonical 이 로컬 KSL 인덱스에 있으면 local 우선 (정확도 ↑ — 로컬 데이터에는
        #    손가락 30개 본 + parent_chain 이 있고, Supabase 데이터는 상체 7개 본만 있어 자세가 어색해짐).
        syn_count = 0
        for alias, canonical_query in supabase_service.SYNONYMS.items():
            key = _norm(alias)
            if not key or key in self._dict:
                continue
            canon_norm = _norm(canonical_query)
            local_hit = self._dict.get(canon_norm)
            if local_hit and local_hit[0] == "local":
                # 로컬 우선: '고맙습니다' → ('local', '감사')
                self._dict[key] = ("local", local_hit[1])
                syn_count += 1
                continue
            resolved = supabase_service.resolve(canonical_query)
            if resolved:
                self._dict[key] = ("supabase", resolved)
                syn_count += 1
            else:
                # resolve 실패 시에도 canonical_query 자체를 등록
                # (motion_loader_v3.js 에서 Supabase API 재조회를 시도하므로 재생 가능)
                self._dict[key] = ("supabase", canonical_query)
                syn_count += 1

        print(
            f"[Tokenizer] 사전 빌드 완료: 총 {len(self._dict)}개 "
            f"(local={local_count}, supabase_alias={supa_count}, supabase_synonym={syn_count})"
        )

    def refresh(self) -> None:
        """Supabase 데이터 재적재 후 사전 재빌드 (관리자 호출용)."""
        supabase_service._refresh_word_cache()
        self._dict.clear()
        self._build()

    def _lookup_stem(self, stem: str) -> Optional[tuple[str, str, str]]:
        """어간을 사전에서 찾는다. 직접/+다/+하다/불규칙 매핑 순으로 시도."""
        s = _norm(stem)
        if not s:
            return None
        # 직접 매칭
        entry = self._dict.get(s)
        if entry:
            return (stem, entry[0], entry[1])
        # + "다" (예: "먹" → "먹다")
        entry = self._dict.get(_norm(stem + "다"))
        if entry:
            return (stem + "다", entry[0], entry[1])
        # + "하다" (예: "감사" → "감사하다")
        entry = self._dict.get(_norm(stem + "하다"))
        if entry:
            return (stem + "하다", entry[0], entry[1])
        # 불규칙 활용 매핑 (예: "반가" → "반갑다")
        irregular = self._IRREGULAR_STEMS.get(s)
        if irregular:
            entry = self._dict.get(_norm(irregular))
            if entry:
                return (irregular, entry[0], entry[1])
        return None

    def _strip_and_lookup(self, word: str) -> Optional[tuple[str, str, str]]:
        """활용어미·조사를 제거하고 어간이 사전에 있는지 확인.

        반환: (stem, source, canonical) 또는 None.
        """
        # 1) 활용어미 스트리핑
        for suffix in self._VERB_SUFFIXES:
            if not word.endswith(suffix) or len(word) <= len(suffix):
                continue
            stem = word[:-len(suffix)]
            hit = self._lookup_stem(stem)
            if hit:
                return hit

        # 2) 조사 스트리핑
        for particle in self._PARTICLES:
            if not word.endswith(particle) or len(word) <= len(particle):
                continue
            stem = word[:-len(particle)]
            hit = self._lookup_stem(stem)
            if hit:
                return hit

        return None

    def _longest_match(self, segment: str, start: int) -> Optional[tuple[int, str, str]]:
        """segment[start:] 위치에서 사전에 있는 가장 긴 단어를 찾는다.

        반환: (end_idx, source, canonical) 또는 None.
        """
        end = len(segment)
        # 가장 긴 후보부터 시도 → 첫 매칭이 곧 최장.
        for length in range(end - start, 0, -1):
            candidate = _norm(segment[start:start + length])
            if not candidate:
                continue
            entry = self._dict.get(candidate)
            if entry:
                source, canonical = entry
                return (start + length, source, canonical)
        return None

    def tokenize(self, text: str) -> list[dict]:
        """문장을 단어 배열로 분절.

        - 공백/구두점으로 1차 분리한 뒤 각 segment 안에서 longest-match greedy.
        - 매칭 실패한 substring 은 source="unknown" 으로 1글자씩 묶어 누락 표시 (디버그용).
        """
        if not text:
            return []

        text = _norm(text)
        # segment 단위로 분리 (구두점·공백 제거)
        segments: list[str] = []
        buf = []
        for ch in text:
            if ch in self._BOUNDARY_CHARS:
                if buf:
                    segments.append("".join(buf))
                    buf.clear()
            else:
                buf.append(ch)
        if buf:
            segments.append("".join(buf))

        tokens: list[dict] = []
        for seg in segments:
            # ── 세그먼트 전체를 먼저 어미/조사 스트리핑 시도 ──
            # "사랑합니다" 같이 세그먼트 통째가 활용형인 경우 우선 처리.
            seg_norm = _norm(seg)
            full_entry = self._dict.get(seg_norm)
            if full_entry:
                # 사전에 통째로 있으면 그대로 사용
                tokens.append({"word": seg, "source": full_entry[0], "canonical": full_entry[1]})
                continue
            strip_hit = self._strip_and_lookup(seg_norm)
            if strip_hit:
                stem, source, canonical = strip_hit
                tokens.append({"word": seg, "source": source, "canonical": canonical})
                continue

            i = 0
            unknown_acc = []
            while i < len(seg):
                hit = self._longest_match(seg, i)
                if hit is None:
                    # 현재 위치부터 남은 부분에 대해 어미/조사 스트리핑 시도
                    remainder = seg[i:]
                    strip_hit2 = self._strip_and_lookup(_norm(remainder))
                    if strip_hit2:
                        if unknown_acc:
                            tokens.append({"word": "".join(unknown_acc), "source": "unknown", "canonical": None})
                            unknown_acc = []
                        stem, source, canonical = strip_hit2
                        tokens.append({"word": remainder, "source": source, "canonical": canonical})
                        break
                    unknown_acc.append(seg[i])
                    i += 1
                    continue
                # 누적된 unknown 을 먼저 기록
                if unknown_acc:
                    tokens.append({
                        "word": "".join(unknown_acc),
                        "source": "unknown",
                        "canonical": None,
                    })
                    unknown_acc = []
                end, source, canonical = hit
                tokens.append({
                    "word": seg[i:end],
                    "source": source,
                    "canonical": canonical,
                })
                i = end
            if unknown_acc:
                tokens.append({
                    "word": "".join(unknown_acc),
                    "source": "unknown",
                    "canonical": None,
                })
        return tokens

    def stats(self) -> dict:
        local = sum(1 for v in self._dict.values() if v[0] == "local")
        supabase = sum(1 for v in self._dict.values() if v[0] == "supabase")
        return {"total": len(self._dict), "local": local, "supabase": supabase}


motion_tokenizer = MotionTokenizer()
