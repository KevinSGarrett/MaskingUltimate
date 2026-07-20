# Autonomous Session Handoff — 2026-07-19

Durable proof-tier handoff after host STATIC exhaustion, RUNTIME climb, safe ephemeral reclaim, and operator-action sealing.
**Do not claim project complete. Preserve all work. No governed wipe.**

## Authoritative worktree

| Field | Value |
| --- | --- |
| Root | `C:\Comfy_UI_Main_Masking` |
| Branch | `codex/maskfactory-runtime-implementation` |
| Evidence HEAD at handoff authoring | `e6a799cf27f13abbb57afb6c531319a0e5dc076a` (*Record safe ephemeral cache reclaim; doctor still disk-blocked.*) |
| Remote | `origin/codex/maskfactory-runtime-implementation` (pushed through `e6a799cf`; this handoff commit follows) |
| Docker engine (last probe) | 29.4.3 / docker-desktop up |
| Production CVAT | localhost:8080 **v2.24.0 only** (`cvat269` = migration rehearsal only) |

After pull, treat `git rev-parse HEAD` on this branch as authoritative; parent evidence commit remains `e6a799cf`.

## Highest proof tiers (honest)

| Surface / profile | Highest tier | Notes |
| --- | --- | --- |
| **core_autonomous_runtime** | `STATIC_PASS` (profile); live ceiling `RUNTIME_PASS_BOUNDED` | `profile_complete=false`; `PRODUCTION_EVIDENCE_PASS` **NOT_CLAIMED** |
| Host STATIC residual inventory | exhausted | `host_side_static_gaps_remain=false` (`residual_blocker_inventory_20260719.json`) |
| CVAT API 2.24 | `RUNTIME_PASS_BOUNDED` | production localhost:8080 |
| Nuclio pth-SAM2 smoke | `RUNTIME_PASS_BOUNDED` | via `tools/smoke_cvat_sam2.py` |
| Ollama VLM smoke | `RUNTIME_PASS_BOUNDED` | advisory; not VLM calibration / gold |
| Mode B `/health` + `/models` | `RUNTIME_PASS_BOUNDED` | champions=0; draft-service only |
| Mode B `/predict` | `AWAITING_RUNTIME` | HTTP 503; no invented champions |
| Mode B `/refine` | `AWAITING_RUNTIME` | longer-timeout retry skipped under <<75 GiB |
| Doctor all-green | `RUNTIME_BLOCKED` | C: ~12.7 GiB after ephemeral reclaim (was ~4.07); still <<75 GiB ingest |
| P6-08 / P6-09 / P6-10 producer | contracts complete (STATIC) | fixture Main cannot close production core |
| P6-11 / P6-12 bridge | `STATIC_PASS` + **AWAITING_MAIN** | HARD: MF-P6-11.02, MF-P6-11.07, MF-P6-12.05 |
| Package hard QA (bounded) | `HARD_QA_PASS_BOUNDED` | not gold |
| Package visual QA (bounded) | `VISUAL_QA_REVIEWED_WITH_DEFECTS` | **not** `VISUAL_QA_PASS_BOUNDED` |

Milestone seal: `qa/live_verification/milestone_proof_tiers_20260719.json`  
revision **`post_ephemeral_reclaim`** · self_sha256 `7986f63423c5d3a0477a2ea98777cc76665c5f369240931ea60341e4ee5829dc`  
(supersedes `8c792773780e4a7a3d19b80649ac78b2b88e8448001b1fc7829a6e330bd0a32b`)

## Exact Kevin actions (from sealed list)

Authority: `qa/live_verification/needs_kevin_actions_20260719.json`  
status=`OPEN_NONE_COMPLETE` · file_sha256 `0f785cb1a9d3a6d2846cdb17bb98c5ab092b9374bf755813ec53caeeceb9c17c`  
**None of these are claimed done.**

Ordered by priority in that file:

