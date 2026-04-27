"""
map_word_ids.py ─ AI Hub morpheme → WORD_ID ↔ 한국어 매핑 + JSON rename

입력:
  morpheme 루트 (예: C:/Users/ComHolic/Desktop/data/[라벨]01_real_word_morpheme/morpheme/01)
  ksl_motions 디렉토리 (frontend/data/ksl_motions)

처리:
  1. morpheme JSON 전체 스캔 → WORD_ID → 한국어 단어 매핑 생성
  2. 같은 WORD_ID 의 여러 angle·performer JSON 은 같은 단어라야 함 (sanity check)
  3. frontend/data/ksl_motions/WORD####.json 을 {한국어}.json 으로 COPY (원본 보존)
  4. mapping.json 파일로 전체 매핑 저장
  5. index.json 갱신
"""

import json
import re
import sys
import shutil
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

MORPHEME_ROOT = Path(r"C:/Users/ComHolic/Desktop/data/01_real_word_morpheme/morpheme/01")
MOTIONS_DIR = ROOT / "frontend" / "data" / "ksl_motions"

# Windows 파일명에 쓸 수 없는 문자
INVALID_FS_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def build_mapping() -> dict:
    """morpheme JSON 전체에서 WORD_ID → 한국어 단어 추출."""
    if not MORPHEME_ROOT.exists():
        raise FileNotFoundError(f"morpheme 루트 없음: {MORPHEME_ROOT}")

    # WORD_ID → set of Korean words (sanity check: 같은 WORD_ID 는 같은 단어여야)
    raw_mapping: dict[str, set] = defaultdict(set)

    files = list(MORPHEME_ROOT.rglob("*_morpheme.json"))
    print(f"[Map] morpheme JSON {len(files)}개 스캔 중...")

    for fp in files:
        # 파일명에서 WORD ID 추출: NIA_SL_WORD0002_REAL01_R_morpheme.json → WORD0002
        m = re.search(r"(WORD\d{4})", fp.name)
        if not m:
            continue
        word_id = m.group(1)

        try:
            with open(fp, encoding="utf-8") as f:
                data = json.load(f)
            for seg in data.get("data", []):
                for attr in seg.get("attributes", []):
                    name = (attr.get("name") or "").strip()
                    if name:
                        raw_mapping[word_id].add(name)
        except Exception as e:
            print(f"  경고 {fp.name}: {e}")

    # WORD_ID 당 하나의 대표 단어 선택 (가장 흔한 것)
    mapping: dict[str, str] = {}
    inconsistent = []
    for wid, words in raw_mapping.items():
        if len(words) == 1:
            mapping[wid] = next(iter(words))
        else:
            # 여러 개면 첫 번째 사용 + 경고
            word = sorted(words)[0]
            mapping[wid] = word
            inconsistent.append((wid, sorted(words)))

    print(f"[Map] 완료: {len(mapping)}개 WORD_ID 매핑 (불일치 {len(inconsistent)}건)")
    if inconsistent[:3]:
        for wid, words in inconsistent[:3]:
            print(f"  주의 {wid}: {words}")
    return mapping


def sanitize_filename(name: str) -> str:
    """Windows 파일명에 쓸 수 없는 문자 제거."""
    cleaned = INVALID_FS_CHARS.sub("_", name).strip()
    return cleaned or "UNKNOWN"


def apply_mapping(mapping: dict) -> None:
    """각 WORD####.json 을 {한국어}.json 으로 복사. 원본 유지."""
    if not MOTIONS_DIR.exists():
        raise FileNotFoundError(f"motions 디렉토리 없음: {MOTIONS_DIR}")

    word_files = sorted(MOTIONS_DIR.glob("WORD*.json"))
    print(f"[Map] {len(word_files)}개 WORD JSON 을 한국어로 복사...")

    created = 0
    skipped_no_map = 0
    collisions = []

    # 이름 충돌 체크 (여러 WORD_ID 가 같은 단어일 수 있음)
    korean_counter: dict[str, list] = defaultdict(list)
    for wf in word_files:
        wid = wf.stem
        korean = mapping.get(wid)
        if korean:
            korean_counter[korean].append(wid)

    for wf in word_files:
        wid = wf.stem
        korean = mapping.get(wid)
        if not korean:
            skipped_no_map += 1
            continue

        safe_name = sanitize_filename(korean)
        # 동일 한국어 단어가 여러 WORD_ID 에 있으면 suffix 부여
        duplicates = korean_counter[korean]
        if len(duplicates) > 1:
            idx = duplicates.index(wid) + 1
            safe_name = f"{safe_name}_{idx}" if idx > 1 else safe_name
            if idx > 1:
                collisions.append((korean, duplicates))

        out_path = MOTIONS_DIR / f"{safe_name}.json"

        # 원본 JSON 에 id 필드도 한국어로 업데이트
        with open(wf, encoding="utf-8") as f:
            motion = json.load(f)
        motion["id"] = korean
        motion["word_id"] = wid  # 역추적용
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(motion, f, ensure_ascii=False, indent=2)
        created += 1

    print(f"[Map] 한국어 JSON 생성: {created}개 / 매핑 없음 스킵: {skipped_no_map}개")
    if collisions:
        print(f"[Map] 중복 처리: {len(set(tuple(c[1]) for c in collisions))}종류 (suffix _2, _3 부여)")

    # mapping.json 저장 (양방향 조회용)
    mapping_path = MOTIONS_DIR / "_mapping.json"
    with open(mapping_path, "w", encoding="utf-8") as f:
        json.dump({
            "word_to_korean": mapping,
            "korean_to_word": {v: k for k, v in mapping.items()},
            "total": len(mapping),
        }, f, ensure_ascii=False, indent=2)
    print(f"[Map] 매핑 저장: {mapping_path}")


def rebuild_index() -> None:
    """index.json 을 현재 디렉토리 전체 파일 스캔으로 재생성."""
    files = sorted([p for p in MOTIONS_DIR.glob("*.json")
                    if p.name not in ("index.json", "_mapping.json")])
    actions = [p.stem for p in files]
    idx = {"total": len(actions), "actions": actions}
    with open(MOTIONS_DIR / "index.json", "w", encoding="utf-8") as f:
        json.dump(idx, f, ensure_ascii=False, indent=2)
    print(f"[Map] index.json 갱신: {len(actions)}개 항목")


if __name__ == "__main__":
    mapping = build_mapping()
    apply_mapping(mapping)
    rebuild_index()
    print("\n[DONE] 한국어 이름으로 재생 가능:")
    # 샘플 10개
    samples = list(mapping.items())[:10]
    for wid, kr in samples:
        print(f"  {wid} → {kr}")
