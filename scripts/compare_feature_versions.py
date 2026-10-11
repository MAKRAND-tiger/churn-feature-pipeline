#!/usr/bin/env python3
"""
Version comparison for whichever feature(s) the confirmed feature_spec.md
designates as versioned. Loads every registered version of each versioned
feature via the feature store (it does NOT recompute from scratch), and writes
VERSION_COMPARISON.md with one section per versioned feature: how many
customers' values changed, the distribution shift between versions, and how
many customers would move across a churn-risk-ranking threshold.
"""

import sys
from pathlib import Path

# Make the repo root importable when this script is run directly.
_REPO_ROOT = str(Path(__file__).resolve().parents[1])
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import pandas as pd

from features.schema import FEATURE_BY_NAME, VERSIONED_FEATURES
from feature_store import store

OUT_PATH = "outputs/artifacts/VERSION_COMPARISON.md"


def _summarize(series: pd.Series) -> dict:
    q = series.quantile([0.0, 0.25, 0.5, 0.75, 1.0]).to_dict()
    return {
        "mean": float(series.mean()),
        "std": float(series.std(ddof=0)),
        "min": float(q[0.0]),
        "p25": float(q[0.25]),
        "p50": float(q[0.5]),
        "p75": float(q[0.75]),
        "max": float(q[1.0]),
    }


def _threshold_moves(v_old: pd.DataFrame, v_new: pd.DataFrame, feature_name: str, q: float = 0.75) -> dict:
    """For a churn feature where HIGHER values = higher churn risk, count how
    many customers cross the q-quantile threshold of the older version when the
    newer version is used. A positive net move above means the newer version
    flags more customers as high-risk.
    """
    merged = v_old[["customer_id", feature_name]].merge(
        v_new[["customer_id", feature_name]], on="customer_id", suffixes=("_old", "_new")
    )
    thr_old = merged[f"{feature_name}_old"].quantile(q)
    thr_new = merged[f"{feature_name}_new"].quantile(q)
    above_old = (merged[f"{feature_name}_old"] >= thr_old).sum()
    above_new = (merged[f"{feature_name}_new"] >= thr_new).sum()
    crossed_up = ((merged[f"{feature_name}_old"] < thr_old) & (merged[f"{feature_name}_new"] >= thr_new)).sum()
    crossed_down = ((merged[f"{feature_name}_old"] >= thr_old) & (merged[f"{feature_name}_new"] < thr_new)).sum()
    # Rank-order (Spearman) correlation between the two versions' values,
    # computed as Pearson correlation of the ranks (Spearman's identity) so we
    # do not depend on scipy.
    ro = merged[f"{feature_name}_old"].rank()
    rn = merged[f"{feature_name}_new"].rank()
    rho = float(ro.corr(rn)) if ro.std() and rn.std() else float("nan")
    return {
        "threshold": f"{q:.0%} quantile",
        "threshold_old": float(thr_old),
        "threshold_new": float(thr_new),
        "above_threshold_old": int(above_old),
        "above_threshold_new": int(above_new),
        "crossed_up": int(crossed_up),
        "crossed_down": int(crossed_down),
        "rank_correlation": float(rho) if rho == rho else float("nan"),
    }


def _format_table(rows: list[dict], headers: list[str]) -> str:
    out = "| " + " | ".join(headers) + " |\n"
    out += "|" + "|".join(["---"] * len(headers)) + "|\n"
    for r in rows:
        out += "| " + " | ".join(str(r[h]) for h in headers) + " |\n"
    return out


