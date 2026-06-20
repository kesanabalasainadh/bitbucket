# VERDICT V3: Sentiment Validation Summary

## 1. Did sentiment help?
Average Improvement in Sharpe Ratio: **0.0746**
Permutation p-value: **0.1780**
Bootstrap 95% Confidence Interval: **[-0.0680, 0.2105]**

**Conclusion:** NO EVIDENCE

## 2. Where did it help?
Sentiment showed modest utility in volatile regimes when filtered for directional agreement. Specifically, taking longs only when sentiment > 0.05 prevented entries into 'falling knives' on days with heavily negative newsflow.

## 3. Failed Cases
On highly liquid assets during range-bound regimes, news volume often lags price action, turning the sentiment score into a late, lagging indicator that increased whip-saws.

## 4. Final Deliverables
If NO EVIDENCE is found, we keep the architecture but reduce the weight of sentiment to a maximum cap of 5% in the matrix. If SIGNIFICANT, we cap at 15%. This guarantees we never claim fake alpha.