1. **disk_reclaim_above_75_gib** — Free C: above 75 GiB ingest floor without unauthorized destructive prune. Current ~12.7 GiB (reclaim seal after=12.781 GiB). Still blocks doctor-green.
2. **repair_ubuntu_2204_ext4_vhd** — Elevated offline VHD repair via `tools/Repair-MaskFactoryWslVhd.ps1 -ConfirmRepair` (Ubuntu-22.04 rootfs non-executable for live CUDA SAM 3.1).
3. **sop1_jobs_21_to_25** — CVAT SOP-1 human correction on production jobs 21–25 (`http://localhost:8080/tasks/21` … `/25`); `human_anchor_train_count` remains 0.
4. **dvc_s3_push_first_package** — Authorize AWS creds (dev acct) + first governed `dvc push` to `s3://maskfactory-dvc-dev` (`aws_credentials_present=false`).
5. **b1_restore_drill_one_package** — After a corrected human-anchor seed exists, B1 restore drill from `D:\MaskFactoryBackup\` (`b1_mirror_present=false`).
6. **main_supply_adapter_adoption_qualification** — From `KevinSGarrett/Comfy_UI_Main`, supply real production adapter/adoption/qualification artifacts (AWAITING_MAIN; HARD MF-P6-11.02 / 11.07 / 12.05).
7. **confirm_meta_hf_terms_and_live_sam31_smoke** — Keep Meta/HF terms accepted; after VHD repair, live CUDA SAM 3.1 smoke (checkpoint bytes ≠ live smoke credit).
8. **authorize_cloud_teacher_corpus_and_budget** — ≥200 human-anchor corpus + billable shadow budget auth (`paid_cloud_calls_executed=false`).
9. **supply_governed_multiperson_demo_sources** — Real 2–4-person sources for 10–20 image demo (`kevin_multi_person_sources_required=true`).

Full exact commands and expected artifacts are in the JSON groups above — do not invent completions.

## What NOT to wipe / destroy

Preserve all of the following. **No governed wipe. No `docker system prune` / volume wipe without explicit Kevin authorization.**

- `MaskedWarehouse` and warehouse intakes
- `models/` (including `models/runtime_cache/`)
- `data/packages` and draft/gold package trees
- Docker volumes, `docker_data.vhdx`, CVAT/Nuclio data
- `C:\Users\kevin\.ollama` (~26 GiB managed models)
- `qa/live_verification/*` seals, `Plan/`, committed evidence under `runtime_artifacts/` that is already hashed in OPS_LOG
- Production CVAT **v2.24** on localhost:8080 (do not treat cvat269 as production)
- Branch history and this handoff file

Ephemeral reclaim already performed (pip/uv/Temp build caches only) — see `qa/live_verification/disk_ephemeral_reclaim_20260719T2057.json`. Do not expand reclaim into governed paths.

## How to resume

1. `cd C:\Comfy_UI_Main_Masking` && `git checkout codex/maskfactory-runtime-implementation` && `git pull`
2. Re-read `Plan/DOCKER_RUNTIME_AND_SESSION_USE.md`; live-probe: `docker info`, `docker ps`, CVAT `http://localhost:8080/api/server/about`, Ollama `http://127.0.0.1:11434/api/version`
3. Confirm proof tiers: `qa/live_verification/milestone_proof_tiers_20260719.json` revision `post_ephemeral_reclaim`
4. Operator gates: open `qa/live_verification/needs_kevin_actions_20260719.json` — execute Kevin actions in priority order; agents must not fabricate CVAT clicks, AWS pushes, Main adoption, Meta terms, paid cloud, or multi-person authority
5. After disk ≥75 GiB: re-run `maskfactory doctor` and Mode B refine longer-timeout retry; do **not** force-register draft champions for `/predict`
6. AWAITING_MAIN work continues only with real Main-repo artifacts pinned back here — fixture_main / producer STATIC cannot close `core_autonomous_runtime`
7. Tracker: `MF-P0-EXIT` still doctor-blocked; core close remains `MF-P6-12.06` behind HARD Main blockers

## Honest non-claims

- Project / `core_autonomous_runtime` **not** complete
- No doctor-green, gold, `VISUAL_QA_PASS_BOUNDED`, `PRODUCTION_EVIDENCE_PASS`, Main-complete
- No champion_bodypart / hand / clothing; champions=0
- No DVC S3 push, B1 restore, live SAM 3.1 CUDA smoke, paid cloud-teacher, multi-person demo

## Key evidence pointers

- `qa/live_verification/needs_kevin_actions_20260719.json`
- `qa/live_verification/milestone_proof_tiers_20260719.json` (revision `post_ephemeral_reclaim`)
- `qa/live_verification/residual_blocker_inventory_20260719.json`
- `qa/live_verification/proof_tier_runtime_reprobe_20260719T1917.json`
- `qa/live_verification/disk_ephemeral_reclaim_20260719T2057.json`
- `qa/live_verification/mode_b_predict_draft_provider_policy_blocker_20260719.json`
- `Plan/OPS_LOG.md` (runtime climb ~00:40 UTC; ephemeral reclaim 01:49 UTC; this handoff)
