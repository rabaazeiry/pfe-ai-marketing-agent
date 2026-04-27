"""
Step 4 (v2) - Improved Linear Regression with Feature Engineering.

Goal: keep the model interpretable while lifting performance vs the baseline
in `baseline_linear_regression.py`. We engineer features that match the
*shape* of the underlying signals:

- followers spans ~10^3 to ~10^7 -> log1p compresses the scale.
- hashtags often have diminishing/decreasing returns -> add quadratic term.
- hour is cyclical (00:00 ~ 23:00) -> sin/cos encoding instead of raw int.
- a "reel posted in the evening" lever is a known marketing heuristic
  -> add an explicit interaction so the linear model can capture it.

We keep StandardScaler + OneHotEncoder + LinearRegression so coefficients
remain directly comparable and readable for the report.
"""

from pathlib import Path
import sys
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

HERE = Path(__file__).resolve().parent
SRC = HERE / "ml_ready_dataset_final_9cols.csv"

# Baseline metrics from `baseline_linear_regression.py` (test set).
BASELINE = {"r2": 0.10, "mae": 0.37, "rmse": 0.84}

NUMERIC = [
    "log_followers",
    "nbrhashtags",
    "hashtags_squared",
    "captionlength",
    "hour_sin",
    "hour_cos",
    "reel_evening",
]
CATEGORICAL = ["industry", "brand", "content_type"]
TARGET = "engagementRate"
RANDOM_STATE = 42


def load_data() -> pd.DataFrame:
    if not SRC.exists():
        raise FileNotFoundError(f"Missing dataset: {SRC}")
    df = pd.read_csv(SRC)
    print(f"[INFO] Loaded {SRC.name}: shape={df.shape}")
    return df


def engineer_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add the engineered columns required by the improved model."""
    out = df.copy()

    out["log_followers"] = np.log1p(out["followers"].astype(float))
    out["hashtags_squared"] = out["nbrhashtags"].astype(float) ** 2

    radians = 2.0 * np.pi * out["hour"].astype(float) / 24.0
    out["hour_sin"] = np.sin(radians)
    out["hour_cos"] = np.cos(radians)

    is_reel = out["content_type"].astype(str).str.lower().eq("reel")
    is_evening = out["hour"].astype(int) >= 18
    out["reel_evening"] = (is_reel & is_evening).astype(int)

    return out


def build_pipeline() -> Pipeline:
    pre = ColumnTransformer(
        transformers=[
            ("num", StandardScaler(), NUMERIC),
            (
                "cat",
                OneHotEncoder(drop="first", handle_unknown="ignore", sparse_output=False),
                CATEGORICAL,
            ),
        ]
    )
    return Pipeline([("preprocess", pre), ("model", LinearRegression())])


def evaluate(y_true, y_pred, label: str) -> dict:
    mae = mean_absolute_error(y_true, y_pred)
    rmse = np.sqrt(mean_squared_error(y_true, y_pred))
    r2 = r2_score(y_true, y_pred)
    print(f"[{label}] MAE={mae:.4f}  RMSE={rmse:.4f}  R2={r2:.4f}")
    return {"mae": mae, "rmse": rmse, "r2": r2}


def coefficient_table(pipe: Pipeline) -> pd.DataFrame:
    pre: ColumnTransformer = pipe.named_steps["preprocess"]
    model: LinearRegression = pipe.named_steps["model"]
    feature_names = pre.get_feature_names_out()
    clean_names = [n.split("__", 1)[1] if "__" in n else n for n in feature_names]
    df = pd.DataFrame({"feature": clean_names, "coefficient": model.coef_})
    df["abs_coef"] = df["coefficient"].abs()
    return df.sort_values("abs_coef", ascending=False).reset_index(drop=True)


def comparison_table(metrics: dict) -> pd.DataFrame:
    rows = []
    for k in ["r2", "mae", "rmse"]:
        old = BASELINE[k]
        new = metrics[k]
        if k == "r2":
            delta = new - old
            note = "higher is better"
        else:
            delta = new - old
            note = "lower is better"
        rows.append(
            {
                "metric": k.upper(),
                "baseline": round(old, 4),
                "improved": round(new, 4),
                "delta": round(delta, 4),
                "direction": note,
            }
        )
    return pd.DataFrame(rows)


def split_top_factors(coefs: pd.DataFrame, k: int = 8) -> tuple[pd.DataFrame, pd.DataFrame]:
    pos = (
        coefs[coefs["coefficient"] > 0]
        .sort_values("coefficient", ascending=False)
        .head(k)
        .reset_index(drop=True)
    )
    neg = (
        coefs[coefs["coefficient"] < 0]
        .sort_values("coefficient", ascending=True)
        .head(k)
        .reset_index(drop=True)
    )
    return pos, neg


def main() -> int:
    df = load_data()
    df = engineer_features(df)

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

    cmp_df = comparison_table(metrics)
    print("\n=== BASELINE vs IMPROVED ===")
    print(cmp_df.to_string(index=False))

    coefs = coefficient_table(pipe)
    intercept = pipe.named_steps["model"].intercept_
    print(f"\nIntercept: {intercept:.6f}")

    print("\n=== TOP 15 COEFFICIENTS BY |value| ===")
    print(coefs.head(15).to_string(index=False))

    pos, neg = split_top_factors(coefs, k=8)
    print("\n=== TOP POSITIVE FACTORS (lift engagementRate) ===")
    print(pos[["feature", "coefficient"]].to_string(index=False))
    print("\n=== TOP NEGATIVE FACTORS (drag engagementRate) ===")
    print(neg[["feature", "coefficient"]].to_string(index=False))

    print("\n=== ENGINEERED-FEATURE COEFFICIENTS (focus) ===")
    focus_cols = [
        "log_followers",
        "nbrhashtags",
        "hashtags_squared",
        "hour_sin",
        "hour_cos",
        "reel_evening",
        "captionlength",
    ]
    focus = coefs[coefs["feature"].isin(focus_cols)].copy()
    print(focus[["feature", "coefficient"]].to_string(index=False))

    out_coefs = HERE / "linreg_coefficients_improved.csv"
    out_cmp = HERE / "linreg_comparison.csv"
    coefs.to_csv(out_coefs, index=False)
    cmp_df.to_csv(out_cmp, index=False)
    print(f"\n[OK] Coefficients -> {out_coefs}")
    print(f"[OK] Comparison   -> {out_cmp}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
