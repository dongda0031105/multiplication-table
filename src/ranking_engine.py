"""
RankingEngine — cross-sectional weighted-percentile scoring from strategy JSON.

For each factor:
  1. Clip at [clip_lo, clip_hi] percentile (default 2nd / 98th)
  2. Rank within the cross-section → percentile 0-100
  3. If direction == "asc" (lower-is-better, e.g. P/E), invert score
  4. Multiply by weight → add to composite score

Tickers with NaN on any ranked factor are excluded (handle_missing=exclude_symbol).
Final columns added: "score" (0-100 composite), "rank" (1 = best).
"""
from typing import Dict, List

import numpy as np
import pandas as pd


class RankingEngine:

    def score_and_rank(
        self, snapshot_df: pd.DataFrame, ranking_config: Dict
    ) -> pd.DataFrame:
        """
        Return snapshot_df with 'score' and 'rank' columns added.
        Rows with NaN on factor fields are dropped.
        """
        factors: List[Dict] = ranking_config.get("factors", [])
        norm = ranking_config.get("normalization", {})
        clip_lo, clip_hi = norm.get("clip_percentiles", [2, 98])
        handle_missing = norm.get("handle_missing", "exclude_symbol")

        result = snapshot_df.copy()

        # Drop tickers missing any ranked factor
        factor_fields = [f["field"] for f in factors]
        if handle_missing == "exclude_symbol" and factor_fields:
            result = result.dropna(subset=factor_fields)

        if result.empty or not factors:
            result["score"] = 0.0
            result["rank"] = range(1, len(result) + 1)
            return result

        result["score"] = 0.0

        for factor in factors:
            field = factor["field"]
            weight = factor["weight"]
            direction = factor.get("direction", "desc")

            values = result[field].copy()

            # Clip outliers
            lo = values.quantile(clip_lo / 100)
            hi = values.quantile(clip_hi / 100)
            values = values.clip(lower=lo, upper=hi)

            # Cross-sectional percentile rank (0–100)
            pct_rank = values.rank(pct=True, method="average") * 100

            # Invert for ascending factors (lower value = better score)
            if direction == "asc":
                pct_rank = 100.0 - pct_rank

            result["score"] += weight * pct_rank

        # Rank by composite score (1 = highest score = best)
        result["rank"] = (
            result["score"].rank(ascending=False, method="min").astype(int)
        )

        return result.sort_values("rank").reset_index(drop=False)

    # ── selection helpers ─────────────────────────────────────────────────────

    def get_watchlist(
        self, ranked_df: pd.DataFrame, ranking_config: Dict
    ) -> pd.DataFrame:
        n = ranking_config.get("selection", {}).get("watchlist_top_n", 20)
        return ranked_df[ranked_df["rank"] <= n]

    def get_buy_candidates(
        self, ranked_df: pd.DataFrame, ranking_config: Dict
    ) -> pd.DataFrame:
        selection = ranking_config.get("selection", {})
        n = selection.get("buy_top_n", 8)
        min_score = selection.get("min_score", 0)
        return ranked_df[(ranked_df["rank"] <= n) & (ranked_df["score"] >= min_score)]
