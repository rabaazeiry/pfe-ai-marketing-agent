"""
Step 4 - AI Reverse Engineering Insights
XGBoost regressor with strong regularization + early stopping.

Splits:
- Held-out test set: 20% of total (random_state=42).
- Validation set: 20% of the remaining train -> 16% of total.
  Used ONLY for early stopping; never used to compute reported metrics.
- Final training set: 64% of total. This is what the booster actually fits.

We preprocess (One-Hot Encode) outside the model so XGBoost sees a stable
numpy matrix and `eval_set` works correctly with early stopping. No scaling.

Why these hyperparameters: shallow trees (max_depth=4) + min_child_weight=5
prevent the brand-leaf memorization we saw in the v1 RandomForest;
subsample/colsample inject row+column noise so trees decorrelate;
gamma + reg_alpha + reg_lambda penalize complex splits and large leaf
values; learning_rate=0.05 with up to 500 rounds + early_stopping_rounds=50
finds the best number of rounds without manual tuning.
"""

from pathlib import Path
import sys
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import OneHotEncoder
from xgboost import XGBRegressor

HERE = Path(__file__).resolve().parent
SRC = HERE / "ml_ready_dataset_final_9cols.csv"

NUMERIC = ["hour", "dayofweek", "nbrhashtags", "captionlength", "followers"]
CATEGORICAL = ["industry", "brand", "content_type"]
TARGET = "engagementRate"
RANDOM_STATE = 42

PARAMS = dict(
    n_estimators=500,
    learning_rate=0.05,
    max_depth=4,
    min_child_weight=5,
    subsample=0.8,
    colsample_bytree=0.8,
    gamma=1.0,
    reg_alpha=0.5,
    reg_lambda=1.0,
    random_state=RANDOM_STATE,
    objective="reg:squarederror",
    tree_method="hist",
    n_jobs=-1,
    early_stopping_rounds=50,
)


def load_data() -> pd.DataFrame:
    if not SRC.exists():
        raise FileNotFoundError(f"Missing dataset: {SRC}")
    df = pd.read_csv(SRC)
    print(f"[INFO] Loaded {SRC.name}: shape={df.shape}")
    return df


def build_preprocessor() -> ColumnTransformer:
    return ColumnTransformer(
        transformers=[
            ("num", "passthrough", NUMERIC),
            (
                "cat",
                OneHotEncoder(handle_unknown="ignore", sparse_output=False),
                CATEGORICAL,
            ),
        ]
    )


def evaluate(y_true, y_pred, label: str) -> dict:
    mae = mean_absolute_error(y_true, y_pred)
    rmse = np.sqrt(mean_squared_error(y_true, y_pred))
    r2 = r2_score(y_true, y_pred)
    print(f"[{label}] MAE={mae:.4f}  RMSE={rmse:.4f}  R2={r2:.4f}")
    return {"mae": mae, "rmse": rmse, "r2": r2}


def importance_table(model: XGBRegressor, feature_names: list[str]) -> pd.DataFrame:
    imp = model.feature_importances_  # default: 'gain'-normalized
    df = pd.DataFrame({"feature": feature_names, "importance": imp})
    df["importance_pct"] = (df["importance"] / df["importance"].sum()) * 100
    return df.sort_values("importance", ascending=False).reset_index(drop=True)


def aggregate_importance(imp_df: pd.DataFrame) -> pd.DataFrame:
    def parent(name: str) -> str:
        for cat in CATEGORICAL:
            if name.startswith(f"{cat}_"):
                return cat
        return name

    agg = (
        imp_df.assign(parent=imp_df["feature"].map(parent))
        .groupby("parent", as_index=False)["importance"]
        .sum()
        .rename(columns={"parent": "feature"})
    )
    agg["importance_pct"] = (agg["importance"] / agg["importance"].sum()) * 100
    return agg.sort_values("importance", ascending=False).reset_index(drop=True)


def main() -> int:
    df = load_data()

    X = df[NUMERIC + CATEGORICAL].copy()
    y = df[TARGET].astype(float).copy()

    # 1) Carve out the held-out TEST set first — never touched until the end.
    X_trainval, X_test, y_trainval, y_test = train_test_split(
        X, y, test_size=0.2, random_state=RANDOM_STATE
    )
    # 2) From the remaining 80%, peel off a VAL set for early stopping.
    X_train, X_val, y_train, y_val = train_test_split(
        X_trainval, y_trainval, test_size=0.2, random_state=RANDOM_STATE
    )
    print(
        f"[INFO] Train={X_train.shape}, Val={X_val.shape}, Test={X_test.shape}"
    )

    pre = build_preprocessor()
    Xtr = pre.fit_transform(X_train)
    Xva = pre.transform(X_val)
    Xte = pre.transform(X_test)
    feature_names = [
        n.split("__", 1)[1] if "__" in n else n
        for n in pre.get_feature_names_out()
    ]

    print("\n[INFO] Training XGBoost with early stopping (rounds=50)...")
    model = XGBRegressor(**PARAMS)
    model.fit(Xtr, y_train, eval_set=[(Xva, y_val)], verbose=False)

    best_iter = getattr(model, "best_iteration", None)
    print(f"[INFO] best_iteration = {best_iter} (cap was {PARAMS['n_estimators']})")

    train_metrics = evaluate(y_train, model.predict(Xtr), "TRAIN")
    val_metrics = evaluate(y_val, model.predict(Xva), "VAL  ")
    test_metrics = evaluate(y_test, model.predict(Xte), "TEST ")

    overfit_gap = train_metrics["r2"] - test_metrics["r2"]
    print(f"\n=== OVERFITTING ANALYSIS ===")
    print(f"Train R2 = {train_metrics['r2']:.4f}")
    print(f"Test  R2 = {test_metrics['r2']:.4f}")
    print(f"Gap (Train - Test) = {overfit_gap:.4f}")

    imp = importance_table(model, feature_names)
    print("\n=== TOP 10 FEATURES (raw, per one-hot column) ===")
    top10 = imp.head(10)[["feature", "importance", "importance_pct"]].copy()
    top10["importance"] = top10["importance"].round(4)
    top10["importance_pct"] = top10["importance_pct"].round(2)
    print(top10.to_string(index=False))

    agg = aggregate_importance(imp)
    print("\n=== AGGREGATED IMPORTANCE (parent feature, %) ===")
    agg_show = agg[["feature", "importance_pct"]].copy()
    agg_show["importance_pct"] = agg_show["importance_pct"].round(2)
    print(agg_show.to_string(index=False))

    print("\n=== FINAL HYPERPARAMETERS ===")
    for k, v in PARAMS.items():
        print(f"  {k} = {v}")
    print(f"  best_iteration (kept) = {best_iter}")

    out_imp = HERE / "xgb_feature_importance.csv"
    out_agg = HERE / "xgb_feature_importance_aggregated.csv"
    imp.to_csv(out_imp, index=False)
    agg.to_csv(out_agg, index=False)
    print(f"\n[OK] Per-column importance -> {out_imp}")
    print(f"[OK] Aggregated importance -> {out_agg}")
    print(
        f"[OK] Final TEST metrics    -> MAE={test_metrics['mae']:.4f}, "
        f"RMSE={test_metrics['rmse']:.4f}, R2={test_metrics['r2']:.4f}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