def _compare_feature(feature_name: str) -> str:
    spec = FEATURE_BY_NAME[feature_name]
    versions_meta = store.list_versions(feature_name)
    # Versions are stored as ints; sort ascending for chronological comparison.
    version_nums = sorted(int(v) for v in versions_meta["version"].tolist())

    lines = [f"## {feature_name}", ""]
    lines.append(f"**Parameter varied:** `{spec.version_param}`")
    lines.append(f"**Versions registered:** {version_nums}")
    lines.append("")

    # Per-version summary stats.
    lines.append("### Per-version distribution")
    rows = []
    dfs = {}
    for v in version_nums:
        df = store.get_version(feature_name, v)
        dfs[v] = df
        s = df[feature_name]
        stat = _summarize(s)
        meta = versions_meta[versions_meta["version"] == v].iloc[0]
        import json as _json
        params = _json.loads(meta["parameters"]) if meta["parameters"] else {}
        rows.append({
            "version": v,
            spec.version_param: params.get(spec.version_param, ""),
            "mean": f"{stat['mean']:.4g}",
            "std": f"{stat['std']:.4g}",
            "p50": f"{stat['p50']:.4g}",
            "p75": f"{stat['p75']:.4g}",
            "max": f"{stat['max']:.4g}",
            "n": len(s),
        })
    lines.append(_format_table(rows, ["version", spec.version_param, "mean", "std", "p50", "p75", "max", "n"]))
    lines.append("")

    # Pairwise changes between consecutive versions.
    lines.append("### Version-to-version change")
    for i in range(1, len(version_nums)):
        v_old, v_new = version_nums[i - 1], version_nums[i]
        old = dfs[v_old][["customer_id", feature_name]]
        new = dfs[v_new][["customer_id", feature_name]]
        merged = old.merge(new, on="customer_id", suffixes=("_old", "_new"))
        n_changed = int((merged[f"{feature_name}_old"] != merged[f"{feature_name}_new"]).sum())
        pct_changed = n_changed / len(merged) if len(merged) else 0.0
        moves = _threshold_moves(dfs[v_old], dfs[v_new], feature_name, q=0.75)
        lines.append(
            f"- **v{v_old} → v{v_new}:** {n_changed}/{len(merged)} "
            f"({pct_changed:.1%}) customers' values changed. "
            f"At the 75% churn-risk threshold, {moves['crossed_up']} customers moved above "
            f"and {moves['crossed_down']} moved below (rank-order correlation {moves['rank_correlation']:.3f})."
        )
    lines.append("")

    # Interpretation.
    lines.append("### Interpretation")
    if feature_name == "txn_count_recent":
        lines.append(
            "The versions differ because `window_days` changes the horizon over which "
            "frequency is counted. A shorter window (v2, 30d) concentrates on very recent "
            "engagement and so flags recent-disengagement churn risk more sharply; a longer "
            "window (v3, 180d) smooths toward long-term habit and moves fewer customers. "
            "A model consuming this feature WOULD notice the change where the rank-order "
            "correlation between versions is materially below 1.0: customers near the "
            "threshold are the ones who cross, so the chosen window is a real modeling "
            "decision, not a cosmetic rename."
        )
    elif feature_name == "avg_monthly_spend":
        lines.append(
            "The versions differ because `window_months` changes the averaging horizon. "
            "The 12-month window (v2) smooths seasonal spend swings that the 6-month window "
            "over-weights, so customers whose recent 6 months were atypical shift the most. "
            "A model consuming this feature would notice the change wherever the two windows "
            "disagree on rank order — the smoothing reduces noise but also dampens genuine "
            "recent-spend drops that signal churn, which is the modeling trade-off the "
            "version bump encodes."
        )
    else:
        lines.append(
            "The versions differ in a tunable parameter; a model consuming this feature would "
            "notice the change wherever the rank order between versions diverges."
        )
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    import json  # noqa: F401  (used inside _compare_feature)
    sections = ["# VERSION_COMPARISON.md", ""]
    sections.append(
        "Per-feature version comparison for the features `feature_spec.md` designates as "
        f"versioned: {VERSIONED_FEATURES}. All values are loaded from the feature store "
        "(not recomputed). For each feature: how many customers' values changed between "
        "consecutive versions, the distribution shift, and how many customers would move "
        "across a churn-risk-ranking threshold (the 75% quantile; higher = higher churn risk) "
        "if the newer version were used instead of the older one."
    )
    sections.append("")
    for name in VERSIONED_FEATURES:
        sections.append(_compare_feature(name))
        sections.append("")

    out = Path(OUT_PATH)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(sections), encoding="utf-8")
    print(f"Wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
