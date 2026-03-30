# Design Document - Document Generation and Impact Analysis Completion Plan

## Background

- The repository now contains a connected flow from source change detection to document-related impact evaluation.
- Backend routes, workflow orchestration, frontend review panels, and persisted audit/change-log artifacts are already present.
- Recent outputs on 2026-03-26 show that the pipeline is being exercised, not just scaffolded.

## Problem

- The current implementation is strong on orchestration, visibility, and review logging, but weaker on proven end-to-end completion of regenerated deliverables.
- Recent impact logs still show `dry_run: true`, and several document targets are recorded as `review_required` or `flagged` rather than fully regenerated outputs.
- SITS and SUTS result metrics are still sparse in the latest sample run, so completion quality is not yet demonstrated at production confidence.
- Some repository-facing documentation, including the root `README.md`, still has presentation issues such as encoding corruption.

## Goals

- Establish a clear completion standard for the "document generation to impact analysis" scope.
- Separate what is already complete from what is only partially validated.
- Define the minimum remaining work required to call the feature set operationally complete.
- Provide a near-term execution plan that can be tracked and closed.

## Non-Goals

- Full redesign of the existing UI or workflow architecture.
- Replacing the current audit/change-log structure with a new reporting model.
- Broad refactoring unrelated to document generation, SITS/SUTS/UDS production, or impact analysis verification.

## Proposed Design

- Treat the current state as a late integration phase, not a greenfield implementation phase.
- Use the existing impact pipeline as the system of record:
  - `workflow/impact_orchestrator.py`
  - `workflow/impact_changes.py`
  - `backend/routers/local.py`
  - `frontend/src/components/local/LocalScmPanel.jsx`
- Define completion using three layers:
  - Flow completion: trigger, analyze, persist audit, persist change log, expose result in UI.
  - Artifact completion: UDS, SUTS, and SITS produce updated artifacts when auto-generation is enabled and applicable.
  - Trust completion: representative change scenarios produce stable, reviewable outputs with non-zero artifact deltas where expected.

### Current Assessment

- Overall implementation status: approximately 65-70% complete for operational finish, approximately 80% complete for architecture and feature skeleton.
- Strongly completed areas:
  - Local impact trigger path is connected to orchestration.
  - Audit and change-log persistence are implemented and producing files.
  - Frontend review surfaces for impact summary and review guidance are present.
  - SITS VectorCAST export packaging exists as a downstream artifact path.
- Partially completed areas:
  - Latest runs indicate review/flagging is working, but artifact regeneration proof is still limited.
  - SUTS/SITS quantitative outputs in the latest sample are still zero or near-zero in places where operational proof is expected.
  - Completion criteria are implied in code but not yet enforced by a formal acceptance checklist.
- Incomplete areas:
  - Real non-dry-run validation for representative scenarios is not yet established as a documented gate.
  - User-facing repository documentation is not yet cleaned up enough for handoff.

### Completion Criteria

- Phase 1: Execution proof
  - Run impact update with `dry_run = false` for representative SCM/project inputs.
  - Confirm audit and change-log outputs are generated for each run.
  - Confirm at least one scenario each for BODY-only change and SIGNATURE/HEADER change.
- Phase 2: Artifact proof
  - Confirm UDS output is updated or explicitly classified as review-only with a justified reason.
  - Confirm SUTS output includes meaningful changed function/case/sequence values when generation is expected.
  - Confirm SITS output includes generated cases or a clear review-required classification with traceable rationale.
- Phase 3: Acceptance proof
  - Create 3-5 representative end-to-end scenarios and preserve their results.
  - Review the outputs with a checklist covering traceability, changed-function mapping, and generated artifact availability.
  - Fix documentation issues so another engineer can run and verify the flow without tribal knowledge.

### Execution Plan

1. Verify non-dry-run behavior.
   - Execute the local impact trigger with `auto_generate = true`.
   - Capture resulting UDS/SUTS/SITS paths and compare them against previous linked docs.

2. Build an acceptance scenario set.
   - Scenario A: BODY-only implementation change.
   - Scenario B: HEADER or SIGNATURE change.
   - Scenario C: multi-file module change with indirect impact.
   - Scenario D: low-impact/no-regeneration case to verify review-only fallback.

3. Validate artifact quality.
   - Check whether change-log summaries show realistic non-zero deltas.
   - Open generated UDS/SUTS/SITS outputs and confirm they match the impacted functions.
   - Confirm review-required markdown is only produced when generation is intentionally skipped or unsafe.

4. Clean repository-facing documentation.
   - Repair `README.md` encoding and summarize the actual current workflow.
   - Add a concise operator guide for running impact update and locating outputs.

5. Freeze acceptance status.
   - Record pass/fail against the completion checklist.
   - Declare the scope complete only after the representative scenarios pass.

## Risks

- The system may appear complete because logs and UI render correctly while generated artifacts remain incomplete.
- Large change sets may over-flag functions, reducing trust in the outputs.
- Review-required fallback behavior may mask generation gaps if it is overused.
- Documentation drift can slow handoff even when the code path is mostly ready.

## Validation

- Confirm the latest impact runs continue to create files under `reports/impact_audit/` and `reports/impact_changes/`.
- Confirm non-dry-run runs generate updated linked-document outputs where expected.
- Confirm frontend impact panels display the same summary values stored in the change log.
- Confirm at least one successful SITS export package can be produced from a generated SITS artifact.
- Confirm `README.md` and project docs are readable and consistent after cleanup.

## Open Questions

- Under what exact conditions should UDS/SUTS/SITS remain `review_required` instead of forcing regeneration?
- Which scenario set should be considered the formal acceptance baseline for this repository?
- Whether SDS and STS should remain review-only in most cases, or gain broader auto-generation coverage later.
