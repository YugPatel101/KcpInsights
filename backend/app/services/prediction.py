"""Optional listing-outcome model and backtesting — separate from the research score.

Target:  Y = (P_listing − P_issue) / P_issue × 100   (listing-day open vs issue price)
Classes: negative (< lo), near-zero ([lo, hi]), positive (> hi) with lo/hi from config.

Rules enforced here
* Features use only information available at the prediction timestamp (issue close):
  statements with period_end before the issue opened, peer snapshots dated on/before
  the timestamp, and subscription snapshots taken on/before it. Later data is never
  substituted for missing values.
* Chronological train/validation/test split and expanding-window walk-forward
  evaluation; imputation and scaling are fitted on training rows only.
* Every model is compared with a naive historical baseline.
* With too little *real* data, no model is trained and nothing is presented as reliable.
* Synthetic datasets are allowed only to test the pipeline; their metrics are labelled
  ``pipeline_test_only`` and are never evidence of predictive performance.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, time
from typing import Any

import numpy as np
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import brier_score_loss, roc_auc_score
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import IPOIssue, ModelEvaluation, Prediction, PredictionModelVersion, utcnow
from app.services.financial_metrics import annual_periods, compute_quality_metrics
from app.services.ipo_service import (
    all_ipos,
    build_scoring_inputs,
    get_active_config,
    issue_price,
    subscription_at,
)
from app.services.scoring_engine import score_valuation

WARNING = (
    "IPO listing returns are highly uncertain. Historical backtests do not guarantee future "
    "outcomes, and this educational model is not investment advice."
)
REAL_STATUSES = {"verified", "imported"}


@dataclass
class Row:
    ipo_id: int
    listing_date: Any
    features: dict[str, float | None]
    target: float


def prediction_timestamp(ipo: IPOIssue) -> datetime | None:
    if ipo.close_date is None:
        return None
    return datetime.combine(ipo.close_date, time(23, 59))


def extract_features(db: Session, ipo: IPOIssue, feature_names: list[str], ts: datetime | None = None) -> dict[str, float | None]:
    ts = ts or prediction_timestamp(ipo) or utcnow()
    cfg = get_active_config(db)
    inputs = build_scoring_inputs(db, ipo, as_of=ts.date())
    # point-in-time filtering
    cutoff = ipo.open_date or ts.date()
    inputs.periods = [p for p in inputs.periods if p.period_end < cutoff]
    inputs.peers = [p for p in inputs.peers if p.as_of <= ts.date()]
    metrics = compute_quality_metrics(inputs.periods)
    val = score_valuation(inputs, cfg)
    subs = subscription_at(ipo, ts)
    price = issue_price(ipo)
    f: dict[str, float | None] = {
        "log_issue_size": math.log(ipo.issue_size_cr) if ipo.issue_size_cr else None,
        "is_sme": 1.0 if ipo.issue_type == "sme" else 0.0,
        "revenue_cagr": metrics["revenue_cagr"].value,
        "pat_margin": metrics["pat_margin"].value,
        "debt_to_equity": metrics["debt_to_equity"].value,
        "valuation_premium_pct": val.get("premium_to_median_pct"),
        "ofs_share_pct": (ipo.ofs_cr / ipo.issue_size_cr * 100) if ipo.ofs_cr is not None and ipo.issue_size_cr else None,
        "subscription_total_at_close": subs.get("total"),
        "subscription_qib_at_close": subs.get("qib"),
        "days_open_to_listing": float((ipo.listing_date - ipo.open_date).days) if ipo.listing_date and ipo.open_date else None,
        "_has_annual_period": 1.0 if annual_periods(inputs.periods) else 0.0,
        "_issue_price": price,
    }
    return {k: f.get(k) for k in feature_names}


def build_real_dataset(db: Session, feature_names: list[str]) -> list[Row]:
    rows = []
    for ipo in all_ipos(db):
        if ipo.data_mode == "demo" or ipo.data_status not in REAL_STATUSES:
            continue
        if ipo.listing_price is None or ipo.listing_date is None or (ipo.listing_data_status not in REAL_STATUSES):
            continue
        p = issue_price(ipo)
        if not p:
            continue
        rows.append(Row(ipo.id, ipo.listing_date, extract_features(db, ipo, feature_names), (ipo.listing_price - p) / p * 100))
    return sorted(rows, key=lambda r: r.listing_date)


def synthetic_dataset(feature_names: list[str], n: int = 160, seed: int = 7) -> list[Row]:
    """Clearly synthetic rows from a known generative process — for pipeline tests only."""
    rng = np.random.default_rng(seed)
    rows = []
    start = datetime(2015, 1, 1)
    for i in range(n):
        f: dict[str, float | None] = {
            "log_issue_size": float(rng.normal(6.5, 1.0)),
            "is_sme": float(rng.random() < 0.3),
            "revenue_cagr": float(rng.normal(15, 10)),
            "pat_margin": float(rng.normal(9, 6)),
            "debt_to_equity": float(abs(rng.normal(0.6, 0.5))),
            "valuation_premium_pct": float(rng.normal(10, 30)),
            "ofs_share_pct": float(rng.uniform(0, 100)),
            "subscription_total_at_close": float(abs(rng.lognormal(1.5, 1.0))),
            "subscription_qib_at_close": float(abs(rng.lognormal(1.8, 1.2))),
            "days_open_to_listing": float(rng.integers(5, 9)),
        }
        qib, prem = float(f["subscription_qib_at_close"] or 0.0), float(f["valuation_premium_pct"] or 0.0)
        y = 2.0 + 6.0 * math.log1p(qib) - 0.08 * prem + rng.normal(0, 12)
        if rng.random() < 0.1:
            f["subscription_qib_at_close"] = None
        rows.append(Row(-(i + 1), start.replace(year=2015 + i // 20, month=1 + (i % 12)), {k: f.get(k) for k in feature_names}, float(y)))
    return sorted(rows, key=lambda r: r.listing_date)


# ---------------------------------------------------------------------------
# Preprocessing fitted on training rows only
# ---------------------------------------------------------------------------
class Preprocessor:
    def __init__(self, features: list[str]) -> None:
        self.features = features

    def fit(self, X: np.ndarray) -> Preprocessor:
        med = np.nanmedian(X, axis=0)
        self.median = np.where(np.isnan(med), 0.0, med)
        Xi = np.where(np.isnan(X), self.median, X)
        self.mean = Xi.mean(axis=0)
        sd = Xi.std(axis=0)
        self.scale = np.where(sd < 1e-12, 1.0, sd)
        return self

    def transform(self, X: np.ndarray) -> np.ndarray:
        Xi = np.where(np.isnan(X), self.median, X)
        return (Xi - self.mean) / self.scale

    def to_params(self) -> dict[str, list[float]]:
        return {"median": self.median.tolist(), "mean": self.mean.tolist(), "scale": self.scale.tolist()}


def _num(v: float | None) -> float:
    return np.nan if v is None else float(v)


def _matrix(rows: list[Row], features: list[str]) -> np.ndarray:
    return np.array([[_num(r.features.get(f)) for f in features] for r in rows], dtype=float)


def expected_calibration_error(y: np.ndarray, p: np.ndarray, bins: int = 10) -> float:
    edges = np.linspace(0, 1, bins + 1)
    ece = 0.0
    for lo, hi in zip(edges[:-1], edges[1:], strict=True):
        m = (p >= lo) & (p < hi) if hi < 1 else (p >= lo) & (p <= hi)
        if m.any():
            ece += m.mean() * abs(y[m].mean() - p[m].mean())
    return float(ece)


def _clf_metrics(y: np.ndarray, p: np.ndarray) -> dict[str, float | None]:
    auc = float(roc_auc_score(y, p)) if len(set(y.tolist())) == 2 else None
    return {"roc_auc": auc, "brier": float(brier_score_loss(y, p)), "ece": expected_calibration_error(y, p),
            "accuracy": float(((p >= 0.5) == (y == 1)).mean())}


def _reg_metrics(y: np.ndarray, yhat: np.ndarray) -> dict[str, float]:
    e = yhat - y
    return {"mae": float(np.abs(e).mean()), "rmse": float(np.sqrt((e**2).mean()))}


def _bootstrap(y: np.ndarray, a: np.ndarray, b: np.ndarray, p: np.ndarray, n: int, seed: int = 11) -> dict[str, list[float] | None]:
    """95 % percentile intervals for MAE improvement over baseline and for ROC-AUC."""
    rng = np.random.default_rng(seed)
    yc = (y > 0).astype(int)
    diffs, aucs = [], []
    for _ in range(n):
        idx = rng.integers(0, len(y), len(y))
        diffs.append(np.abs(b[idx] - y[idx]).mean() - np.abs(a[idx] - y[idx]).mean())
        if len(set(yc[idx].tolist())) == 2:
            aucs.append(roc_auc_score(yc[idx], p[idx]))
    return {
        "mae_improvement_vs_baseline_95ci": [float(np.percentile(diffs, 2.5)), float(np.percentile(diffs, 97.5))],
        "roc_auc_95ci": [float(np.percentile(aucs, 2.5)), float(np.percentile(aucs, 97.5))] if aucs else None,
    }


def class_of(y: float, lo: float, hi: float) -> str:
    return "negative" if y < lo else ("positive" if y > hi else "near_zero")


def train_and_evaluate(rows: list[Row], cfg: dict[str, Any], dataset_kind: str) -> dict[str, Any]:
    lm = cfg["listing_model"]
    features: list[str] = lm["features"]
    lo, hi = lm["classes"]["negative_below_pct"], lm["classes"]["positive_above_pct"]
    n = len(rows)
    y_all = np.array([r.target for r in rows])
    yc_all = (y_all > hi).astype(int)
    pos, neg = int(yc_all.sum()), int(n - yc_all.sum())
    base = {"dataset_kind": dataset_kind, "n_samples": n, "features": features,
            "target": f"listing return % = (P_listing − P_issue) / P_issue × 100; positive class: > {hi}%",
            "warning": WARNING}
    if n < lm["min_samples"] or min(pos, neg) < lm["min_class_count"]:
        return {**base, "status": "insufficient_data",
                "reason": f"{n} usable listed IPOs ({pos} positive / {neg} other); need ≥ {lm['min_samples']} with ≥ {lm['min_class_count']} per class"}

    n_test = max(5, int(round(n * lm["test_fraction"])))
    n_val = max(5, int(round(n * lm["validation_fraction"])))
    n_train = n - n_test - n_val
    tr, va, te = rows[:n_train], rows[n_train : n_train + n_val], rows[n_train + n_val :]
    Xtr, Xva, Xte = (_matrix(r, features) for r in (tr, va, te))
    ytr, yva, yte = (np.array([r.target for r in s]) for s in (tr, va, te))

    # model selection on the validation block (fitted on train only)
    pre = Preprocessor(features).fit(Xtr)
    best_c, best_brier = 1.0, float("inf")
    for c in (0.05, 0.2, 1.0, 5.0):
        m = LogisticRegression(C=c, max_iter=2000).fit(pre.transform(Xtr), (ytr > hi).astype(int))
        b = brier_score_loss((yva > hi).astype(int), m.predict_proba(pre.transform(Xva))[:, 1])
        if b < best_brier:
            best_c, best_brier = c, b
    best_a, best_mae = 1.0, float("inf")
    for a in (0.1, 1.0, 10.0, 100.0):
        r = Ridge(alpha=a).fit(pre.transform(Xtr), ytr)
        mae = float(np.abs(r.predict(pre.transform(Xva)) - yva).mean())
        if mae < best_mae:
            best_a, best_mae = a, mae

    # refit on train+validation (still strictly before the test period)
    trva = tr + va
    Xtrva, ytrva = _matrix(trva, features), np.array([r.target for r in trva])
    pre2 = Preprocessor(features).fit(Xtrva)
    clf = LogisticRegression(C=best_c, max_iter=2000).fit(pre2.transform(Xtrva), (ytrva > hi).astype(int))
    reg = Ridge(alpha=best_a).fit(pre2.transform(Xtrva), ytrva)
    p_te = clf.predict_proba(pre2.transform(Xte))[:, 1]
    yhat_te = reg.predict(pre2.transform(Xte))
    base_rate = float((ytrva > hi).mean())
    base_mean = float(ytrva.mean())
    yc_te = (yte > hi).astype(int)
    test: dict[str, Any] = {
        "period": [str(te[0].listing_date), str(te[-1].listing_date)],
        "n": len(te),
        "logistic": _clf_metrics(yc_te, p_te),
        "baseline_classification": _clf_metrics(yc_te, np.full(len(te), base_rate)),
        "ridge": _reg_metrics(yte, yhat_te),
        "baseline_regression": _reg_metrics(yte, np.full(len(te), base_mean)),
        "bootstrap": _bootstrap(yte, yhat_te, np.full(len(te), base_mean), p_te, lm["bootstrap_iterations"]),
        "class_distribution": {k: sum(1 for v in yte if class_of(v, lo, hi) == k) for k in ("negative", "near_zero", "positive")},
    }

    # expanding-window walk-forward over the post-training period
    folds = []
    k = lm["walk_forward_folds"]
    start = n_train
    step = max(3, (n - start) // k)
    for f in range(k):
        a, b = start + f * step, min(n, start + (f + 1) * step)
        if a >= n or b - a < 3:
            break
        hist, fut = rows[:a], rows[a:b]
        Xh, yh = _matrix(hist, features), np.array([r.target for r in hist])
        if len(set((yh > hi).astype(int).tolist())) < 2:
            continue
        pp = Preprocessor(features).fit(Xh)
        c_m = LogisticRegression(C=best_c, max_iter=2000).fit(pp.transform(Xh), (yh > hi).astype(int))
        r_m = Ridge(alpha=best_a).fit(pp.transform(Xh), yh)
        Xf, yf = _matrix(fut, features), np.array([r.target for r in fut])
        folds.append({
            "train_until": str(hist[-1].listing_date), "test_period": [str(fut[0].listing_date), str(fut[-1].listing_date)], "n": len(fut),
            "logistic": _clf_metrics((yf > hi).astype(int), c_m.predict_proba(pp.transform(Xf))[:, 1]),
            "ridge": _reg_metrics(yf, r_m.predict(pp.transform(Xf))),
            "baseline_regression": _reg_metrics(yf, np.full(len(fut), yh.mean())),
        })

    beats = test["ridge"]["mae"] < test["baseline_regression"]["mae"]
    ci = test["bootstrap"]["mae_improvement_vs_baseline_95ci"]
    return {
        **base,
        "status": "pipeline_test_only" if dataset_kind == "synthetic" else "evaluated",
        "split": {"train": len(tr), "validation": len(va), "test": len(te), "method": "chronological"},
        "hyperparameters": {"logistic_C": best_c, "ridge_alpha": best_a},
        "test": test,
        "walk_forward": folds,
        "beats_baseline_point_estimate": beats,
        "beats_baseline_with_confidence": bool(ci and ci[0] > 0),
        "params": {
            "preprocessor": pre2.to_params(),
            "logistic": {"coef": clf.coef_[0].tolist(), "intercept": float(clf.intercept_[0])},
            "ridge": {"coef": reg.coef_.tolist(), "intercept": float(reg.intercept_)},
            "baseline": {"positive_rate": base_rate, "mean_return": base_mean},
        },
        "training_window": {"from": str(trva[0].listing_date), "to": str(trva[-1].listing_date)},
    }


def run_training(db: Session, *, synthetic: bool = False) -> dict[str, Any]:
    cfg = get_active_config(db)
    feats = cfg["listing_model"]["features"]
    rows = synthetic_dataset(feats) if synthetic else build_real_dataset(db, feats)
    res = train_and_evaluate(rows, cfg, "synthetic" if synthetic else "real")
    mv = PredictionModelVersion(
        name="listing_outcome_baselines", version=f"{cfg['version']}-{utcnow():%Y%m%d%H%M%S}",
        model_type="logistic_regression+ridge", dataset_kind=res["dataset_kind"], status=res["status"],
        features=feats, target_definition=res["target"], params=res.get("params", {}),
        training_window=res.get("training_window", {}), n_samples=res["n_samples"],
    )
    db.add(mv)
    db.flush()
    if "test" in res:
        db.add(ModelEvaluation(model_version_id=mv.id, split="test", metrics=res["test"], n_samples=res["test"]["n"]))
        db.add(ModelEvaluation(model_version_id=mv.id, split="walk_forward", metrics={"folds": res["walk_forward"]}, n_samples=sum(f["n"] for f in res["walk_forward"])))
    db.commit()
    res["model_version_id"] = mv.id
    return res


def _predict(params: dict[str, Any], feats: list[str], f: dict[str, float | None]) -> tuple[float, float]:
    x = np.array([_num(f.get(k)) for k in feats])
    pp = params["preprocessor"]
    x = np.where(np.isnan(x), np.array(pp["median"]), x)
    z = (x - np.array(pp["mean"])) / np.array(pp["scale"])
    logit = float(z @ np.array(params["logistic"]["coef"]) + params["logistic"]["intercept"])
    ret = float(z @ np.array(params["ridge"]["coef"]) + params["ridge"]["intercept"])
    return 1 / (1 + math.exp(-logit)), ret


def models_overview(db: Session) -> list[dict[str, Any]]:
    out = []
    for mv in db.execute(select(PredictionModelVersion).order_by(PredictionModelVersion.id.desc()).limit(20)).scalars():
        out.append({
            "id": mv.id, "name": mv.name, "version": mv.version, "model_type": mv.model_type, "dataset_kind": mv.dataset_kind,
            "status": mv.status, "n_samples": mv.n_samples, "features": mv.features, "target_definition": mv.target_definition,
            "training_window": mv.training_window, "created_at": mv.created_at.isoformat(),
            "evaluations": [{"split": e.split, "n": e.n_samples, "metrics": e.metrics} for e in mv.evaluations],
            "label": "SYNTHETIC PIPELINE TEST — not evidence of predictive performance" if mv.dataset_kind == "synthetic" else None,
        })
    return out


def real_data_count(db: Session) -> int:
    return sum(
        1 for i in all_ipos(db)
        if i.data_mode != "demo" and i.listing_price is not None and i.listing_data_status in REAL_STATUSES and i.data_status in REAL_STATUSES
    )


def prediction_for_ipo(db: Session, ipo: IPOIssue) -> dict[str, Any]:
    cfg = get_active_config(db)
    mv = db.execute(
        select(PredictionModelVersion)
        .where(PredictionModelVersion.dataset_kind == "real", PredictionModelVersion.status == "evaluated")
        .order_by(PredictionModelVersion.id.desc())
    ).scalars().first()
    if mv is None:
        n = real_data_count(db)
        return {"available": False, "warning": WARNING,
                "reason": f"No validated listing-outcome model. {n} real listed IPOs with verified/imported outcomes are stored; "
                          f"at least {cfg['listing_model']['min_samples']} are needed before a model is trained and evaluated."}
    test = next((e.metrics for e in mv.evaluations if e.split == "test"), None)
    if ipo.data_mode == "demo":
        return {"available": False, "warning": WARNING, "reason": "Predictions are not produced for synthetic demonstration IPOs."}
    ts = prediction_timestamp(ipo) or utcnow()
    f = extract_features(db, ipo, mv.features, ts)
    missing = [k for k, v in f.items() if v is None]
    p, r = _predict(mv.params, mv.features, f)
    out = {
        "available": True, "model_version": mv.version, "prediction_timestamp": ts.isoformat(),
        "probability_positive": round(p, 4), "expected_return_pct": round(r, 2),
        "positive_threshold_pct": cfg["listing_model"]["classes"]["positive_above_pct"],
        "features": f, "missing_features_imputed": missing, "test_metrics": test, "warning": WARNING,
    }
    db.add(Prediction(ipo_id=ipo.id, model_version_id=mv.id, prediction_timestamp=ts, feature_snapshot=f, output=out,
                      outcome=None if ipo.listing_price is None else {"listing_price": ipo.listing_price}))
    db.commit()
    return out
