# NOTES

Assessed write-up (brief §8). Filled in as layers land; complete at Layer 9.

## 1. How to run it

_Layer 8 — clean clone through to a scored result._

## 2. Metric definitions

_Layer 3 / 9 — formula and edge-case behaviour for `overall_sentiment` and
`sentiment_trajectory`, including the `null` vs `0.0` cases and the trajectory
chart. Constants live in `pipeline.config.Config` and are echoed into every
`results` row's `params`._

## 3. Trade-offs

_Layer 9 — what was cut for the time box, and why._

## 4. Next steps

_Layer 9 — what another day buys (deferred layers 10a–10g)._

## 5. Scale

_Layer 9 — bottleneck backed by a measured throughput number from
`scripts/bench.py`; cost per million; what breaks first at 10×._

## 6. Deployment

_Layer 9 — AWS mapping (`jobs`→SQS, blobs→S3, results→DynamoDB, worker→Fargate),
autoscale signal, cost cap, dead-letter alerting, rough steady-state cost._

## Time spent

_Running total recorded here._
