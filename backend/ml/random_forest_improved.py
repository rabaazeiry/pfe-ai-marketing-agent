"""
Step 4 - Improved Random Forest (regularized) on the 9-column dataset.

Problem with the v1 forest:
    Train R2 = 0.5897 vs Test R2 = 0.1380  -> heavy overfitting.

Why this dataset overfits a RandomForest:
- Small sample (4,130 rows) with a *high-cardinality* categorical (`brand`,
  ~50 distinct values one-hot encoded into ~50 dummies). A tree can carve
  out very thin brand-specific leaves that memorize training noise.
- `captionlength` is continuous with a long tail, so trees split on it
  many times and each split is essentially fitting individual posts.
- Default `max_features=1.0` for regression -> every split sees every
  feature -> trees become highly correlated and can collectively chase
  the same brand-level noise.
- `max_depth=10` with `min_samples_leaf=1` lets leaves contain a single
  post, which is a memorization regime.

Regularization plan:
- Cap depth (max_depth in {4, 6, 8}).
- Force leaves to hold real evidence (min_samples_leaf in {5, 10},
  min_samples_split in {10, 20}).
- Decorrelate trees by limiting feature subsampling
  (max_features in {'sqrt', 0.5}).
- More trees (n_estimators=300) to stabilize the average without
  re-introducing variance.

We pick the best combo by 5-fold CV on the training set (R2), then
retrain once and evaluate ONCE on the held-out test set.
"""

from pathlib import Path
import sys
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import GridSearchCV, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

HERE = Path(__file__).resolve().parent
SRC = HERE / "ml_ready_dataset_final_9cols.csv"

# v1 RF metrics, repeated here for the comparison print only.
PREVIOUS = {
    "train_r2": 0.5897,
    "test_r2": 0.1380,
    "mae": 0.3307,
    "rmse": 0.8284,
    "params": {
        "n_estimators": 100,
        "max_depth": 10,
        "min_samples_split": 2,
        "min_samples_leaf": 1,
        "max_features": 1.0,
    },
}

NUMERIC = ["hour", "dayofweek", "nbrhashtags", "captionlength", "followers"]
CATEGORICAL = ["industry", "brand", "content_type"]
TARGET = "engagementRate"
RANDOM_STATE = 42


def load_data() -> pd.DataFrame:
    if not SRC.exists():
        raise FileNotFoundError(f"Missing dataset: {SRC}")
    df = pd.read_csv(SRC)
    print(f"[INFO] Loaded {SRC.name}: shape={df.shape}")
    return df


def build_pipeline() -> Pipeline:
    pre = ColumnTransformer(
        transformers=[
            ("num", "passthrough", NUMERIC),
            (
                "cat",
                OneHotEncoder(handle_unknown="ignore", sparse_output=False),
                CATEGORICAL,
            ),
        ]
    )
    base = RandomForestRegressor(random_state=RANDOM_STATE, n_jobs=-1)
    return Pipeline([("preprocess", pre), ("model", base)])


def tune(pipe: Pipeline, X_train, y_train) -> GridSearchCV:
    grid = {
        "model__n_estimators": [300],
        "model__max_depth": [4, 6, 8],
        "model__min_samples_split": [10, 20],
        "model__min_samples_leaf": [5, 10],
        "model__max_features": ["sqrt", 0.5],
    }
    search = GridSearchCV(
        pipe,
        param_grid=grid,
        cv=5,
        scoring="r2",
        n_jobs=-1,
        verbose=0,
        refit=True,
    )
    search.fit(X_train, y_train)
    return search


def evaluate(y_true, y_pred, label: str) -> dict:
    mae = mean_absolute_error(y_true, y_pred)
    rmse = np.sqrt(mean_squared_error(y_true, y_pred))
    r2 = r2_score(y_true, y_pred)
    print(f"[{label}] MAE={mae:.4f}  RMSE={rmse:.4f}  R2={r2:.4f}")
    return {"mae": mae, "rmse": rmse, "r2": r2}


def importance_table(pipe: Pipeline) -> pd.DataFrame:
    pre: ColumnTransformer = pipe.named_steps["preprocess"]
    model: RandomForestRegressor = pipe.named_steps["model"]
    feature_names = pre.get_feature_names_out()
    clean = [n.split("__", 1)[1] if "__" in n else n for n in feature_names]
    imp = model.feature_importances_
    df = pd.DataFrame({"feature": clean, "importance": imp})
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


def comparison_table(train_r2, test_r2, mae, rmse) -> pd.DataFrame:
    rows = [
        ("Train R2", PREVIOUS["train_r2"], train_r2),
        ("Test R2", PREVIOUS["test_r2"], test_r2),
        ("MAE", PREVIOUS["mae"], mae),
        ("RMSE", PREVIOUS["rmse"], rmse),
    ]
    df = pd.DataFrame(rows, columns=["metric", "old_rf", "improved_rf"])
    df["delta"] = (df["improved_rf"] - df["old_rf"]).round(4)
    df["old_rf"] = df["old_rf"].round(4)
    df["improved_rf"] = df["improved_rf"].round(4)
    return df


def main() -> int:
    df = load_data()

    X = df[NUMERIC + CATEGORICAL].copy()
    y = df[TARGET].astype(float).copy()

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=RANDOM_STATE
    )
    print(f"[INFO] Train={X_train.shape}, Test={X_test.shape}")

    print("\n[INFO] Running 5-fold GridSearchCV over the regularization grid...")
    search = tune(build_pipeline(), X_train, y_train)
    best_pipe: Pipeline = search.best_estimator_
    best_params = {
        k.replace("model__", ""): v for k, v in search.best_params_.items()
    }
    print(f"[INFO] Best CV R2: {search.best_score_:.4f}")
    print(f"[INFO] Best params: {best_params}\n")

    train_metrics = evaluate(y_train, best_pipe.predict(X_train), "TRAIN")
    test_metrics = evaluate(y_test, best_pipe.predict(X_test), "TEST ")

    cmp_df = comparison_table(
        train_r2=train_metrics["r2"],
        test_r2=test_metrics["r2"],
        mae=test_metrics["mae"],
        rmse=test_metrics["rmse"],
    )
    print("\n=== OLD RF vs IMPROVED RF ===")
    print(cmp_df.to_string(index=False))

    overfit_old = PREVIOUS["train_r2"] - PREVIOUS["test_r2"]
    overfit_new = train_metrics["r2"] - test_metrics["r2"]
    print(
        f"\nOverfitting gap (TrainR2 - TestR2): "
        f"{overfit_old:.4f} -> {overfit_new:.4f}"
    )

    imp = importance_table(best_pipe)
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

    out_imp = HERE / "rf_improved_feature_importance.csv"
    out_agg = HERE / "rf_improved_feature_importance_aggregated.csv"
    out_cmp = HERE / "rf_comparison.csv"
    imp.to_csv(out_imp, index=False)
    agg.to_csv(out_agg, index=False)
    cmp_df.to_csv(out_cmp, index=False)
    print(f"\n[OK] Per-column importance -> {out_imp}")
    print(f"[OK] Aggregated importance -> {out_agg}")
    print(f"[OK] Comparison            -> {out_cmp}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
