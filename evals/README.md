# Evals

## Purpose

This directory contains the evaluation fixtures and definitions used to measure chatbot behavior during the modernization effort.

The goals are:

- detect regressions while introducing LangGraph and MCP
- compare model behavior on representative DevOps tasks
- measure grounding and citation quality
- measure latency and degraded-mode behavior


## Initial Eval Categories

The first fixed evaluation set should cover:

1. build failure summary
2. coverage explanation
3. findings summary
4. Jenkins status question
5. code guidance question
6. latest-doc or external-fact question
7. degraded-mode fallback behavior


## Suggested Layout

- `cases/`
  - individual case definitions
- `fixtures/`
  - stable report or JSON inputs
- `results/`
  - captured benchmark outputs
- `scripts/`
  - local evaluation runners


## Case Format

Each case should eventually define:

```json
{
  "id": "build_failure_local_01",
  "question": "현재 빌드 실패 원인을 요약해줘",
  "mode": "local",
  "report_dir": "reports/sample_session",
  "expected_topics": ["build", "failure", "cause"],
  "must_cite": true,
  "must_not_hallucinate": true
}
```


## Baseline Metrics

The first comparison run should capture:

- `total_ms`
- `context_ms`
- `retrieval_ms`
- `tool_ms`
- `llm_ms`
- `stream_first_event_ms`
- `fallback_used`
- `citation_count`


## Rule

No major runtime change should be merged without running the fixed evaluation set against at least one baseline.
