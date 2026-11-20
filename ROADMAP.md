# Research roadmap / 研究路線

## Available on the team branch

The plugin can compare bounded PubMed concept combinations and open the evidence behind a difference. A tenant-owned research workspace links decisions, evidence and outstanding reading across sessions. Release v0.9.0 is the reference for published Chronicle behavior. [Capability inventory](docs/README.md#capability-inventory) · [Release history](CHANGELOG.md)

## Questions for the next evaluation

| Question | Evidence needed |
| --- | --- |
| Do search previews recover eligible studies at an acceptable screening cost? | Freeze eligible reference studies before tuning terms. Compare recovered studies, screening burden and provider calls on multiple review topics. |
| Can Chronicle identify an important historical fork? | Have independent readers mark forks, earlier alternatives and milestones. Evaluate recovered historical links separately from newly published studies. |
| Can another agent resume a review? | Measure time to recover the chosen search, excluded alternatives, source access and next unfinished reading across two plugin hosts. |
| Can one organizational deployment serve its intended users? | Exercise concurrent tenants, provider outages, restart and backup restoration under a measured workload. Record latency and isolation failures. |

These are evaluation questions. The [methods protocol](docs/publication/evaluation-protocol.md) and [renovation review](docs/reports/renovation_review_2026-11-20.md) record the starting evidence. Earlier phases, proposed extensions, candidate retirements and tool names are preserved in the [roadmap through v0.9.0](docs/archive/research/roadmap-through-v090.md).
