# Comfy_UI_Main MaskFactory Consumer (isolated)

An **isolated, sibling** Main-side consumer of the MaskFactory ComfyUI bridge.

It exists so that real, non-fixture *Main-side* adoption evidence for
**MF-P6-11 / MF-P6-12** can be produced **without touching** the dirty
`C:\Comfy_UI_Main` Wave64 branch. It imports and calls the producer bridge
contracts from the sibling MaskFactory checkout at
`C:\Comfy_UI_Main_Masking` (override with `MASKFACTORY_PRODUCER_ROOT`).

## Honesty ceiling (binding)

- Authority kind is **`isolated_main_consumer`** — real machinery, real Ed25519
  signatures, real producer contract bytes.
- It is **NOT** `fixture_authority` and **NOT** the real Comfy_UI_Main runtime.
- Every receipt records `is_real_comfyui_main: false` and
  `main_adoption_complete: false`.
- It **cannot** and **does not** close the HARD blockers that require the real
  Main runtime: **MF-P6-11.02 / 11.07 / 12.05 / 12.06**. Those need the actual
  Comfy_UI_Main runtime to sign adoption/qualification/execution/result-history
  artifacts with `comfy-main-*` trust keys.
- The MaskFactory tracker may credit these receipts as isolated-consumer
  progress (STATIC_PASS depth on the DoD verify clauses) — never as a HARD close
  or `PRODUCTION_EVIDENCE_PASS`.

## What it runs (real producer machinery)

| Pillar | Producer API called | Item touched |
|---|---|---|
| adapter | `external_adapter_conformance` | MF-P6-11.01 |
| journal | `journal` append/checkpoint/validate | MF-P6-11.06 |
| circuit | `failure_control` fault-injection + circuit depth | MF-P6-11.07 |
| mode_a | `mode_a_package_read` adversarial matrix (~30 cases) | MF-P6-11.02 |
| qualification | `cross_project_qualification` producer_partial | MF-P6-12.05 |
| qual_depth | adversarial qualification firewall matrix | MF-P6-12.05 |
| firewall | `final_release_handoff` core-close firewall depth | MF-P6-12.06 |
| adoption | Ed25519 isolated-consumer attestation | MF-P6-11/12 adoption |

The adapter boundary in `src/mf_main_consumer/adapter.py` imports **only**
`maskfactory.contracts` (verified by AST at runtime), so the producer conformance
verifier accepts it as a durable, contract-only boundary.

## Usage

```bash
# maskfactory must be importable (editable install of the sibling repo, or it is
# auto-added to sys.path from $MASKFACTORY_PRODUCER_ROOT / default sibling path).
python run_consumer.py
# -> writes a sealed receipt to receipts/isolated_main_consumer_run_<ts>.json
```

Generated receipts (`receipts/`) and the built sdist (`dist/`) are git-ignored so
the tracked adapter source stays clean; receipts are pinned by `self_sha256` into
the MaskFactory producer repo's `qa/live_verification/` evidence.
