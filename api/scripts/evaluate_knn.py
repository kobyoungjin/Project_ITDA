"""
evaluate_knn.py ─ KSL KNN 모델 정확도 정직 평가

■ 데이터 누수(leakage)란?
  같은 출처(같은 영상·같은 수집 세션·같은 프레임의 증강본)에서 나온 샘플이
  train 과 test 양쪽에 동시에 들어가면, 모델이 "거의 같은 것"을 미리 본 셈이라
  정확도가 실제보다 부풀려진다. 특히 KNN(weights='distance')은 가까운 형제
  샘플 하나만 train 에 있어도 그 표를 그대로 가져온다.

■ 누수를 없애는 유일하게 확실한 방법
  각 샘플이 "어느 출처에서 왔는지"(source)를 알고, 같은 출처는 train/test 중
  한쪽에만 넣는 것(GroupKFold). 그래서 이 스크립트는 source 열을 기준으로 한다.

    - CSV 에 source 열이 있으면 → GroupKFold = 누수 없는 정직한 수치
    - source 열이 없으면        → StratifiedKFold 만 가능. 증강·연속프레임
                                   형제 샘플이 섞일 수 있어 결과가 낙관적이다.

실행:
  python api/scripts/evaluate_knn.py --dataset main
  python api/scripts/evaluate_knn.py --dataset dialogue
  python api/scripts/evaluate_knn.py --csv <경로> --neighbors 7 --folds 5
"""

import argparse
from pathlib import Path

import pandas as pd
from sklearn.neighbors import KNeighborsClassifier
from sklearn.model_selection import StratifiedKFold, GroupKFold, cross_val_predict
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix

ROOT = Path(__file__).resolve().parents[2]
DATASETS = {
    "main": ROOT / "api" / "data" / "ksl_training" / "ksl_dataset.csv",
    "dialogue": ROOT / "api" / "data" / "ksl_training" / "ksl_dataset_dialogue.csv",
}


def load_dataset(csv_path: Path, source_col: str):
    """CSV → (X, y, groups). groups 는 source 열이 있을 때만 채워진다."""
    df = pd.read_csv(csv_path, encoding="utf-8")
    if "label" not in df.columns:
        raise ValueError(f"'label' 열이 없습니다: {csv_path}")

    # 학습 파이프라인(train_knn_model)과 동일하게 완전 중복 행 제거
    before = len(df)
    df = df.drop_duplicates().reset_index(drop=True)
    if len(df) < before:
        print(f"[정보] 완전 중복 행 {before - len(df)}개 제거 ({before} → {len(df)})")

    groups = None
    if source_col in df.columns:
        groups = df[source_col].astype(str).values
        feature_cols = [c for c in df.columns if c not in ("label", source_col)]
    else:
        feature_cols = [c for c in df.columns if c != "label"]

    X = df[feature_cols].to_numpy(dtype=float)
    y = df["label"].astype(str).to_numpy()
    return X, y, groups


def print_distribution(y):
    vc = pd.Series(y).value_counts()
    print(f"  단어 수: {vc.size},  총 샘플: {len(y)}")
    print(f"  단어별 샘플 수 — 최소 {vc.min()}, 최대 {vc.max()}, 중앙값 {int(vc.median())}")
    low = vc[vc < 10]
    if not low.empty:
        print(f"  ⚠️  샘플 10개 미만 단어: {list(low.index)}")


def run_cv(title, model, X, y, cv, groups=None):
    """교차검증으로 out-of-fold 예측을 만들고 정확도를 출력한다."""
    y_pred = cross_val_predict(model, X, y, cv=cv, groups=groups)
    acc = accuracy_score(y, y_pred)
    print(f"  ▶ {title}:  정확도 {acc * 100:.1f}%")
    return y_pred, acc


def top_confusions(y, y_pred, top=8):
    labels = sorted(set(y))
    cm = confusion_matrix(y, y_pred, labels=labels)
    pairs = [
        (cm[i, j], labels[i], labels[j])
        for i in range(len(labels))
        for j in range(len(labels))
        if i != j and cm[i, j] > 0
    ]
    pairs.sort(reverse=True)
    return pairs[:top]


