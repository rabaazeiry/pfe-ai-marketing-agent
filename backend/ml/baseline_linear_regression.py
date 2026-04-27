"""
Step 4 - AI Reverse Engineering Insights
Baseline Linear Regression on the 9-column interpretable dataset.

Goal: explanatory, not predictive. We want to know WHICH factors move
engagementRate and IN WHAT DIRECTION.

Notes on methodology:
- Numeric features are StandardScaled so that coefficient magnitudes are
  directly comparable (1 std-dev change in feature -> X change in target).
  Without scaling, `followers` (~10^7) would dominate `hour` (0..23) on
  raw magnitude alone, which is misleading.
- Categorical features are One-Hot encoded with `drop='first'` so each
  coefficient reads as "effect vs the dropped reference category".
- hour and dayofweek are kept as raw numeric per spec; a true cyclical
  encoding (sin/cos) would be a sensible v2 but is out of scope here.
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
    print(f"\n[{label}] MAE={mae:.4f}  RMSE={rmse:.4f}  R2={r2:.4f}")
    return {"mae": mae, "rmse": rmse, "r2": r2}


def coefficient_table(pipe: Pipeline) -> pd.DataFrame:
    pre: ColumnTransformer = pipe.named_steps["preprocess"]
    model: LinearRegression = pipe.named_steps["model"]
    feature_names = pre.get_feature_names_out()
    # strip the "num__" / "cat__" prefixes added by ColumnTransformer
    clean_names = [n.split("__", 1)[1] if "__" in n else n for n in feature_names]
    df = pd.DataFrame({"feature": clean_names, "coefficient": model.coef_})
    df["abs_coef"] = df["coefficient"].abs()
    df = df.sort_values("abs_coef", ascending=False).reset_index(drop=True)
    return df


def interpret(coefs: pd.DataFrame) -> list[str]:
    """Translate the strongest coefficients into plain-English marketing insights."""
    insights: list[str] = []
    cmap = dict(zip(coefs["feature"], coefs["coefficient"]))

    def describe_numeric(name: str, label_hi: str, label_lo: str) -> str | None:
        if name not in cmap:
            return None
        c = cmap[name]
        direction = "increases" if c > 0 else "decreases"
        return (
            f"- {name}: 1 std-dev higher {label_hi} {direction} engagementRate by "
            f"{c:+.4f} (units = engagementRate). {label_lo}"
        )

    # numerical drivers
    for name, hi, lo in [
        ("hour", "posting hour", "Try later/earlier slots accordingly."),
        ("dayofweek", "dayofweek (Mon=0..Sun=6)", "Later in the week vs earlier."),
        ("nbrhashtags", "hashtag count", "More hashtags vs fewer."),
        ("captionlength", "caption length", "Longer captions vs shorter."),
        ("followers", "follower count", "Bigger accounts dilute engagement rate."),
    ]:
        line = describe_numeric(name, hi, lo)
        if line:
            insights.append(line)

    # content_type vs reference (carousel is alphabetically first -> dropped reference)
    for k, v in cmap.items():
        if k.startswith("content_type_"):
            ctype = k.replace("content_type_", "")
            verb = "boosts" if v > 0 else "reduces"
            insights.append(
                f"- content_type={ctype} {verb} engagementRate by {v:+.4f} vs "
                f"the reference (carousel)."
            )

    # industry effects (reference = beauty after drop_first, alphabetical)
    industry_lines = []
    for k, v in cmap.items():
        if k.startswith("industry_"):
            ind = k.replace("industry_", "")
            industry_lines.append((ind, v))
    industry_lines.sort(key=lambda x: abs(x[1]), reverse=True)
    for ind, v in industry_lines[:3]:
        verb = "above" if v > 0 else "below"
        insights.append(
            f"- industry={ind} sits {verb} the reference industry (beauty) by "
            f"{v:+.4f} on engagementRate."
        )

    # top brand effects (top 3 by magnitude)
    brand_lines = []
    for k, v in cmap.items():
        if k.startswith("brand_"):
            brand_lines.append((k.replace("brand_", ""), v))
    brand_lines.sort(key=lambda x: abs(x[1]), reverse=True)
    for b, v in brand_lines[:3]:
        verb = "outperforms" if v > 0 else "underperforms"
        insights.append(
            f"- brand={b} {verb} the reference brand by {v:+.4f} on engagementRate."
        )

    return insights


def sample_prediction(pipe: Pipeline, df: pd.DataFrame) -> None:
    """Predict for: industry=beauty, content_type=reel, hour=20, nbrhashtags=10.
    Other features are filled from realistic dataset statistics so the prediction
    is not dominated by arbitrary defaults."""
    industry = "beauty"
    sub = df[df["industry"] == industry]
    sample = pd.DataFrame(
        [
            {
                "industry": industry,
                "brand": sub["brand"].mode().iat[0],
                "content_type": "reel",
                "hour": 20,
                "dayofweek": int(sub["dayofweek"].median()),
                "nbrhashtags": 10,
                "captionlength": int(sub["captionlength"].median()),
                "followers": int(sub["followers"].median()),
            }
        ]
    )
    pred = float(pipe.predict(sample)[0])
    print("\n=== SAMPLE PREDICTION ===")
    print(sample.to_string(index=False))
    print(f"-> predicted engagementRate = {pred:.4f}")

    # what-if: same row but content_type swapped, to show the lever in isolation
    print("\nWhat-if (same row, varying content_type):")
    for ct in ["reel", "photo", "carousel"]:
        row = sample.copy()
        row["content_type"] = ct
        p = float(pipe.predict(row)[0])
        print(f"  content_type={ct:<8} -> {p:.4f}")


def main() -> int:
    df = load_data()

    X = df[NUMERIC + CATEGORICAL].copy()
    y = df[TARGET].astype(float).copy()

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=RANDOM_STATE
    )
    print(f"[INFO] Train={X_train.shape}, Test={X_test.shape}")

    pipe = build_pipeline()
    pipe.fit(X_train, y_train)

    evaluate(y_train, pipe.predict(X_train), "TRAIN")
    metrics = evaluate(y_test, pipe.predict(X_test), "TEST ")

    coefs = coefficient_table(pipe)
    intercept = pipe.named_steps["model"].intercept_

    print(f"\nIntercept: {intercept:.6f}")
    print("\n=== TOP 20 COEFFICIENTS BY |value| ===")
    print(coefs.head(20).to_string(index=False))

    print("\n=== TOP NUMERIC + CONTENT_TYPE FACTORS ===")
    focus = coefs[
        coefs["feature"].isin(NUMERIC)
        | coefs["feature"].str.startswith("content_type_")
    ]
    print(focus.to_string(index=False))

    print("\n=== MARKETING INSIGHTS (plain English) ===")
    for line in interpret(coefs):
        print(line)

    sample_prediction(pipe, df)

    out_path = HERE / "linreg_coefficients.csv"
    coefs.to_csv(out_path, index=False)
    print(f"\n[OK] Coefficients exported to {out_path}")
    print(f"[OK] Final test metrics -> MAE={metrics['mae']:.4f}, "
          f"RMSE={metrics['rmse']:.4f}, R2={metrics['r2']:.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
