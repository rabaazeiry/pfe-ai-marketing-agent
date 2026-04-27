"""
Step 4 - AI Reverse Engineering Insights
Random Forest Regressor on the 9-column dataset (no scaling, OHE for cats).

Standalone training run: we are NOT comparing with other models in this
script. The goal is to extract feature_importances_ and translate them
into marketing insights.

We aggregate one-hot importances back to the parent feature
(brand_*, industry_*, content_type_*) so the "role of content_type"
question has a single, clean number instead of being scattered across
several dummy columns.
"""

from pathlib import Path
import sys
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

HERE = Path(__file__).resolve().parent
SRC = HERE / "ml_ready_dataset_final_9cols.csv"

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
    model = RandomForestRegressor(
        n_estimators=100,
        max_depth=10,
        random_state=RANDOM_STATE,
        n_jobs=-1,
    )
    return Pipeline([("preprocess", pre), ("model", model)])


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
    """Collapse one-hot dummies back to their parent feature."""

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


def insight_for(agg: pd.DataFrame, name: str) -> float:
    row = agg.loc[agg["feature"] == name]
    return float(row["importance_pct"].iat[0]) if not row.empty else float("nan")


def main() -> int:
    df = load_data()

    X = df[NUMERIC + CATEGORICAL].copy()
    y = df[TARGET].astype(float).copy()

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=RANDOM_STATE
    )
    print(f"[INFO] Train={X_train.shape}, Test={X_test.shape}\n")

    pipe = build_pipeline()
    pipe.fit(X_train, y_train)

    evaluate(y_train, pipe.predict(X_train), "TRAIN")
    metrics = evaluate(y_test, pipe.predict(X_test), "TEST ")

    imp = importance_table(pipe)
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

    print("\n=== MARKETING INSIGHTS ===")
    most_imp = agg.iloc[0]
    print(
        f"- Most important factor: '{most_imp['feature']}' "
        f"({most_imp['importance_pct']:.2f}% of total importance)."
    )
    print(f"- Role of content_type : {insight_for(agg, 'content_type'):.2f}%")
    print(f"- Role of hour         : {insight_for(agg, 'hour'):.2f}%")
    print(f"- Role of nbrhashtags  : {insight_for(agg, 'nbrhashtags'):.2f}%")
    print(f"- Role of followers    : {insight_for(agg, 'followers'):.2f}%")
    print(f"- Role of captionlength: {insight_for(agg, 'captionlength'):.2f}%")
    print(f"- Role of dayofweek    : {insight_for(agg, 'dayofweek'):.2f}%")
    print(f"- Role of brand        : {insight_for(agg, 'brand'):.2f}%")
    print(f"- Role of industry     : {insight_for(agg, 'industry'):.2f}%")

    out_imp = HERE / "rf_feature_importance.csv"
    out_agg = HERE / "rf_feature_importance_aggregated.csv"
    imp.to_csv(out_imp, index=False)
    agg.to_csv(out_agg, index=False)
    print(f"\n[OK] Per-column importance -> {out_imp}")
    print(f"[OK] Aggregated importance -> {out_agg}")
    print(
        f"[OK] Final test metrics    -> MAE={metrics['mae']:.4f}, "
        f"RMSE={metrics['rmse']:.4f}, R2={metrics['r2']:.4f}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
