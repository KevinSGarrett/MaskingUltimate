# MaskFactory control-plane integration contract

This is a read-only integration map for external control planes. It does not
delegate MaskFactory release, tracker, provider, mask, or acceptance authority.
In particular, an external control plane must not write MaskFactory SQLite
files, replay a correction, or treat a receipt as a release decision.

## Product workflow state

The authoritative product workflow index is
`C:\Comfy_UI_Main_Masking\data\maskfactory.sqlite`.  It is defined by
`src/maskfactory/state.py:DEFAULT_DB_PATH`; there is no environment-variable
override or configuration key for this default in the current implementation.
CLI commands may explicitly receive a different path through their
`--database` option, but that is an owner-controlled invocation contract, not
an external-control-plane override.

This product index is not interchangeable with the campaign, fallback-route,
shared-GPU lease, OpenRouter, or Serverless broker SQLite ledgers.  Those are
independent control-plane records and cannot establish product-stage state.

`initialize_database()` requires SQLite `journal_mode=WAL`.  Mutable access
uses `WriterGuard` and `writer_connection()` from `maskfactory.state`:

- the exclusive guard is
  `data/maskfactory.sqlite.writer.lock`;
- it is created with exclusive creation and mode `0600`;
- its JSON owner record contains the owner PID, host, acquisition time, and
  resolved database path; and
- the guarded connection runs `BEGIN IMMEDIATE` before state mutation.

The supported read-only programmatic entry point is
`maskfactory.state.reader_connection(path)`.  It opens SQLite with
`mode=ro`, enables `PRAGMA query_only=ON`, and never acquires the writer
guard.  Consumers should query documented tables only (`images`, `stage_runs`,
`review_tasks`, `training_runs`, and `package_truth`) and treat unknown schema
versions or missing rows as unavailable state, not permission to repair it.

## Governed correction boundary

Only the MaskFactory owner may submit a correction through the canonical CLI.
The relevant owner-invoked commands are:

```text
maskfactory ingest IMAGE --database PATH --config configs/pipeline.yaml
maskfactory rescreen-quarantine IMAGE --database PATH --config configs/pipeline.yaml
maskfactory run IMAGE_ID --database PATH --config configs/pipeline.yaml [--plan-only]
```

`ingest` and `rescreen-quarantine` require an existing image path; `run`
requires a registered image identity and owner-selected roots/configuration.
They enforce the state-machine and policy checks in the product process.  An
external system may propose a hash-bound correction package for review, but it
must not call these commands, update the database, or create a synthetic stage
receipt.

## Stage graph and legal product transitions

The executable S00--S15 stage graph is exposed by `maskfactory run` and is
configured by `configs/pipeline.yaml`; `maskfactory run IMAGE_ID --plan-only`
is the owner-safe way to inspect a resolved stage plan.  The durable status
chain in `maskfactory.state` is:

```text
ingested -> drafted -> auto_qa -> vlm_qa -> in_review -> corrected
         -> approved_gold -> exported
```

At every nonterminal main-chain state, only the next status, `rejected`, or
`quarantined` is legal.  `corrected` may return to `in_review`; approved or
exported records may be corrected or deprecated; rejected/quarantined records
must re-enter through verified recovery to `ingested`.  `deprecated` is
terminal.  The product maps these states to S00, S09--S14 and fails closed on
an attempted skip or unauthorized regression.

## Review and evidence formats

Review, release, and bridge evidence are JSON records validated against the
schemas in `src/maskfactory/schemas/`.  Integrators must preserve the raw bytes
and validate the exact schema before relying on any claim.  The principal
cross-bound formats are:

- `maskfactory_integration_release_evidence.schema.json` -- clean-install,
  source/tree, inventory-parity, activation, verification, and rollback
  evidence for an integration release;
- `bridge_final_release_handoff_evidence.schema.json` -- producer release and
  independent Main adoption evidence; and
- `bridge_journal_reconstruction_evidence.schema.json`,
  `bridge_recovery_evidence.schema.json`, and
  `bridge_failure_control_evidence.schema.json` -- recovery and failure-control
  evidence.

Package truth is recorded separately in the product database as
`package_truth`, with a package path, truth tier, partition, training weight,
and optional certificate-bundle digest.  It is not a blanket promotion flag.
Accepted cross-session use still requires an immutable release and independent
ComfyUI adoption; fixture, advisory, static, or historical receipts do not
authorize production use.

## Common integration errors

- Do not use a fallback or broker ledger as the product workflow database.
- Do not infer stage success from a generated file; use the guarded workflow
  state and exact evidence schema.
- Do not bypass the writer guard, fabricate owner metadata, or delete a stale
  lock from another process.
- Do not promote a visual or mask result from metadata, text reasoning, a
  detached provider response, or an unqualified critic receipt.
- Do not treat this document as authority to create routes, jobs, releases, or
  corrections.
