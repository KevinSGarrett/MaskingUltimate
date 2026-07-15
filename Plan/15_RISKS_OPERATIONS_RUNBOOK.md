# Document 15: Risks, Operations & Runbook

The operating manual for keeping MaskFactory healthy: risk register, daily/weekly routines,
disk & backup procedures, garbage collection, troubleshooting, incident playbooks, the Label
Studio contingency, and the glossary. Section numbers §4/§5/§6/§9 are referenced by other docs —
do not renumber.

---

## 1. Risk Register

| ID | Risk | L | I | Mitigation (built into the design) | Trigger/Owner |
|----|------|---|---|-------------------------------------|---------------|
| R01 | 8 GB VRAM OOM mid-stage | H | M | model-major batching, per-slot budgets, auto-retry at tile/half-size, fallback ckpts (doc 05 §5) | OOM in logs → Kevin |
| R02 | sm_120 wheel breakage on env rebuild | M | H | pinned cu128 lockfiles, doctor capability check, known-fix note (doc 06 pitfall 1) | doctor red |
| R03 | CVAT/nuclio instability on this machine | M | H | pinned v2.24.0, CPU interactor, §9 Label Studio switch fully specified | 3 failed sessions/wk |
| R04 | Model checkpoint drift / dead links / license change | M | M | SHA-256 registry, local `models\` cache is source of truth, fetch is no-op if hashes match | fetch mismatch |
| R05 | WSL `/mnt/c` I/O slowness stalls pipeline | M | M | hot work on ext4 `~/mfwork`, packages synced back (doc 06 §1) | stage runtime ×2 budget |
| R06 | Annotator fatigue → quality drift | M | H | quick-pass discipline, IAA 15% second review, honesty contract (doc 11 §6/§8) | IAA < 0.92 body |
| R07 | Systemic L/R swap poisoning gold | L | H | QC-014 2-of-3 vote is a BLOCK; flip-remap CI test; SOP trace-the-chain | any QC-014 in approved gold = incident §8 |
| R08 | Chest/clothing semantic errors (skin vs projected) | M | H | chest lane constitution, QC-019/020, purple-label separation, mandatory second review of projected | lane failure rate >10% |
| R09 | Data loss (disk death, accidental delete) | L | H | §5 backups (nightly mirror + weekly cold + git + DVC), monthly restore test | monthly drill |
| R10 | Disk exhaustion mid-run | M | M | §4 thresholds (warn <150 GB, block <75 GB), §6 gc, junction move procedure | doctor disk check |
| R11 | Ontology churn invalidating existing gold | M | H | change procedure only (doc 02 §9), §8-of-doc-12 evidence bar, back-annotation plan required | CHANGELOG entry |
| R12 | Overfitting to synthetic data | M | M | ≤30% mix cap, train-only rule, promotion invalid if win depends on >30% mix (doc 12 §9) | dataset card audit |
| R13 | VLM hallucinated verdicts steering reviewers | M | M | calibration gate (≥0.90/0.80), VLM can never approve/clear/edit, uncertain→no hints | eval regression |
| R14 | Laptop thermal throttling corrupts long runs | M | L | cooldown policy (sleep >87 °C), stage idempotency makes resume safe | temp logs |
| R15 | Scope creep (video, per-toe splits, dense crowd scenes) | H | M | v1 out-of-scope list (doc 01 §5), ontology growth gate (doc 12 §8), P7-05 formal go/no-go for video · **AMENDED (doc 17):** multi-person masking graduated out of this guard-list into fully-specced Phase P8 | any "quick add" |
| R16 | Privacy leak via cloud LLM | L | H | teacher runtime may be enabled, but image transmission is exact-hash/rights/provider default-deny; hash-chained cost/audit ledger (doc 10 §6) | audit review |
| R17 | State DB corruption/drift vs packages | L | M | packages are truth, `maskfactory reindex` rebuilds DB, nightly integrity sweep | reindex diff ≠ 0 |
| R18 | Instance mis-split (one real person falsely detected as two) or cross-instance mask bleed | M | H | QC-035/036 hard BLOCKs, deterministic ranking/tie-break, S09.5 reconciliation runs before any review time is spent (doc 17 §7, §15) | any QC-035/036 fire on approved gold = incident |

L/I = likelihood/impact (L/M/H). Review this table at each phase exit; add rows, never delete.

## 2. Daily Operations (≈5 min, any day the system is touched)

```
maskfactory doctor                      # env, GPU, disk, services, registry hashes
docker ps                               # cvat_server/db/redis + nuclio + ollama all Up
maskfactory status --queues             # incoming / careful / quick-pass / rejected counts
tail -n 30 logs/maskfactory_$(date).log # no ERROR lines unaccounted for
```
End of any working session: `git push` + `dvc push` (rule from doc 14 §10). Nightly (scheduled
task, Windows Task Scheduler → WSL): integrity sweep = `maskfactory verify-package --sample 10`
+ backup mirror (§5) + manifest lint (doc 10 §8).

## 3. Weekly Operations (Monday block, ~30 min)

1. `maskfactory coverage report` → note top deficits.
2. Open `qa\reports\acquisition_plan_<date>.md` (S15 output) → pick the week's acquisition items.
3. IAA report review (doc 11 §6) → any class < target ⇒ schedule guideline refresh, not blame.
4. Leaderboard glance: any tracked class error ↑ >5 pts 2 wks running ⇒ retrain trigger fires.
5. Backup verify (§5 quick variant) + disk headroom check (§4).
6. Friday: annotation block; log minutes/image — the G1 trend line is a weekly artifact.

## 4. Disk Management & Junction Move Procedure

Thresholds (doctor-enforced): **warn < 150 GB free on the data drive; BLOCK new ingests
< 75 GB.** Expected footprint: ~0.5–1.5 GB/package (source + maps + binaries + crops + panels)
⇒ 500 gold ≈ 250–750 GB. When C: is tight, move `data\` (and optionally `datasets\`, `runs\`)
to a larger drive with a junction — paths in code never change:

```
robocopy C:\Comfy_UI_Main_Masking\data D:\MaskFactory\data /MIR /COPY:DAT /DCOPY:T /R:2 /W:2
rename   C:\Comfy_UI_Main_Masking\data data_old        (keep until verified)
mklink /J C:\Comfy_UI_Main_Masking\data D:\MaskFactory\data
maskfactory verify-package --sample 25                  (hash-verify through the junction)
maskfactory reindex --dry-run                           (0 diffs expected)
rmdir /S /Q C:\Comfy_UI_Main_Masking\data_old           (only after both checks pass)
```
WSL note: junction targets resolve transparently under `/mnt/c/...`; re-run doctor after moving.
Never junction `models\` to an external/removable drive (checkpoint reads are latency-critical).

## 5. Backup Policy & Restore Testing

| Layer | What | How | Cadence |
|-------|------|-----|---------|
| B1 mirror | `data\packages`, `qa\`, `configs\`, `state.db` snapshot | `robocopy /MIR` to `D:\MaskFactoryBackup\` (or NAS) | nightly (scheduled) |
| B2 cold copy | zip of B1 + `models\model_registry.json` | external SSD, kept offline | weekly |
| B3 code | repo | `git push` (GitHub, Scentiment-Dev) | every session |
| B4 datasets/models | dataset builds + champion ckpts | `dvc push` → S3 `maskfactory-dvc-dev` | every build/promotion |
| B5 DB | SQLite | `sqlite3 state.db ".backup ..."` into B1 before mirror | nightly, 7 rotations |

**Restore test (monthly, D10 item):** pick 3 random packages from B2 → restore to a temp dir →
`maskfactory verify-package --root <temp>` (all hashes must pass) → open one in CVAT via push to
confirm end-to-end usability → log result in `Plan\OPS_LOG.md`. A backup that has never been
restored is a hope, not a backup. Quick weekly variant: verify 3 packages from B1 in place.

## 6. Garbage Collection (`maskfactory gc`)

Dry-run by default; `--apply` to execute; every deletion listed first, logged to
`logs\gc_<date>.log`. Eligible:
- `deprecated` mask version folders (`masks@v1\` etc.) older than **30 days** whose superseding
  version is `human_approved_gold` (the diff report QC-034 produced is retained).
- `work\` stage intermediates for packages already approved (recomputable by re-run).
- Quarantine items reviewed and marked `discard` (age >14 days) — reviewed, never auto.
- Orphan files not referenced by any manifest (reindex cross-check) — listed for manual confirm.
Never eligible: anything referenced by a manifest hash map, holdout exports, `qa\iaa\` archives,
leaderboard artifacts. Post-gc: `verify-package --sample 10` + reindex must be clean.

## 7. Troubleshooting Table (Symptom → Cause → Fix)

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `RuntimeError: no kernel image ... sm_120` | wrong torch wheel | reinstall pinned cu128 wheels from `env\` lock (doc 06 pitfall 1); doctor confirms capability (12,0) |
| CVAT 502 / login loop | containers half-up after reboot | `docker compose -f cvat\docker-compose.yml down && up -d`; wait for `cvat_server` healthy; check Docker Desktop WSL integration on |
| SAM2 interactor spinner forever in CVAT | nuclio function crashed/cold | `nuctl get functions` → redeploy `pth-sam2`; CPU function cold start up to ~60 s is normal |
| Ollama OOM / VLM slow | model too big for free VRAM slot | ensure pipeline released GPU (gpu.lock free); Q4 model only; fallback llama3.2-vision; batch S11 model-major |
| QC-002 "mask not binary" BLOCK | some writer bypassed png_strict | find writer via stack in qa_report; only `png_strict.py` may write masks (QC-030 / CI lint) |
| QC-005 dims mismatch | resize snuck into a stage | stage must operate at native dims or record transform; check crop paste-back transform |
| QC-014 L/R flag storm on one image | subject in mirror pose / DensePose confused | trust the 2-of-3 vote; review with SOP-2 trace-the-chain; if human confirms correct, log override reason (vote stays advisory only for `uncertain`, never for BLOCK) |
| Fusion disagreement > 40% pixels (QC-031 storm) | one source degraded (e.g., parsing ckpt wrong) | check `model_registry` hashes; re-run stage solo; compare source overlays in panel |
| `dvc push` fails | AWS creds/expired token (dev 548846591581) | refresh SSO/keys; `dvc push -r maskfactory-dvc-dev -v`; artifacts are still safe locally + B1 |
| WSL clock skew breaks TLS/downloads | Windows sleep drift | `sudo hwclock -s` (or `wsl --shutdown` + restart) |
| Pipeline "GPU busy" refusal | stale `runs\gpu.lock` after crash | confirm no python/uvicorn holds GPU (`nvidia-smi`), then delete lock; doctor reports stale locks |
| ComfyUI node "package not found" | wrong `packages_root` or status filter | check `maskfactory_nodes\config.json`; browser node lists nearest ids + statuses |
| Everything slow on `/mnt/c` | hot work not on ext4 | verify `~/mfwork` in use (doc 06 §1); doctor prints the IO check |
| Training loss NaN | fp16 overflow w/ Swin | switch AMP to bf16 (default), lower lr 2×, resume from last ckpt |

## 8. Incident Playbooks

**IP-1 Bad gold discovered after approval.** Freeze: mark package `rejected_needs_fix`; run
QC-034 regression sweep across all gold touching the same class; quarantine the class in
training (rebuild dataset excluding flagged ids); root-cause via panels + provenance; fix →
re-review → new version; leaderboard re-scored if a dataset changed. Log in `Plan\OPS_LOG.md`.

**IP-2 GPU dead / unavailable.** Degraded CPU mode (explicitly supported): intake, hashing,
export-binaries, QA format checks, packaging, CVAT (interactor already CPU), manifests — all run.
Suspended: S01–S09 model stages, VLM, training, serving. Annotation continues on existing drafts.

**IP-3 State DB corrupt.** Packages are the truth: `maskfactory reindex --rebuild` reconstructs
`state.db` from manifests; restore last B5 snapshot only if reindex itself fails; diff report
between the two must be empty before resuming.

**IP-4 Repeated CVAT data loss in a task.** Pull immediately (`cvat pull` keeps
`cvat_task_backup.zip`), export server backup, then evaluate §9 switch criteria.

## 9. Label Studio Switch Procedure (Contingency for R03)

Trigger: ≥3 CVAT-blocking failures in a week OR interactor unusable for >3 days with fixes
attempted. Decision recorded in OPS_LOG. Steps:
1. `docker compose -f cvat\label-studio-compose.yml up -d` — Label Studio + `label-studio-ml-backend`
   running the same SAM2.1 ckpt (registry hash) as an ML-assisted segmentation backend, bound
   127.0.0.1:8081.
2. `maskfactory cvat pull --all-open` first (nothing stranded), then `maskfactory ls init-project`
   (labels from ontology.yaml — same generator as CVAT, MF-P1-03 parity test covers both).
3. Bridge swap: `configs\cvat.yaml → provider: label_studio`; push/pull semantics identical
   (pre-annotations in, corrected masks + attributes out, backup zip retained).
4. Re-run one known-good package through annotate→package→verify as the acceptance test.
CVAT remains the default; this section exists so the fallback is a procedure, not a research task.

## 10. Maintenance Calendar

Daily (auto): B1 mirror, B5 DB snapshot, integrity sample, manifest lint. Weekly: §3 block,
B2 cold copy, gc dry-run review. Monthly: restore test (§5), gc --apply, risk table skim,
dependency CVE glance (pip-audit) — upgrades only via lockfile bump + doctor + CI. Per phase
exit: doc 14 checkboxes + DECISIONS_LOG. Per ontology change: CHANGELOG_ONTOLOGY.md entry.

## 11. Glossary

**Atomic mask** — smallest exclusive body-part unit; owns pixels in `label_map_part`. **Band /
region mask** — non-exclusive zone (joints, waist, contact) allowed to overlap atomics.
**Derived union** — script-generated combination (left_hand = hand_base ∪ fingers); never
hand-authored. **Gold** — human-approved, format-verified truth; binary {0,255}, never softened.
**Inpaint derivative** — dilated/feathered copy of gold for editing; explicitly not truth.
**Projected / amodal** — estimated region under clothing/occlusion; separate directory, separate
truth class, purple in UI. **Protected class** — QA-only mask (other_person, background, face)
used to catch bleed. **Panoptic map** — single indexed PNG where every pixel has exactly one
PART (or MATERIAL) ID. **Lane** — specialist sub-pipeline for a hard class (hands, chest, hair,
feet). **Consensus/fusion** — weighted per-pixel vote across sources (S09). **Crop contract** —
1.6×bbox→1024 crop with recorded inverse transform, paste-back IoU ≥0.995. **Trimap** —
{fg, bg, unknown} tri-level map feeding matting. **RLE** — run-length encoding used in COCO
exports and CVAT transport. **IAA** — inter-annotator agreement (second-review IoU). **Champion**
— registry-pointed model currently serving a role; promotion is a one-line registry edit.
**BLOCK / ROUTE / WARN** — QA severities: unapprovable / must-review / advisory. **doctor** —
the environment self-check CLI; green doctor is the precondition for every session.
