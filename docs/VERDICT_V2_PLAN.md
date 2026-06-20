# VERDICT V2 Implementation Note

## Architecture Diff

Old flow:

`Market data -> candidates -> backtest -> walk-forward -> selection -> AgentVerdict`

V2 flow:

`Market data -> news/sentiment -> feature layer -> decision matrix -> risk gates -> verdict -> DCA agent narrative -> optional future executor`

New code paths:

- `verdict/sentiment/`: deterministic `SentimentSnapshot` creation, scoring, normalization, and cache helpers.
- `verdict/core/matrix.py`: weighted, explainable `TRADE | WAIT | DCA | NO_TRADE` matrix.
- `verdict/safety/`: mandatory kill-switch state and trigger evaluation.
- `verdict/agent/dca.py`: personality-driven narrative and DCA cadence, with no execution authority.
- `verdict/demo.py`: clean judge JSON summary mode.

## Audit Fixes Included

- Selection leakage reduced: risk-adjusted eligibility now uses OOS walk-forward Sharpe and drawdown instead of full-history Sharpe/drawdown.
- README claims narrowed: current code is Track-2 research/narrative only; execution is explicitly future work.
- Coverage support added through `.coveragerc` and `pytest-cov` in `requirements.txt`.

## Remaining Risks

- Sentiment uses a simple deterministic lexicon and offline fallback; it is intentionally bounded and not a trading edge by itself.
- No live executor exists. DCA output is an allocation narrative only.
- News API connectors are not enabled by default; this avoids network dependence but limits live context.
- Strategy search space remains narrow: three hand-authored archetypes per asset.

## Implementation Order

1. Keep selection and backtest honest.
2. Add bounded sentiment snapshots.
3. Add explainable decision matrix.
4. Add kill-switch gates before any agent narrative.
5. Add DCA narrative with personality thresholds only.
6. Add future executor only after paper executor, allowlist, wallet policy, and rejection handling exist.
