# 09 — CROSS-PROJECT BRIDGE RELEASE AND SESSION HANDOFF

Machine-readable pre-commit preservation evidence is generated at
`Plan/Instructions/10_AUTONOMOUS_CORE_BRIDGE_PLANNING_PRESERVATION_MANIFEST.json`.
It enumerates every other dirty/untracked packet file with its status, size, and SHA-256, binds both task
IDs/worktrees/branches and the adoption order, and explicitly carries no runtime-release authority.
The manifest names itself separately and uses its canonical self-seal to avoid recursive self-hashing.
Regenerate it with `tools/build_maskfactory_bridge_planning_preservation_manifest.py` immediately
after the producer contract freeze and before the preservation commit.

This protocol preserves the MaskFactory↔ComfyUI bridge across repositories,
Codex tasks, worktrees, restarts, and invalidations. It is a coordination
authority, not a substitute for a signed producer release, Main adoption
receipt, operational certificate, or runtime qualification evidence.

## 1. Pinned project and task identities

| Role | Project root | Codex task ID | Responsibility |
|---|---|---|---|
| MaskFactory producer | `C:\Comfy_UI_Main_Masking` | `019f4cfc-60c3-7500-8626-261dcf70db5d` | Build, certify, release, revoke, and repair MaskFactory capabilities and artifacts. |
| Main ComfyUI consumer | `C:\Comfy_UI_Main` | `019f422f-88b1-7382-872b-21de2089e983` | Pin a released producer, validate compatibility, implement the adapter/controller/App projection, execute consumer qualification, and issue adoption receipts. |

The current isolated producer-planning worktree is
`C:\w\mask-autonomy-bridge-plan` on `codex/mask-autonomy-bridge-plan`. It must
not be deleted, cleaned, reset, or treated as disposable dirt until its commit,
PR, review outcome, and receiving-task acknowledgement are recorded. Its dirty
bytes are planning work only and can never be consumed as runtime authority.

The current isolated Main-planning worktree is
`C:\w\main-maskfactory-bridge-plan` on
`codex/w64-maskfactory-bridge-plan`. The same preservation rule applies.

## 2. Two distinct bridges

1. **Runtime/data bridge:** Main's external `MaskFactoryAdapter` consumes only
   an immutable adopted release through Mode A package reads or Mode B
   localhost request/receipt contracts. It never imports a dirty producer
   module, reaches into producer internals, or upgrades producer authority.
2. **Project/session coordination bridge:** producer release snapshot → Main
   consumer requirements → compatibility result → adoption receipt →
   invalidation/feedback/repair → superseding release. Codex task messages
   announce durable artifacts and preserve work, but they do not grant
   authority by themselves.

## 3. Required preservation record

Before either task changes or removes bridge-related files, it must read this
protocol and the latest durable handoff. The handoff must record:

- both task IDs, repository roots, worktrees, branches, and intended PR bases;
- producer commit/tree, PR, schema catalog, semantic-profile, release-snapshot,
  capability-snapshot, trust-key registry, journal checkpoint, and test hashes;
- Main commit/tree, PR, consumer-requirements, executable field mapping,
  compatibility result, adoption decision, pinned artifacts, and test hashes;
- exact status: `planning_only`, `producer_contract_frozen`,
  `producer_release_published`, `consumer_mapping_frozen`,
  `partially_adopted`, `adopted`, `rejected`, `invalidated`, or `superseded`;
- unfinished runtime slices, blockers scoped to the correct completion profile,
  and the next deterministic action;
- explicit statement that the full 7,282-record model-library ingestion and
  qualification remain deferred until complete intended downloads,
  deterministic inventory verification, and Main-task acknowledgement.

Do not use a conversational summary, dirty working tree, copied node pack,
floating branch, or file-presence check as the preservation record.

## 4. Producer-to-consumer adoption order

1. Freeze and validate MaskFactory producer schemas, semantic invariants,
   fixtures, compatibility rules, trust anchors, and claim firewall.
