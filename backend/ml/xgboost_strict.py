"""
Step 4 - XGBoost (STRICT regularization).

Goal: minimize the Train-vs-Test R2 gap, accepting a lower absolute R2.
This is the "generalization-first" run for the report — it is *not*
the production model, it is the baseline that proves how much of the
previous train-set R2 was variance and how much was real signal.

Splits: 70% train / 15% val / 15% test (random_state=42).
The val set is used ONLY for early stopping; the test set is the held-out
final evaluation.
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

# Strict-regularization hyperparameters as specified.
PARAMS = dict(
    n_estimators=1000,
    learning_rate=0.03,
    max_depth=3,
    min_child_weight=10,
    subsample=0.7,
    colsample_bytree=0.6,
    gamma=2.0,
    reg_alpha=1.0,
    reg_lambda=2.0,
    random_state=RANDOM_STATE,
    objective="reg:squarederror",
    tree_method="hist",
    n_jobs=-1,
    early_stopping_rounds=30,
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


def split_70_15_15(X: pd.DataFrame, y: pd.Series):
    # First peel off 15% test (test_size=0.15).
    X_temp, X_test, y_temp, y_test = train_test_split(
        X, y, test_size=0.15, random_state=RANDOM_STATE
    )
    # From the remaining 85%, peel off val so val is 15% of total
    # -> val fraction of temp = 0.15 / 0.85.
    val_frac = 0.15 / 0.85
    X_train, X_val, y_train, y_val = train_test_split(
        X_temp, y_temp, test_size=val_frac, random_state=RANDOM_STATE
    )
    return X_train, X_val, X_test, y_train, y_val, y_test


def main() -> int:
    df = load_data()

    X = df[NUMERIC + CATEGORICAL].copy()
    y = df[TARGET].astype(float).copy()

    X_train, X_val, X_test, y_train, y_val, y_test = split_70_15_15(X, y)
    n = len(X)
    print(
        f"[INFO] Split sizes -> "
        f"Train={X_train.shape} ({len(X_train)/n:.0%}), "
        f"Val={X_val.shape} ({len(X_val)/n:.0%}), "
        f"Test={X_test.shape} ({len(X_test)/n:.0%})"
    )

    pre = build_preprocessor()
    Xtr = pre.fit_transform(X_train)
    Xva = pre.transform(X_val)
    Xte = pre.transform(X_test)

    print("\n[INFO] Training STRICT XGBoost (early_stopping_rounds=30)...")
    model = XGBRegressor(**PARAMS)
    model.fit(Xtr, y_train, eval_set=[(Xva, y_val)], verbose=False)

    best_iter = getattr(model, "best_iteration", None)
    print(f"[INFO] best_iteration = {best_iter} (cap was {PARAMS['n_estimators']})")

    train_metrics = evaluate(y_train, model.predict(Xtr), "TRAIN")
    val_metrics = evaluate(y_val, model.predict(Xva), "VAL  ")
    test_metrics = evaluate(y_test, model.predict(Xte), "TEST ")

    gap = train_metrics["r2"] - test_metrics["r2"]

    print("\n=== STRICT XGBOOST - SUMMARY ===")
    summary = pd.DataFrame(
        [
            {"quantity": "best_iteration", "value": best_iter},
            {"quantity": "Train R2", "value": round(train_metrics["r2"], 4)},
            {"quantity": "Val R2", "value": round(val_metrics["r2"], 4)},
            {"quantity": "Test R2", "value": round(test_metrics["r2"], 4)},
            {"quantity": "Gap (Train - Test)", "value": round(gap, 4)},
            {"quantity": "Test MAE", "value": round(test_metrics["mae"], 4)},
            {"quantity": "Test RMSE", "value": round(test_metrics["rmse"], 4)},
        ]
    )
    print(summary.to_string(index=False))

    print("\n=== HYPERPARAMETERS ===")
    for k, v in PARAMS.items():
        print(f"  {k} = {v}")
    print(f"  best_iteration (kept) = {best_iter}")

    out = HERE / "xgb_strict_summary.csv"
    summary.to_csv(out, index=False)
    print(f"\n[OK] Summary -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
