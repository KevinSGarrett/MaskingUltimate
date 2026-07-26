# Pursuing-goal message — finish the self-hosted autonomous LLM system

Add the following as a binding priority inside the current pursuing goal:

> Finish the MaskFactory self-hosted autonomous LLM continuous-operations
> system before treating isolated bounded steward missions as the intended
> autonomy milestone. The purpose is to materially reduce Codex desktop usage,
> eliminate routine micro handoffs, and make the self-hosted system continuously
> perform eligible engineering, test generation, diagnosis, mask adjustment,
> deterministic QA, visual-review orchestration, evidence compaction, recovery,
> and campaign preparation.
>
> Use `Plan/27_SELF_HOSTED_AUTONOMOUS_LLM_CONTINUOUS_OPERATIONS_SPEC.md`,
> `Plan/Items/23_ITEMS_P6_SELF_HOSTED_AUTONOMOUS_LLM_OPERATIONS.md`, and
> `Plan/Instructions/16_SELF_HOSTED_AUTONOMOUS_LLM_CONTINUOUS_OPERATIONS.md`
> as the execution authority. Read the live tracker first and keep this track
> ahead of lower-value bookkeeping or one-off advisory work whenever its next
> dependency is unblocked.
>
> Build a persistent CPU-safe supervisor and durable mission/campaign ledger.
> It must select work from the tracker/DAG, persist intent, avoid completed,
> duplicate, active, superseded, or ambiguous work, batch compatible work into
> campaigns, and continue CPU-safe work whenever GPU inference is unavailable.
> Default campaign bounds are 25 engineering missions or 100 compatible masks.
>
> Every local RunPod GPU command must use
> `tools/run_with_shared_pod_gpu_lease.py`, the authoritative FIFO database
> `/workspace/.maskfactory/shared_pod_coordination/shared_gpu_leases_v1.sqlite`,
> and the protected MaskFactory owner token. Never kill or preempt foreign work;
> release the GPU after each atomic work cell. If local admission is unavailable,
> use only the brokered Serverless `decide`/`reserve`/`submit`/`reconcile` flow.
> For eligible read-only advisory reasoning, use only the governed OpenRouter
> manager and its Qwen-first policy. Otherwise continue a CPU-safe lane. Never
> dual-submit or call endpoints/providers directly.
>
> The engineering worker may prepare bounded repository packets, patch bundles,
> focused tests, repair proposals, evidence, and tracker-ready recommendations
> in an isolated staging area. It does not receive credential, Git/GitHub,
> destructive filesystem, infrastructure, RunPod lifecycle, final tracker,
> final mask, or final adoption authority. Codex reviews one consolidated
> campaign packet instead of every internal step.
>
> The mask work cell must resolve exact label/owner/side/neighbor/protected
> resources; generate multiple provider candidates; run deterministic hard QA;
> perform bounded hypothesis-distinct repair; render exact evidence panels; and
> use a qualified high-end primary visual critic plus a qualified independent-
> family juror. A text-only LLM cannot approve masks. Hard QA always vetoes and
> uncertain records abstain without blocking unrelated records.
>
> Eliminate routine micro handoffs. Escalate only security/credential needs,
> destructive or external actions, unresolved authority conflicts,
> contradictory truth, unreconciled ambiguous completion, policy/schema
> changes, or a terminal campaign decision. Target at least 80% autonomous
> preparation of eligible work, no more than one routine Codex handoff per
> 25 missions or 100 masks, at least 70% less Codex usage per accepted artifact,
> zero duplicate submissions/promotions, 100% terminal reconciliation, and 100%
> local lease release.
>
> Do not call the system complete after another isolated prompt or unit-test
> pass. Completion requires one real 25-mission engineering campaign, one
> governed 100-mask campaign, restart/ambiguous-completion and routing fault
> drills, and three consecutive mixed campaigns meeting all autonomy, safety,
> visual-authority, reconciliation, GPU-release, and Codex-reduction targets.
> Until that evidence bundle passes, report
> `SELF_HOSTED_AUTONOMOUS_LLM_THROUGHPUT_INCOMPLETE`.

The closed v1 authority, telemetry, and acceptance bytes referenced by this
message are:

- `configs/self_hosted_autonomy_contract_freeze_v1.json`;
- `configs/self_hosted_autonomy_campaign_telemetry_v1.schema.json`; and
- `configs/self_hosted_autonomy_acceptance_v1.schema.json`.

Unknown fields, duplicate item identities, missing measures, or stale bound
hashes fail closed.