2. Preserve the frozen producer packet commit. If the active producer line
   advances after that freeze, integrate it with a non-rewriting merge commit,
   generate
   `11_AUTONOMOUS_CORE_BRIDGE_INTEGRATION_RECONCILIATION_MANIFEST.json`, and
   account for every base-owned byte supersession while proving that all 12
   wire schemas remain exact. Rerun validation, push, and keep the PR
   non-merged.
3. Send both the immutable producer-packet commit and the current integration
   head, plus the exact schema/catalog hashes and reconciliation-manifest seal,
   to the Main task. Main pins wire authority to the immutable producer commit;
   the PR integration head is review/merge ancestry rather than a replacement
   producer identity.
4. Main updates only its executable producer-v1→Main-port mapping and release
   pin, reruns all consumer and historical package tests, then rebases onto
   current protected `origin/main`.
5. Main commits, pushes, and opens a non-merged PR. It may record
   `partially_adopted` for planning/contracts; it must not record runtime
   `adopted` until clean installs and required vertical slices pass.
6. Each task records the other's PR/commit and the required adoption order.
   Neither task deletes the preserved worktree before acknowledgement.

Planning-contract completion is not runtime implementation. A producer PR can
freeze the wire format without proving a live service; a Main PR can freeze the
adapter port and App read models without proving end-to-end ComfyUI execution.

## 5. Invalidation and reciprocal resumption

When a signer/key, certificate, package, provider, ontology, policy,
capability, schema, semantic profile, release, or consumer requirement changes:

1. MaskFactory appends a trusted signed invalidation or supersession event with
   exact target scope and journal position; immutable historical evidence is
   retained.
2. The producer task sends the event/release identity to the Main task and
   persists the same identity in the next durable handoff.
3. Main invalidates affected cache/routes/adoption scope, blocks only dependent
   DAG work where safe, reconciles `outcome_unknown`, and never silently falls
   back to a weaker mask.
4. Main publishes an authenticated adoption/rejection/partial-adoption receipt
   for the new release and sends its identity back to MaskFactory.
5. Both tasks resume from the last mutually acknowledged journal/adoption heads,
   not from whichever conversation appears newest.

Duplicate same-body notices are idempotent. Same-key/different-body, missing
events, forks, stale heads, unknown signers, or reordered lifecycle transitions
fail closed and require journal reconciliation before use.

## 6. Task-message template

Every producer freeze/release or Main adoption message should contain:

```text
MASKFACTORY_COMFYUI_BRIDGE_HANDOFF
producer_task_id: 019f4cfc-60c3-7500-8626-261dcf70db5d
consumer_task_id: 019f422f-88b1-7382-872b-21de2089e983
status: <closed status vocabulary>
producer_commit_or_pending: <sha-or-pending>
producer_pr_or_pending: <url-or-pending>
consumer_commit_or_pending: <sha-or-pending>
consumer_pr_or_pending: <url-or-pending>
release_snapshot_sha256_or_pending: <sha-or-pending>
schema_catalog_sha256_or_pending: <sha-or-pending>
consumer_mapping_sha256_or_pending: <sha-or-pending>
adoption_receipt_sha256_or_pending: <sha-or-pending>
runtime_claim: <none|bounded_fixture|qualified_slice|adopted_runtime>
model_library_gate: deferred_waiting_for_complete_model_download
preserve_worktrees: true
next_action: <one deterministic action>
```

The task message is a wake-up and preservation signal. Receivers must verify
the referenced Git and artifact bytes before changing project state.

## 7. Completion rule

Cross-project coordination is complete only when both tasks pin the same
producer/consumer artifact identities, the applicable PRs and adoption receipt
are durable, invalidation/recovery drills pass, and a fresh session can resume
without conversational memory. Human masks, CVAT corrections, blinded human
review, corpus volume, full-library download, DAZ work, and soak tests are not
required for `core_autonomous_runtime` coordination or closure.