def main():
    parser = argparse.ArgumentParser(description="KSL KNN 모델 누수 없는 정확도 평가")
    parser.add_argument("--dataset", choices=list(DATASETS), default="main",
                        help="평가할 내장 데이터셋 (기본: main)")
    parser.add_argument("--csv", type=Path, default=None,
                        help="직접 지정할 CSV 경로 (지정 시 --dataset 무시)")
    parser.add_argument("--neighbors", type=int, default=7,
                        help="KNN n_neighbors (배포 모델과 동일값: 7)")
    parser.add_argument("--folds", type=int, default=5, help="교차검증 fold 수 (기본: 5)")
    parser.add_argument("--source-col", default="source",
                        help="출처(누수 방지 그룹) 열 이름 (기본: source)")
    args = parser.parse_args()

    csv_path = args.csv if args.csv else DATASETS[args.dataset]
    if not csv_path.exists():
        print(f"[오류] CSV 를 찾을 수 없습니다: {csv_path}")
        return

    print("=" * 64)
    print(f"[평가 대상] {csv_path}")
    X, y, groups = load_dataset(csv_path, args.source_col)
    print_distribution(y)

    n_classes = len(set(y))
    if n_classes < 2:
        print("[오류] 단어가 1종류뿐이라 평가할 수 없습니다.")
        return

    # 배포 모델(train_knn_model)과 동일한 KNN 설정으로 평가해야 의미가 있다
    model = KNeighborsClassifier(
        n_neighbors=args.neighbors, weights="distance", metric="minkowski", p=2
    )

    # ── [1] 표준 교차검증 (낙관적일 수 있음) ─────────────────────
    print("\n" + "-" * 64)
    print("[1] 표준 교차검증 (StratifiedKFold)")
    print("    같은 출처의 증강·연속프레임 형제 샘플이 train/test 에 섞일 수")
    print("    있어, 결과가 실제 사용 환경보다 낙관적일 수 있습니다.")
    min_class = int(pd.Series(y).value_counts().min())
    skf_splits = max(2, min(args.folds, min_class))
    skf = StratifiedKFold(n_splits=skf_splits, shuffle=True, random_state=42)
    y_pred_naive, _ = run_cv("표준 CV (낙관적)", model, X, y, skf)

    honest_pred, honest_name, honest_done = y_pred_naive, "표준 CV", False

    # ── [2] 출처 단위 교차검증 (누수 없음) ───────────────────────
    print("\n" + "-" * 64)
    if groups is not None:
        n_groups = len(set(groups))
        print("[2] 출처 단위 교차검증 (GroupKFold) — 누수 없음")
        print(f"    '{args.source_col}' 열 감지: 출처 {n_groups}개.")
        print("    같은 출처 샘플은 train/test 중 한쪽에만 들어갑니다.")
        gkf_splits = min(args.folds, n_groups)
        if gkf_splits < 2:
            print("    ⚠️  출처가 2개 미만이라 GroupKFold 를 할 수 없습니다.")
        else:
            gkf = GroupKFold(n_splits=gkf_splits)
            honest_pred, _ = run_cv("정직한 CV (누수 없음)", model, X, y, gkf, groups)
            honest_name, honest_done = "정직한 CV (GroupKFold)", True
            # 출처가 너무 적은 단어는 일반화 평가 자체가 불가능
            src_per_class = (
                pd.DataFrame({"label": y, "src": groups})
                .groupby("label")["src"].nunique()
            )
            scarce = src_per_class[src_per_class < 2]
            if not scarce.empty:
                print(f"    ⚠️  출처가 1개뿐인 단어 {len(scarce)}개: {list(scarce.index)}")
                print("       → 이 단어들은 '새 출처 일반화'를 평가할 수 없습니다.")
    else:
        print(f"[2] 출처 단위 평가 — 건너뜀")
        print(f"    CSV 에 '{args.source_col}' 열이 없어 누수 없는 평가가 불가능합니다.")
        print("    각 샘플이 어느 영상/수집 세션에서 왔는지 기록되어 있지 않습니다.")
        print("    → 데이터 수집 시 'source' 열(영상 파일명·세션 ID 등)을 함께")
        print("      저장하면 이 정직한 평가가 활성화됩니다.")

    # ── 상세 리포트 (가용한 최선의 기준으로) ─────────────────────
    print("\n" + "=" * 64)
    print(f"[단어별 성능]  기준: {honest_name}")
    print("=" * 64)
    print(classification_report(y, honest_pred, zero_division=0))

    print("[가장 자주 혼동되는 단어쌍]")
    conf = top_confusions(y, honest_pred)
    if conf:
        for cnt, a, b in conf:
            print(f"  '{a}'  →  '{b}' 로 오인식  {cnt}회")
    else:
        print("  (혼동 없음)")

    # ── 결론 ─────────────────────────────────────────────────────
    print("\n" + "=" * 64)
    print("[결론]")
    if honest_done:
        print("  GroupKFold 수치가 실사용에 가장 가까운 정직한 정확도입니다.")
    else:
        print("  위 표준 CV 수치는 낙관적 추정치이며 실제 정확도는 더 낮을 수")
        print("  있습니다. 누수 없는 정직한 수치를 얻으려면 데이터 수집 단계에서")
        print("  각 샘플의 출처(source)를 기록해야 합니다.")
    print("=" * 64)


if __name__ == "__main__":
    main()
