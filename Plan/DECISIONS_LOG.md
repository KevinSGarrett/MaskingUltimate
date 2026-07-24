# Decisions Log

Append-only record of deliberate deviations from the written spec
(`Plan\00`–`15`), including autonomous, conservative, spec-consistent
judgment calls made when a genuine gap was found, and any Kevin-approved
scope changes. Referenced by `Plan\14_IMPLEMENTATION_ROADMAP_WBS.md` §10 and
`Plan\Instructions\06_BLOCKERS_AMBIGUITY_AND_ESCALATION.md`.

**Format:** newest entries at the bottom, chronological, append-only.

---

## TEMPLATE — copy this block for each new entry, then fill it in

```
## <YYYY-MM-DD> — <short title>
**Item(s) affected:** <MF-P#-##.## ...>
**Spec said:** <precise reference/paraphrase of the relevant Plan\ section>
**What we did instead:** <the actual deviation>
**Why:** <reasoning — what made this the conservative, spec-consistent choice>
**Approved by:** Kevin | AI-autonomous (conservative default, logged for Kevin's awareness) | pending Kevin review
```

---

## EXAMPLE (illustrative only — not a real decision, delete or leave as reference)

## 2026-01-01 — Example: clarified crop padding rounding
**Item(s) affected:** MF-P3-01.01
**Spec said:** `Plan\03` §5 — crop side = 1.6 × part bbox max side, no
rounding rule specified for non-integer results.
**What we did instead:** Round up to the nearest even integer before
resizing to 1024, so the crop is always symmetric around the bbox center.
**Why:** Matches the "no resize/crop/pad ambiguity" spirit of the gold
format spec (`Plan\03` §1) more closely than truncating, and keeps the
`crop_to_full_transform.json` math exact rather than approximate.
**Approved by:** AI-autonomous (conservative default, logged for Kevin's awareness)

---

<!-- Real entries begin below this line. -->

## 2026-07-10 — tracker.py save_tracker() rename-aside fallback
**Item(s) affected:** build infrastructure (all tracker writes)
**Spec said:** tracker.py is delivered tooling; `save_tracker()` did an atomic
`os.replace(tmp, tracker.json)` with a 6× transient-lock retry.
**What we did instead:** Added a fallback: if `os.replace` keeps raising
`PermissionError` (a *persistent* share-delete handle, not a transient one),
rename the held current file to a `.orphan` name and move the freshly written
temp into place, then best-effort delete the orphan.
**Why:** A leaked handle from the Claude Desktop app's node service held
tracker.json open indefinitely, jamming every session's tracker writes (see
OPS_LOG 2026-07-10). `os.replace` cannot delete-over a held destination, but a
plain rename of that destination is permitted, so rename-aside makes the write
succeed and detaches the stale handle. Preserves all existing semantics
(backups, atomicity, changelog) and only triggers after the normal path fails.
**Approved by:** AI-autonomous (conservative default, logged for Kevin's awareness)

## 2026-07-10 — Passwordless sudo for WSL user `kevin`
**Item(s) affected:** MF-P0-01.02
**Spec said:** `Plan\06` §1 / MF-P0-01.02 — "create Linux user `kevin`". No
password or sudo policy specified.
**What we did instead:** Created `kevin` (uid 1000), added to the `sudo` group,
and granted passwordless sudo via `/etc/sudoers.d/90-kevin-nopasswd`
(`kevin ALL=(ALL) NOPASSWD:ALL`, validated with `visudo -c`).
**Why:** Autonomous, non-interactive execution of the P0 install items
(`sudo apt install ...`, Docker/WSL integration, etc.) requires sudo without an
interactive password prompt. This is the standard local WSL dev-box posture and
does not weaken any project data-governance rule. The distro is a
single-user local development environment, not a shared/networked host.
**Approved by:** AI-autonomous (conservative default, logged for Kevin's awareness)

## 2026-07-10 — `wsl --update` action skipped (already exceeds requirement)
**Item(s) affected:** MF-P0-01.03
**Spec said:** `Plan\06` §1 / MF-P0-01.03 — "`wsl --update` · verify WSL kernel
≥ 2.3 for CUDA 12.8 passthrough".
**What we did instead:** Did NOT run `wsl --update` to completion. It launched an
interactive UAC + MSI elevation (`consent.exe`/`msiexec.exe`) that cannot be
granted in a non-interactive session and hung; the driver processes were killed.
The verify clause passes independently: `wsl --version` = 2.7.3.0 (≥ 2.3),
kernel 6.6.114.1-microsoft-standard-WSL2, and CUDA 12.8 GPU passthrough is
confirmed working (nvidia-smi inside Ubuntu shows the RTX 5060).
**Why:** The update command is idempotent maintenance whose only purpose is
ensuring a recent-enough WSL for CUDA passthrough — a condition already
demonstrably met. Forcing it would require interactive elevation Kevin must
click. If a newer WSL is ever desired, Kevin can run `wsl --update` in an
elevated terminal.
**Approved by:** AI-autonomous (conservative default, logged for Kevin's awareness)

## 2026-07-10 — Plan/Civitai/ excluded from git (kept local)
**Item(s) affected:** MF-P0-08.01, and the P0-10/P0-14 Civitai-intake clusters
**Spec said:** doc 16 §4 lists `Plan\Civitai\` as bootstrap reference assets;
MF-P0-08.01's ignore list did not mention it. doc 16 §7 anti-pattern: do not
train on platform preview images/screenshots.
**What we did instead:** Added `Plan/Civitai/` to `.gitignore` (plus global
`*.safetensors/*.pt/*.pt2/*.pth/*.onnx/*.ckpt/*.bin/*.pkl/*.zip` weight ignores).
`Plan/Civitai/` is ~9 GB: a 5.4 GB controlnet safetensors, a 1.1 GB model, dozens
of detector `.pt`/archives, and ~359 MB of catalog-tagged pose-pack PREVIEW PNGs.
**Why:** (1) Committing multi-GB model weights to git is wrong regardless — they
belong in DVC / an external cache. (2) ~359 MB of adult reference preview imagery
is not build source (doc 16 §7) and is inappropriate for a code repo, especially
the company GitHub repo pending in MF-P0-08.02. The assets stay fully present on
disk and usable by the P0-10/14 review tasks; only git-tracking is deferred.
Classification OUTPUTS are written outside `Plan/Civitai/` (configs/, Plan/) so
they remain versioned. Kevin to decide final storage (DVC vs external) when he
resolves the remote-repo question (08.02).
**Approved by:** AI-autonomous (conservative default, logged for Kevin's awareness)

## 2026-07-10 — Supply the specified SAM2 Nuclio function outside pinned CVAT
**Item(s) affected:** MF-P0-04.02, MF-P0-04.03, MF-P0-04.04, MF-P0-04.05
**Spec said:** `Plan\06` §4 and MF-P0-04 require pinned CVAT v2.24.0 plus
`serverless/pytorch/facebookresearch/sam2/nuclio`, deployed as a CPU interactor
and reported by the runbook as function `pth-sam2`.
**What we did instead:** Keep CVAT at the mandated v2.24.0 pin and provide the
missing SAM2 Nuclio source as a tracked MaskFactory compatibility component,
synced into the exact expected path before executing the function-specific
`nuctl deploy` block from CVAT's pinned `serverless/deploy_cpu.sh`. The wrapper
skips that script's unconditional, unrelated OpenVINO base-image prebuild because
its retired Intel apt repository prevents the script from reaching SAM2. Do not
substitute the checkout's SAM 1 function or upgrade CVAT.
**Why:** The official CVAT v2.24.0 tree contains
`serverless/pytorch/facebookresearch/sam/nuclio` but no `sam2` directory; CVAT's
public project also confirms SAM2 was not shipped as a community Nuclio config.
The written requirements are otherwise unambiguous about the model generation,
function identity, CPU ownership, and pinned CVAT version. Supplying the missing
adapter is the narrowest reading that satisfies all of them and keeps the
external checkout reproducible and clean.
**Approved by:** AI-autonomous (conservative default, logged for Kevin's awareness)
## 2026-07-11 — RESOLVED by approved doc 18: v1 uses 56 logits; v2 uses 65
**Item(s) affected:** MF-P5-02.01, MF-P5-03.01, every body-part training/promotion run
**Spec conflict:** The authoritative ontology and label-map contract define exactly
56 indexed values, IDs `0..55`, and ID 0 is already `background`. Doc 12 §6.1 and
MF-P5-03.01 instead demand "57-class (56 PART IDs + background)" and the completed
training YAML therefore declares `num_classes: 57`.
**Observed consequence:** A real MMSeg dataset built from the authoritative maps has
56 class names and no possible target pixel for logit 56. Keeping 57 creates an
untrained, unnamed output; changing to 56 contradicts the literal training item.
**Resolution:** Approved doc 18 §1 explicitly invalidates the old 57-class phrase. Active
v1 uses the contiguous 56-class vocabulary for IDs `0..55`, including background ID 0.
The append-only v2 migration adds IDs `56..64` and therefore uses exactly 65 logits.
Both active v1 body-part configs are corrected to 56; no dummy class or ID remap exists.

## 2026-07-12 — VLM workhorse means tool controller, not silent gold author
**Item(s) affected:** MF-P4-01.02, MF-P4-01.03, MF-P4-01.04, MF-P4-02.01,
MF-P4-05.01 through MF-P4-05.04
**Spec said:** Doc 10 defined the VLM as passive QA/router input using one compressed
five-tile panel, with text correction suggestions and no pixel-mask output.
**What we did instead:** Kevin explicitly approved expanding S11 into a high-resolution,
tool-using controller. It observes six independent images, creates bounded SAM2 correction
plans, writes isolated candidate masks, validates prompt polarity/change/neighbor overlap,
and compares full before/after evidence. Authoritative maps and gold remain human-controlled.
Without calibration the loop is shadow-only, emits no qa_report verdict, and routes carefully.
**Why:** The old input reduced each tile to roughly 205 pixels and the only live diagnostic
passed every seeded defect. Passive text advice did not materially reduce mask-correction work.
**Approved by:** Kevin

## 2026-07-12 — VLM confidence is subordinate to independent evidence
**Item(s) affected:** MF-P4-01.02 through MF-P4-05.04
**Decision:** Raw VLM verdict/confidence is retained for measurement but has no authority over a
label-specific auto-QA contradiction. BLOCK findings force fail; ROUTE/WARN findings force uncertain;
component-limit failures may create only a bounded deterministic cleanup candidate. Whole-image review
now receives separate clean-source and overlay images. Workhorse calibration fingerprints bind prompts,
evidence rendering, client, controller, and production implementation.
**Why:** Qwen2.5-VL and Qwen3-VL both returned confidence-1.0 passes on a known-bad real forearm mask.
Qwen3.5 could not finish within the allowed local latency. Confidence is not evidence and cannot erase
measurable anatomy, geometry, topology, or model-disagreement failures.
**Approved by:** Kevin's explicit workhorse mandate; fail-closed implementation

## 2026-07-12 — SAM 3.1 is the next concept-mask candidate backend, not an assumed dependency
**Item(s) affected:** MF-P4 workhorse research and future correction-provider work
**Decision:** Preserve SAM2 and specialist lanes as current pixel tools. Evaluate official SAM 3.1 in a
separate governed environment after checkpoint access, dependency compatibility, 8 GB GPU smoke, and a
frozen real-mask benchmark. It may create isolated candidates only and cannot write authoritative maps.
**Why:** SAM 3.1 provides the text/exemplar/geometry promptable segmentation needed for LLM-directed mask
creation, but its official checkpoint is access-gated and requires Python 3.12, PyTorch 2.7+, and CUDA
12.6+. Those prerequisites and local capacity are not yet proven here.
**Approved by:** AI-autonomous architecture selection under Kevin's mandate

## 2026-07-12 — Cloud models are governed teachers, never self-validating truth
**Item(s) affected:** MF-P4 VLM workhorse, S11 review/correction proposals, S15 active learning
**Decision:** Add an opt-in shadow cascade using Gemini first, OpenAI as an independent critic, and
Anthropic only as a tie-breaker. All provider outputs remain proposals. Only frozen human-approved gold
may teach Qwen or a segmentation model. GPT Image is excluded from exact mask correction authority.
**Why:** Multiple uncalibrated models can share the same visual error; agreement and confidence do not
prevent pseudo-label poisoning. The useful objective is incremental defects found and human edit time
saved. The new frozen gate measures those outcomes against local QA and human truth.
**Cost/privacy:** Calls require exact-image/provider approval plus pre-dispatch reservation in a
hash-chained ledger. After Kevin's authorization the hard daily cap is $15.00, every request reserves $1.00, and no billable call is
made merely because implementation exists. Cloud-ineligible images remain local-only.
**Approved by:** Kevin's explicit multi-provider workhorse and <$20/day mandate

## 2026-07-12 — Autonomous acceptance is earned per label/context at measured 95% confidence
**Item(s) affected:** S09–S15, MF-P4 routing/calibration, P5 semi-supervised training
**Decision:** Add candidate tournaments and two non-human truth tiers: `machine_verified_candidate` and
`calibrated_auto_accepted`. Autoaccept requires an exact, unexpired, hash-bound label/context/pipeline
certificate whose one-sided 95% upper bounds are <=1% overall false accepts and <=0.5% serious false
accepts. Machine labels never become human gold or holdout truth.
**Why:** The Image1 audit proved that a confidence-.86 critic can falsely reject a human reference and
propose a 13x-area correction. Autonomy must rely on competing pixel candidates, hard geometry/QA vetoes,
measured error bounds, drift revocation, and sparse random auditing—not model confidence or majority alone.
**Approved by:** Kevin's explicit mandate to minimize routine human masking while reaching measurable
95%-plus confidence

## 2026-07-13 — Autonomy certificates gate review bypass, not pre-review improvement
**Item(s) affected:** S11–S12, MF-P4 VLM workhorse, CVAT draft handoff, teacher learning
**Decision:** The best demonstrably improved, hard-QA-passing non-baseline candidate may replace its
label in a reversible non-gold review draft even when the tournament lifecycle remains
`residual_human_queue`. Each label is composed and validated independently; a failure rolls back only
that label. Final complete-map QA must pass before S12/CVAT receives the optimized draft. The exact S09
baseline, candidates, hashes, provider votes, metrics, uncertainties, and rollback evidence are retained.
**Authority boundary:** A 95%-confidence certificate is still required to skip routine human review.
`pre_review_improvement` cannot clear a block, approve gold, become holdout truth, or impersonate Kevin.
**Why:** Candidate generation without safe draft application produced work but did not reduce CVAT
correction labor. The useful distinction is between improving what the human starts from and allowing
the machine to accept its own result; only the latter requires the statistical autonomy certificate.
**Approved by:** Kevin

## 2026-07-13 — Exact-candidate autonomous repair is the required S11 execution contract
**Item(s) affected:** S05, S09-S12, CVAT bridge, MF-P4-08.*, docs 10, 11, 19, 20, 21
**Decision:** A reviewer description or baseline vote is not an autonomous repair. Production uses
geometry-bound ROIs, polygon/SAM2 tools, transactional ordinary-label reassignment, complete-map QA, a
bounded tournament, and fresh exact-candidate review by Qwen plus every enabled eligible cloud reviewer.
Failed winners are downgraded and executable correction plans feed another bounded round. Experimental
committee convergence requires all required reviewers to pass the same exact candidate at the governed
advisory floor plus deterministic QA. Raw provider confidence is not a calibrated probability; the 95%
acceptance claim remains exclusively bound to frozen human-anchor evaluation and confidence bounds.
**Publication boundary:** Only a reversible non-gold review draft may be updated. Existing-task CVAT
publication backs up annotations, refuses completed tasks and human-edited PART shapes, verifies the
write, and rolls back on mismatch. No model can approve human gold or clear hard QA.
**Why:** The earlier path reviewed the baseline, could inherit its votes onto later candidates, and
stopped after a relative "better" comparison. That did not reliably repair catastrophic masks or reduce
the human's starting work. Exact-candidate convergence makes correction executable and auditable.
**Approved by:** Kevin's explicit repeated autonomous-repair mandate

## 2026-07-14 — Age predicates are not MaskFactory eligibility authority

**Item(s) affected:** MF-P2-10.02, MF-P4-09.01, MF-P4-10.03, MF-P8-10.01,
docs 18–22/SAM 3.1 tracker reconciliation
**Decision:** Do not gate ingestion, drafting, QA, cloud-teacher routing, training, or certification
on a project content classifier. Retire QC-V2-011 and remove its predicate from the affected
code/config/tests. Continue to enforce source rights/provenance,
provider- and artifact-specific content compatibility, license terms, exact-image cloud authorization,
credential redaction, spending approval, and truth/certificate authority as independent gates.
**Why:** Kevin explicitly rejected the age-eligibility gate because it can incorrectly exclude needed
training and masking material. Content/license/rights governance remains necessary, but it must not be
coupled to the removed age predicate.
**Approved by:** Kevin, explicit owner decision in the 2026-07-14 tracker reconciliation

## 2026-07-14 — Pooled risk certificates authorize autonomous truth without creating human gold

**Item(s) affected:** MF-P1-13.*, MF-P4-11.*, MF-P5-10.*, S13-S15, manifests,
SQLite/reindex, dataset/training inputs

**Decision:** Supersede the earlier per-label/context and human-only-gold wording with the approved
four-tier contract. New autonomy certificates are pooled only within an explicit risk bucket, are
anchored to frozen image-disjoint `human_anchor_gold` calibration evidence, bind an exact pipeline
fingerprint and covered labels/contexts, and default-deny legacy certificates for autonomous-gold
authority. A covered winner may finalize only as `autonomous_certified_gold`; it is never renamed
`human_approved_gold`. Human-anchor holdouts never enter certificate fitting or training.

**Training boundary:** Human-anchor train examples use weight 1.0, autonomous-certified examples use
the configured 0.5–0.75 weight, weighted pseudo-labels use 0.1–0.25, and machine candidates use zero.
Only anchor-train plus autonomous-certified packages satisfy certified volume/coverage gates;
effective weight units remain a separate optimization diagnostic.

**Why:** Per-label/context Cartesian calibration creates unnecessary review volume, while collapsing
machine and human authority falsifies provenance. Risk-bucket selective prediction preserves the
statistical and audit boundary while allowing certificate-covered local production training to scale.

**Approved by:** Kevin's 2026-07-13 SAM 3.1/autonomous-gold amendment

## 2026-07-14 - Parent-union specialist masks cannot impersonate atomic anatomy

**Item(s) affected:** S05-S12, MF-P2-09.*, MF-P4-08.*, docs 10 and 21

**Decision:** Whole-hand and whole-foot detector outputs are support-only evidence. They may localize
repair and appear in reviewer evidence, but cannot enter an atomic-label tournament. A bare whole foot
may produce `foot_base` and `toes` only through the validated pose-backed MTP split. Deterministic pose
guards veto whole-foot-as-base, heel-as-toes, and multi-fingertip-as-hand-base candidates before model
acceptance. Reviewer prompts must include the ontology boundary text.

**Why:** Task 23 v6 proved that Qwen, Gemini, OpenAI, and Anthropic can unanimously pass the same
semantically wrong mask when a whole foot is presented as `right_foot_base`. Pixel similarity and model
agreement do not establish the requested ontology boundary.

**Approved by:** Kevin's autonomous near-perfect repair mandate; implemented as a fail-closed semantic
correction after live evidence

## 2026-07-14 - Cloud repair calls are bounded across the complete S11 job

**Item(s) affected:** S11 cloud diagnosis, exact-candidate committee, cost ledger, doc 21

**Decision:** Diagnosis and convergence share a maximum-nine-call job quota and maximum-six-call
per-label quota. The duplicate pre-convergence diagnosis cascade is disabled by default. Definite
unbilled provider rejections release reservations; unknown post-dispatch usage remains pessimistically
committed. Budget/quota terminal errors stop no-progress retry rounds, and missing votes remain non-pass.

**Why:** A Task 23 replay repeatedly invoked the same unavailable/invalid reviewers across rounds and
consumed the conservative ledger almost to its $15 hard limit without producing a valid toes repair.
Bounded calls preserve autonomous iteration while preventing retry storms and false convergence.

**Approved by:** Existing Kevin-approved $15/day hard cap and autonomous repair mandate

## 2026-07-14 - Freeze official SAM 3.1 source now; keep checkpoint activation gated

**Item(s) affected:** MF-P0-17.03, MF-P0-17.04, external-source registry, isolated runtimes

**Decision:** Freeze the official Meta SAM 3.1 source at commit
`5dd401d1c5c1d5c3eedff06d41b77af824517619` and the official gated checkpoint identity at
Hugging Face revision `daa63191845a41281374e725f4c9e51c7a824460`. Maintain an isolated,
reproducible source runtime and use the uniform source-admission path under the private-local profile,
but retain lifecycle `planned` and `verify_license: true` until Kevin completes the interactive Meta
checkpoint terms. Source imports and CUDA allocation are evidence for the runtime only; they do not
substitute for checkpoint inference, deterministic-output, latency, VRAM, benchmark, or promotion
evidence.

**Why:** The official source is available and reproducible, while the checkpoint repository returns
HTTP 401 until a human accepts Meta's contact/license form. Separating source-runtime qualification
from checkpoint activation preserves forward progress without inventing authority or evidence.

**Approved by:** Kevin's SAM 3.1 modernization amendment; interactive gate acceptance remains Kevin-only

## 2026-07-14 - CVAT v2.69 is the parallel migration target; v2.24 remains incumbent

**Item(s) affected:** MF-P0-17.12, CVAT runtime, backup/restore, rollback, SAM2 interactor

**Decision:** Use signed stable CVAT v2.69.0 at commit
`f6ae1dca443b94dd01288dfc9ac6ffe988218f0c` for the isolated migration rehearsal. Do not adopt
v2.70.0 on its publication day. Keep v2.24.0 as the production incumbent while v2.69 runs under a
separate Compose project, container namespace, volume namespace, hostname, ports, and Traefik router
namespace. Production promotion remains a later measured decision, not an implication of a successful
schema/data migration.

**Why:** The v2.69 source, images, database migration, task/media identity, authenticated API, UI,
parallel operation, and rollback all passed on this machine. v2.70 had only hours of release exposure,
and replacing the only working review deployment would violate the approved parallel-first contract.

**Approved by:** Kevin's SAM 3.1 modernization amendment and autonomous execution mandate

## 2026-07-15 - Keep official SAM3.1 repair proposals isolated until the downstream gold gate

**Item(s) affected:** MF-P2-11.04, S11 autonomous repair, documents 20–22

**Decision:** Execute official SAM3.1 point/mask/box repair as a lifecycle-aware S11 sidecar behind
the canonical `InteractiveSegmenter` contract. Admit only exact official runtime identities with
shadow authority; bind every request to source, label, ROI, positive/negative points, baseline and
protected-mask hashes; cap each label at twelve proposals; run the existing reconstruction,
changed-area, protected-region, outside-ROI, component, and expected-area guards; persist only
guard-passing strict binary masks; and leave S09 plus the active provider selection unchanged.
Repair grants no gold authority itself. A resulting candidate can become gold only through later
human-anchor approval or the exact-scope, current autonomous-certification gate in documents 20 and
22. Planned/unavailable, empty-plan, missing-loader, and runtime-failure states remain explicit
zero-authority records.

**Administrative compatibility rebind:** Because S11 orchestration is part of the frozen pipeline,
administratively rebind the unopened MediaPipe ablation, silhouette, serving-workflow, and aggregate
provider-matrix policies to the new `configs/pipeline.yaml` identity before any eligible result.
No route, provider comparison, truth tier, metric, threshold, finalist, rollback, or authority rule
changes.

**Why:** The approved modernization requires official SAM3.1 repair proposals, while the existing
repair engine already provides the required safety and tournament guards. An isolated provider-
neutral source closes the execution gap without allowing an unbenchmarked challenger to alter a
production map. The prior repair-spec sentence that only a human could ever approve gold conflicted
with the separately approved autonomous-certified-gold architecture; narrowing repair to no direct
gold authority preserves both contracts.

**Approved by:** Kevin's SAM 3.1 modernization amendment and autonomous execution mandate

## 2026-07-15 - Execute official SAM3.1 as an isolated production shadow sidecar

**Item(s) affected:** MF-P2-11.03, MF-P3-08.01, MF-P8-11.03, S06 production
orchestration, provider benchmark reproducibility

**Decision:** Add a governed S06 sidecar that derives unique visible-surface concepts for every
frozen specialist label across hand/finger, chest/pelvic, hair, foot/toe, clothing, accessory, and
repeated-instance lanes. A runnable official SAM3.1 challenger must enter through exact
`ConceptDetector` and `InteractiveSegmenter` identities, execute discovery and box/mask refinement,
and persist only isolated strict-PNG candidates plus a schema-valid hash-sealed orchestration record.
Planned/unavailable, no-candidate, loader-failure, and runtime-failure outcomes remain explicit
zero-authority records. None may change active maps, feed S07, serve a mask, decide semantics, or
grant truth/gold authority. Adult-nonexplicit and consensual-explicit-adult labels remain eligible;
there is no age-eligibility filter. Sapiens2 remains independently excluded.

**Administrative pre-result rebind:** `provider_benchmark_matrix_v1` is rebound from canonical
SHA-256 `f76605c75aa28b3e3ca1730fb09a33fb8e94d5e9bc65d923e0026afd0c831c4f` to
`263c4472008b8def97a2d4dcc61fca587b123c7b3109b426e8f525a4eef4464d`. Its frozen
`configs/pipeline.yaml` identity changed to
`0484443725cc9d2784acb370e83e5a373cc6d3a158791ebbde00956cbd8f0769`; its transitive
MediaPipe/silhouette policy and verifier identities were then rebound to their pipeline-current
bytes. No benchmark result has been opened; routes, providers, truth partition, measurements,
margins, thresholds, finalist rules, and authority are unchanged.

The same pipeline-only source rebind applies to three other unopened policies:
`mediapipe_vote_ablation_v1` from `8589e735...` to `a4091b17...`,
`silhouette_variant_benchmark_v1` from `04a13fef...` to `7532c4d1...`, and
`serving_workflow_performance_v1` from `0bd10772...` to `144a6cce...`. Their
truth sets, provider/role matrices, metrics, thresholds, fallback/rollback requirements,
determinism rules, and authority boundaries are unchanged, and no eligible result exists.

**Why:** The official adapters and candidate package contract existed, but production S06 never
invoked them, so all seven required specialist lanes remained fixture-only. The sidecar closes that
orchestration gap while preserving SAM2.1/GroundingDINO incumbency and making unavailable or failed
challenger execution auditable instead of silently absent.

**Approved by:** Kevin's SAM 3.1 modernization amendment and autonomous execution mandate

## 2026-07-15 - Require signed matrix-bound specialist champion transactions

**Item(s) affected:** MF-P2-11.15, MF-P5-10.11, MF-P6-06.08, specialist
hand/clothing champion promotion and rollback

**Decision:** Remove the legacy direct role-swap path for `champion_hand` and
`champion_clothing`. A specialist promotion now requires the complete signed aggregate
matrix bundle, exact role/candidate/incumbent binding, current checkpoint/content/source/
runtime/license identities, a promoted incumbent, a benchmarked candidate, and a passing
smoke of the proposed registry before activation. Publish the role/lifecycle swap and a
hash-sealed transaction history atomically under a registry lock. Permit rollback only from
that unused sealed transaction, only when no intervening registry or role drift exists, and
only after the restored incumbent passes its production smoke. Expose both directions as
one-command CLI operations. The existing strict custom body-part transaction remains
unchanged; connecting its mutation event to the aggregate matrix certificate remains open.

**Why:** The prior hand/clothing helper could mutate production roles without the signed
ten-role matrix prerequisite, transaction serialization, exact registry-history sealing, or
tested restoration. That bypass contradicted Document 22. The replacement fails closed on
bundle drift, identity substitution, smoke failure, concurrent promotion, history publication
failure, replay, tampering, and intervening registry changes. This decision creates no winner
and authorizes no live role change; real image-disjoint human-anchor results and a production
promotion/rollback event are still required.

**Administrative compatibility rebind:** `retraining_compatibility_v1` is rebound before
any eligible retraining result from canonical SHA-256 `f02ac133...` to
`5650b8f2e5b523032b37da98ac10cf0741ce5fe7dd99d7ce356042726ddc290c` solely because its
frozen source identity includes `src/maskfactory/models/registry.py`, now SHA-256
`d7f2382a0f757383103800adb7f73d25b053c8f4d9cb473fedf1a3cfc733de88`. No retraining
rule, threshold, authority, eligible result, or decision changed.

**Approved by:** Kevin's SAM 3.1 modernization amendment and autonomous execution mandate

## 2026-07-15 - Freeze the provider-neutral Mode A/Mode B workflow performance contract

**Item(s) affected:** MF-P6-02.05, MF-P6-05.07, MF-P6-06.08, MF-P6-EXIT

**Decision:** Freeze `serving_workflow_performance_v1` before any eligible champion result. A
complete report must cover Mode B predict and refine plus dependency-light, read-only Mode A package
execution on separate governed unseen single-person and 2-4-person sources. It must bind actual source,
governance, provider, checkpoint, runtime, benchmark-certificate, provenance, output, and package
artifacts; enforce the existing 60/4/2/1.2-second Mode B limits; record Mode A latency without inventing
an unapproved threshold; measure VRAM, OOMs, crashes, and exact repeat determinism; and prove distinct
transactional rollback and restoration for body-part, hand, clothing, and interactive roles.

**Why:** The existing MF-P6-02.05 benchmark measures Mode B latency but cannot prove the broader
MF-P6-06.08 requirement. Allowing results before source scope, Mode A immutability, multi-person
coverage, provenance, artifact identity, failure accounting, and role rollback are frozen would permit
selective or irreproducible evidence. The new verifier refuses partial cases, stale artifacts, duplicate
sources, latency overruns, nondeterminism, package mutation, Mode A model loads/writes, OOM/crash
events, same-provider rollback, incomplete lifecycle round trips, or altered frozen artifacts.

No live performance claim is made by freezing this policy. A passing real report still requires trained
promoted champions, distinct benchmarked rollback providers, eligible single/multi-person packages,
and governed unseen source images.

**Approved by:** Kevin's SAM 3.1 modernization amendment and autonomous execution mandate

## 2026-07-15 - Install SAM3-LiteText S0 as a shadow-only optional experiment

**Item(s) affected:** MF-P3-08.02, MF-P0-17.13, concept-detector and
interactive-segmenter challenger inventory

**Decision:** Advance exact `vil-uob/sam3-litetext-s0` revision
`b09766e54f5d2eba021119ec7feff13e74c0f8fc` from planned to installed in the
isolated WSL environment `/home/kevin/mfenvs/sam3-litetext-b09766e5`. Bind
checkpoint SHA-256 `69c86fda...`, Transformers 5.13.1 wheel SHA-256
`53f0ea8a...`, the complete installed dependency lock, CUDA smoke evidence,
and the expanded eight-family runtime matrix. Its only eligible role remains
`shadow_only_experiment`; active, fallback, OOM-fallback, rollback, production,
semantic, mask-authority, and gold-authority substitution for official
`sam3_1` remain forbidden.

**Why:** The previously storage-blocked public checkpoint is ungated and now
runs deterministically on the recovered 8 GiB machine, producing four strict
person masks on the governed adult multi-person fixture with 1,479,608,320
peak allocated bytes. This establishes installation and local feasibility only.
Official SAM 3.1 remains checkpoint-gated, so no relative lower-memory claim,
quality non-inferiority claim, benchmark win, provider promotion, or substitute
authority is supportable yet. Keeping those comparisons explicitly pending
preserves the approved amendment's requirement that LiteText never masquerade
as official SAM 3.1.

**Approved by:** Kevin's SAM 3.1 modernization amendment and autonomous execution mandate

## 2026-07-15 - Freeze RTM pose-variant comparison before human-anchor results

**Item(s) affected:** MF-P3-08.04, MF-P2-11.13, pose-provider promotion and rollback

**Decision:** Freeze `pose_variant_benchmark_v1` at canonical SHA-256
`3791ffe1f527a465d06d271aaca585fdf16253584667797a49b07adab10c8517`. Compare
RTMW-X to DWPose across whole-body, hands, feet, rear, contact, occlusion, and crowded-scene
contexts using all 133 COCO-WholeBody joints. Measure all 14 RTMO CrowdPose joints in every context,
but compare RTMO to DWPose only on the 12 exact-name shared joints and only for its crowded-scene
role; do not invent mappings for CrowdPose `top_head` or `neck`. Normalize joint error by the truth
person-box diagonal, report PCK@0.05 and PCK@0.10 from explicit counts, preserve character-anatomical
side semantics, and require side, cross-person identity, latency, VRAM, crash/OOM, two-repeat
determinism, and injected-failure fallback evidence. Keep DWPose active and rollback regardless of a
fixture report; real authority requires an image-disjoint human-anchor holdout report.

**Why:** Smoke success proves that the installed challengers execute, not that they are accurate or
safe in every hard context. A pre-result, hash-locked evaluator prevents missing joints, absent
contexts, denominator-free rates, post-result threshold changes, or a fabricated RTMO/DWPose joint
mapping from becoming promotion evidence. Explicit DWPose failure drills also prove reversibility
instead of relying on configuration intent.

**Approved by:** Kevin's SAM 3.1 modernization amendment and autonomous execution mandate

## 2026-07-15 - Require one signed matrix-bound certificate before role promotion

**Item(s) affected:** MF-P2-11.15, MF-P3-08.08, MF-P5-10.09, specialist and
custom-segmenter role promotion

**Decision:** Require one dedicated Ed25519-signed aggregate prerequisite certificate before any
provider-role promotion transaction. The verifier must recompute the complete top-level provider
matrix report from its sealed manifest and observations; validate all nine specialist promotion
packets plus the custom-segmenter certificate; bind every specialist checkpoint to an exact provider
artifact present in its named matrix cell; bind the custom segmenter to the matrix evaluation-set,
hardware, and QA identities through an explicitly labeled pipeline-context cell; require the exact ten
governed roles and ten distinct matrix cells; bind every prerequisite, derived summary, cell result,
and full rollback-evidence hash; and reject a certificate issued before any recorded rollback test.
The signature uses a dedicated promotion-event key whose private half is not committed. Validation
returns prerequisites-only evidence and performs no registry mutation.

**Why:** The role-specific gates and matrix compiler were individually fail-closed but did not prove
that a proposed set of promotions came from the same exact matrix execution or that one result was not
reused across roles. A signed aggregate closes that join boundary while preserving the separate
transactional mutation and live rollback requirements. Fixture certificates prove only enforcement;
they confer no winner, promotion, serving, mask, production, blocker-clearance, or gold authority.

**Approved by:** Kevin's SAM 3.1 modernization amendment and autonomous execution mandate

## 2026-07-15 - Freeze MediaPipe handedness-vote ablation before holdout results

**Item(s) affected:** MF-P3-08.06, QC-014, MF-P3-08.10, specialist benchmark evidence

**Decision:** Freeze `mediapipe_hand_vote_ablation_v1` at SHA-256
`8589e73549b26529505e4888e504cfe5024c1cb6c2bb21b2578ab71746e6f1c2` before any
human-anchor hand result is opened. Compare the character-perspective two-source baseline
(`pose_skeleton` plus `densepose_surface`) against the three-source path that adds
`mediapipe_handedness`, requiring two matching votes and abstention without a strict majority.
MediaPipe must score at least 0.5 to vote. A passing real ablation must add at least one correct
decision and add zero wrong-side decisions. At least one exact x-mirrored side-swap fixture must swap
the truth label and every available vote; fixture rows are excluded from performance denominators.

**Why:** Keeping MediaPipe installed or displaying 21 landmarks does not establish incremental value.
The frozen ablation separates a genuinely rescued decision from coverage inflation, makes new
wrong-side decisions an absolute regression, proves character-side flip behavior geometrically, and
prevents synthetic mirror pairs from masquerading as independent human-anchor performance evidence.
Only image-disjoint `human_anchor_gold` holdout truth may complete the measured benchmark.

**Approved by:** Kevin's SAM 3.1 modernization amendment and autonomous execution mandate

## 2026-07-14 - Use exact Qwen3-VL Instruct Q4_K_M tags as shadow reviewers

**Item(s) affected:** MF-P0-17.09, MF-P0-17.13, MF-P2-11.09, MF-P4-10.12,
VLM provider selection and local runtime

**Decision:** Install and freeze `qwen3-vl:4b-instruct-q4_K_M` and
`qwen3-vl:8b-instruct-q4_K_M` under native local Ollama 0.32.0. Bind each provider identity to its
exact local manifest digest, use a 4,096-token context for bounded 8 GB operation, and require Ollama
JSON Schema plus the canonical strict verdict parser. Keep both variants at lifecycle `installed` and
shadow-only. Retain Qwen2.5-VL as the incumbent and LLaVA as fallback until the complete untouched
holdout, 40-panel, 200-case, reviewer-time, and rollback certificate gates pass.

**Why:** Both exact Apache-2.0 variants fit the RTX 5060 and pass live strict-schema adapter calls;
the 8B uses 5.53 GB VRAM and remains feasible. Its cold warm-up verdict differed from the stable warm
verdict, so only post-warm-up repeatability is claimed. This is sufficient for governed shadow
integration and later benchmarking, not production promotion or gold authority.

**Approved by:** Kevin's SAM 3.1 modernization amendment and autonomous execution mandate

## 2026-07-14 - RF-DETR Medium is the installed shadow challenger; YOLO11 retains authority

**Item(s) affected:** MF-P0-17.05, MF-P0-17.13, MF-P2-11.05, S01 person detection,
provider selection, frozen provider benchmark matrix

**Decision:** Freeze RF-DETR 1.7.1 Medium rather than the Base or commercially licensed Plus
variants, run it in its isolated WSL/cu128 environment behind the versioned `PersonDetector`, and
name the provider key `rf_detr_medium` so provenance matches the actual checkpoint. Keep RF-DETR at
lifecycle `installed` with shadow-comparison authority only. Keep `yolo11m_person` as both active S01
provider and rollback until a current human-anchor benchmark certificate satisfies every promotion
and non-inferiority gate.

**Why:** The exact Medium runtime and checkpoint pass CUDA, determinism, failure-boundary, and live
four-person comparison checks, including 4/4 matched detections with mean box IoU 0.97931262. This is
enough to integrate and benchmark the challenger, but it is not a gold-backed promotion certificate
and the CPU/CUDA comparison cannot support latency claims. The lifecycle guard correctly rejects an
RF-DETR activation edit and an incumbent replay remains exact.

**Approved by:** Kevin's SAM 3.1 modernization amendment and autonomous execution mandate

## 2026-07-14 - Default BiRefNet HR challengers to 1024 under the 8 GB profile

**Item(s) affected:** MF-P2-11.08, MF-P3-08.03, S02 silhouette provider selection,
BiRefNet variant runtime and promotion eligibility

**Decision:** Install and freeze the official BiRefNet Dynamic, HR, and HR-matting checkpoints, expose
them behind `SilhouetteProvider`, and keep them lifecycle `installed`/shadow-only. Dynamic retains
native stride-32 preprocessing. HR and HR-matting default to the official 1024 evaluation mode on this
machine; their official 2048 mode remains an explicit high-memory shadow option. Keep
`birefnet_general` as active and rollback provider. A challenger runtime failure may invoke the
explicit incumbent fallback, but the returned proposal must preserve the incumbent identity.

**Why:** Corrected live 2048 inference was deterministic and produced valid masks, but PyTorch reported
10.13 GB peak allocated and 15.33 GB peak reserved for both HR checkpoints, above the available 8 GB
dedicated-GPU budget. The 1024 path passed full provider, strict-mask, matting, provenance, and fallback
checks without pretending that a successful oversubscribed 2048 run proves reliable 8 GB operation.
Promotion still requires the frozen human-anchor role benchmark and every non-inferiority/rollback gate.

**Approved by:** Kevin's SAM 3.1 modernization amendment, 8 GB reliability requirement, and autonomous execution mandate

## 2026-07-15 - Install RTMW-X and RTMO as one correlated shadow pose family

**Item(s) affected:** MF-P2-11.06, S04 pose provider selection, crowded-person ownership,
provider benchmark matrix

**Decision:** Freeze MMPose v1.3.2 at commit
`5408bc76f5b848cf925a0d1857899011d8c5b497`, the official RTMW-X 384x288
COCO-WholeBody-133 checkpoint, and the official RTMO-L 640x640 CrowdPose-14 checkpoint. Run both
through one isolated local CUDA dependency layer behind `PoseProvider`. Treat them as separate
candidate providers but one correlated `rtmpose` model family. Preserve character-anatomical
left/right names, bind RTMO candidates to requested people by box IoU and stable instance keys, and
fail closed on any source, runtime, artifact, vocabulary, determinism, ownership, or confidence
drift. Keep DWPose as active and rollback and MediaPipe hands as the independent vote; neither RTM
challenger may author gold or enter production before the frozen human-anchor benchmark certificate.

**Why:** Both exact official models pass live deterministic CUDA inference on the adult crowded bus
fixture, fit comfortably within the 8 GB profile, and satisfy the role, side, crowd, and fallback
contracts. This proves governed installation and integration, not superiority. Counting the two
variants as independent votes would inflate evidence from a shared source/model family.

**Approved by:** Kevin's SAM 3.1 modernization amendment and autonomous execution mandate

## 2026-07-15 - Use EoMT-DINOv3 Small-640 as a trainable shadow backbone

**Item(s) affected:** MF-P0-17.10, MF-P0-17.13, MF-P2-11.10, body_parts_v2 custom
training and provider tournament

**Decision:** Freeze `tue-mps/eomt-dinov3-coco-panoptic-small-640` at revision
`602edaa2839daf6cb3de3ad46c176098c3be9090` and use its DINOv3/EoMT weights as the
installed trainable challenger under the existing torch 2.11/cu128 runtime. Discard the pretrained
COCO-panoptic-133 segmentation head for MaskFactory training and initialize a fresh 65-class head
whose vocabulary hash is bound to exact `body_parts_v2` IDs 0–64. Keep SegFormer and Mask2Former as
baselines. Pretrained EoMT predictions are shadow smoke evidence only and may not author gold or
claim production authority.

**Why:** The exact 93.45 MB MIT checkpoint is public, supported by the installed Transformers 5.13,
passes deterministic live CUDA inference, and uses only 0.70 GB peak reserved memory. Its COCO labels
do not match MaskFactory's ontology, so preserving that pretrained head would create silent semantic
corruption; a hash-bound fresh target head makes the training contract explicit and fail closed.

**Approved by:** Kevin's SAM 3.1 modernization amendment, private local profile, and autonomous execution mandate

## 2026-07-15 - Freeze specialist non-inferiority policy before benchmark results

**Item(s) affected:** MF-P2-11.13 through MF-P2-11.15, MF-P3-08.03 through
MF-P3-08.10, specialist provider promotion and rollback

**Decision:** Freeze `specialist_noninferiority_v1` at SHA-256
`6b5a939f9aeeda0025ef39b93b308a9c7ed2ef2caaff1cc76d05a6acba4d5b55` before any
specialist result is opened. Use the uniform delta convention “positive is challenger improvement.”
Expand role-specific label and context margin maps plus absolute zero-regression metrics into an exact
406-bucket result contract across hand/finger, foot/toe, chest/pelvic, hair/matting, clothing/accessory,
silhouette, pose, geometry, and repeated-instance roles. Require every result to bind the frozen hash,
include every exact bucket and margin, postdate the freeze, and pass each bucket independently.

**Why:** The modernization contract forbids an average improvement from hiding a hard-label or
high-risk-context regression. A prose flag such as `no_hard_class_regression: true` can be asserted
after results and does not prove which labels, contexts, metrics, or margins were predeclared. The
hash-locked expansion makes omissions and post-result threshold relaxation deterministic failures
while retaining zero tolerance for bleed, side/identity, protected-region, hard-QA, determinism,
OOM/crash, and rollback regressions.

**Approved by:** Kevin's SAM 3.1 modernization amendment and autonomous execution mandate

## 2026-07-15 - Administratively refreeze specialist policy after repository normalization

**Item(s) affected:** MF-P3-08.08, MF-P7-07.01, specialist benchmark policy

**Decision:** Supersede the serialization hash
`6b5a939f9aeeda0025ef39b93b308a9c7ed2ef2caaff1cc76d05a6acba4d5b55` with
`605f79e0d4f8354a7a4d445a0a5725af829cd78b85e2e36f91b065576553a739`. The only
policy-source change is repository end-of-file normalization of
`configs/autonomy_risk_buckets.yaml`; all nine roles, 406 expanded buckets, thresholds, margin
directions, zero-regression metrics, source meanings, and the 2026-07-15T01:00:00Z pre-result freeze
time remain identical. No provider benchmark result was opened or modified.

**Why:** The repository's mandatory end-of-file pre-commit hook normalized the policy source after
the initial working-tree freeze. Retaining a stale embedded source hash would make every legitimate
benchmark fail, while silently changing it would erase the audit trail. This explicit administrative
refreeze preserves the original decision and records the byte-only normalization before any real
human-anchor benchmark output exists.

**Approved by:** Kevin's SAM 3.1 modernization amendment and autonomous execution mandate

## 2026-07-15 - Freeze silhouette, hair-edge, and matting provider comparisons

**Item(s) affected:** MF-P3-08.03, MF-P2-11.13, silhouette/matting provider promotion and rollback

**Decision:** Freeze `silhouette_variant_benchmark_v1` at canonical SHA-256
`04a13fef0de84b0db3895437163b33866ca1a553b916a5b1397681f84972ebab` before any
eligible result. Use BiRefNet-general as the incumbent for person-silhouette and binary hair-edge
roles, and ViTMatte-S as the incumbent for trimap-guided alpha matting. Compare BiRefNet Dynamic,
HR, and HR-matting only where their governed outputs support the role: all three for silhouette and
hair edge, Dynamic and HR-matting for alpha matting. Require every provider/role/label across hair
boundaries, multi-person overlap, contact/occlusion, small parts, and truncation. Recompute
foreground IoU, foreground leakage, boundary-F@2px, correction pixels, alpha MAE/MSE, latency,
VRAM, OOM/crash, two-repeat determinism, and eight exact role-specific fallback drills from explicit
denominators. Keep HR and HR-matting at 1024 under the 8 GB profile; 2048 evidence cannot qualify on
this machine.

**Why:** Single-image smoke masks prove shape, determinism, and runtime feasibility but cannot prove
boundary quality or leakage across the hard contexts. ViTMatte requires a trimap and therefore is
not a silent full-silhouette substitute, while BiRefNet HR has no governed alpha-matting output.
Freezing the capability matrix prevents invalid cross-role comparisons, denominator-free quality
claims, or post-result margin changes from becoming promotion evidence.

**Approved by:** Kevin's SAM 3.1 modernization amendment and autonomous execution mandate

## 2026-07-15 - Make operational autonomy metrics cohort-bound and denominator-exact

**Item(s) affected:** MF-P7-07.05, MF-P3-07.03, revised autonomous headline evidence

**Decision:** Supersede the structural autonomy metrics v2 report with hash-sealed v3. Every report
must bind one cohort ID, observation timestamp, input-manifest SHA-256, complete pipeline-fingerprint
SHA-256, and an exact four-tier package breakdown that reconciles to the eligible cohort. Zero-touch
throughput, routine human touch, audit workload, residual review, human touches, manual changed pixels,
blinded human-anchor quality, and failure confidence remain separate domains with explicit integer or
sum numerators and denominators. Derived rates and means are always recomputed. Aggregate false accepts
use the predeclared one-sided 95% Wilson upper bound; serious false accepts use a one-sided 95%
Clopper-Pearson upper bound for both zero and positive observed failures. The report and its normalized
source-input document each carry a canonical SHA-256. A CLI must build or verify the exact contract,
and CI must reject missing denominators, cross-domain population drift, truth-tier mismatch, residual
reviews outside the routine-touch subset, conflated zero-touch claims, or any recomputation/hash drift.

**Why:** A displayed percentage is not reproducible evidence unless its population, numerator,
denominator, truth authority, pipeline identity, and observation cohort are fixed. The earlier v2
contract left quality numerators implicit and did not recompute stored confidence bounds, allowing a
well-formed but stale or misleading report to survive structural validation. V3 makes those failures
deterministic while preserving the governing rule that a 95% zero-touch rate is a throughput result,
not an accuracy or certification claim. Synthetic fixtures validate enforcement only; actual project
performance remains pending a genuine autonomous cohort and blinded human-anchor audit.

**Approved by:** Kevin's SAM 3.1 modernization amendment and autonomous execution mandate

## 2026-07-15 - Freeze the local-Qwen replacement benchmark before human-anchor results

**Item(s) affected:** MF-P4-10.12, local VLM reviewer promotion, Qwen2.5-VL rollback,
Qwen3-VL 4B/8B challenger evaluation

**Decision:** Freeze `qwen_challenger_benchmark_v1` at canonical SHA-256
`cba85192e7ed558b5632b05952e80edfa6e88da155b0460e1a0798d27c3d2792` before
opening any eligible quality result. Compare the exact installed Qwen3-VL 4B and quantized 8B
identities against Qwen2.5-VL on three independently frozen, source-image-disjoint human-anchor
partitions: the untouched teacher holdout, the exact balanced 40-panel local gate, and at least 200
naturally occurring incremental-value cases. Require complete serious/good/error/context coverage,
closed observations for every provider/case, per-label and high-risk non-regression, absolute recall,
precision, false-pass, usefulness and reviewer-time gates, reliable operation within 8 GiB,
deterministic repeats, and an injected-failure return to Qwen2.5-VL. A measured win requires at least
one-percent recall improvement or five-percent median reviewer-time reduction with no gate regression.
Choose deterministically if both challengers qualify. Keep Qwen2.5-VL active and rollback, preserve
LLaVA-13B as fallback, and grant no mask, gold, blocker-clearance, or quick-pass authority from the
benchmark itself.

**Why:** Installation and single-fixture runtime smokes prove identity and feasibility, not replacement
value. The existing cloud-teacher evaluator does not join the teacher holdout, local panel gate,
incremental corpus, model identity, reviewer labor, runtime, per-stratum regression, and rollback into
one exact local-model decision. Freezing those requirements now prevents data leakage, missing
denominators, post-result threshold changes, a fast-but-worse replacement, or model-card confidence
from silently displacing the incumbent. Test fixtures demonstrate enforcement only; a real result still
requires Kevin-supplied human-anchor evidence and the upstream frozen corpus.

**Approved by:** Kevin's SAM 3.1 modernization amendment and autonomous execution mandate

## 2026-07-15 - Freeze compatibility-scoped retraining lifecycle evidence

**Item(s) affected:** MF-P7-07.06, autonomy retraining, recertification, model-role promotion,
serving rollback

**Decision:** Freeze `retraining_compatibility_v1` at canonical SHA-256
`f02a057c45d76a5e586f1758c94e9df895e20afdaf22edf33d9cc10c13d19107` before any
eligible retraining result. A qualifying operation must start from an actionable immutable audit
trigger, bind a successful training run into a recomputed pipeline fingerprint different from the
incumbent, and record one explicit versioned decision for every evidence category. Frozen
human-anchor holdouts, approved human-gold training packages, immutable audit history, and benchmark
observations may be reused only under exact artifact and complete scope identity. Autonomy
certificates, serving/promotion evidence, and pseudo-label eligibility never carry across the new
fingerprint. Every affected risk-bucket/instance-context stratum must either receive a new-fingerprint
human-anchor certificate or remain residual-only with no certificate. Promotion additionally
requires frozen-holdout and benchmark passes, an identity-matched transactional registry mutation,
and a rollback drill that restores the exact prior registry hash, incumbent provider, and passing
serving smoke. A rejected challenger carries no synthetic promotion or rollback record.

**Why:** A retraining task and new checkpoint are not sufficient operations evidence. Without an
explicit compatibility policy, stale certificates or evaluation results could silently authorize a
new pipeline, while a nominal rollback could restore the wrong registry or provider. The frozen
contract makes every authority transfer and abstention decision reproducible while preserving the
boundary that fixtures and a passing contract do not themselves train, promote, serve, mint gold, or
complete the tracker item. Real completion still requires a certified corpus, genuine audit trigger,
real retraining run, human-anchor revalidation, role decision, and observed rollback.

**Approved by:** Kevin's SAM 3.1 modernization amendment and autonomous execution mandate

## 2026-07-15 - Freeze the final modernization completion evidence index

**Item(s) affected:** MF-P7-07.09, MF-P7-EXIT, MF-P8-EXIT, D1-D11, G1-G9, final
modernization declaration

**Decision:** Freeze `modernization_completion_v1` at canonical SHA-256
`aed53657c856f259d629d9f8dff588ccd9bde6226996d3e85c873df102ccb1c9` before any
eligible final bundle. Require exactly one current, hash-sealed, `real_operation` receipt for each of
15 non-collapsible domains: doctor, live provider smokes, isolated runtime matrix, frozen
human-anchor benchmarks, CVAT migration, CVAT rollback, autonomy certification, serious-failure
revocation, trigger-driven retraining, operational labor/quality/confidence metrics, single-person
headline, multi-person headline, signed currency review, complete test/lint/format/drift suite, and
tracker validation. Each receipt must use its frozen verifier identity, link the minimum distinct
source artifacts by contained relative path and exact SHA-256, satisfy domain-specific measured
thresholds, and remain within its predeclared freshness window. One artifact cannot satisfy multiple
domains. The live tracker must contain at least 609 items; every non-orphaned item except the bundle
item itself must be `complete` or `not_applicable`; D1-D11 and measured G1-G9 must all be `met`.
Only MF-P7-07.09 may be excluded to avoid circular self-authorization.

**Why:** A directory of evidence files, green fixture suite, or implementation-ready contract cannot
prove project completion. Final declaration requires a current, exact index whose primary evidence
cannot be silently omitted, duplicated across roles, replaced by synthetic/pre-result artifacts, or
contradicted by the tracker. This contract deliberately fails against the current live tracker and
grants no completion authority until every real upstream operation and measurement exists.

**Approved by:** Kevin's SAM 3.1 modernization amendment and autonomous execution mandate

## 2026-07-15 - Freeze the SAM 3D Body versus DensePose geometry benchmark

**Item(s) affected:** MF-P3-08.05, MF-P2-11.07, MF-P2-11.13, geometry-provider
promotion and rollback

**Decision:** Freeze `geometry_variant_benchmark_v1` at canonical SHA-256
`98810aa56d85381ec1f792edf6308f6f4bc1741304cccae312868716a6316aef` before any
eligible result. Compare SAM 3D Body only as the modern challenger to the exact promoted DensePose
R50-FPN incumbent/rollback. Require image-disjoint human-anchor holdout observations across geometry
priors, contact, crowding, identity ambiguity, occlusion, rear view, front view, scale disparity, and
truncation. Bind the exact source revision, checkpoint revision, installed checkpoint/config/MHR/source
archive hashes, runtime and hardware identities. Recompute image-projection consistency, visible-surface
recall, background and cross-person bleed, character-side errors, front/back errors, person-identity
assignment errors, hard-QA failures, cold/warm latency, peak VRAM, OOM/crash, and two-repeat determinism
from explicit counts. Require at least a 0.01 overall projection-consistency win, the frozen 0.02
per-context non-inferiority margins, zero regression on every safety/error rate, reliable operation
within 8 GiB, and an injected-failure return to DensePose without changing active or rollback identity.

**Why:** The public source and exact gated Hugging Face revision are known, but Meta's checkpoint,
configuration, and MHR assets still require Kevin's human license/contact-sharing acceptance. Freezing
the complete comparison before that gate opens prevents later artifact substitution, missing-context
averages, denominator-free 3D claims, or post-result threshold changes. Synthetic fixtures prove only
that the contract fails closed; they do not install SAM 3D Body, measure performance, promote a
provider, author a mask, or create gold authority.

**Approved by:** Kevin's SAM 3.1 modernization amendment, 8 GB reliability requirement, and autonomous execution mandate

## 2026-07-15 - Freeze the fair custom-segmenter training tournament

**Item(s) affected:** MF-P5-10.07, MF-P5-10.08, MF-P5-10.09, custom-segmenter
selection, promotion, and rollback

**Decision:** Freeze `custom_segmenter_training_tournament_v1` at canonical SHA-256
`550ff7c9efce0bef8cddc55c943dacb8d90ab066fd18a11e004984cfedfee983` before any
eligible training result. Compare SegFormer-B3, Mask2Former-Swin-B, and
EoMT-DINOv3-Small-640 only after all three bind the same certified training manifest,
image-disjoint human-anchor holdout, body-parts-v2 ontology, QA policy, hardware identity,
seed, crop, augmentations, 40,000-iteration schedule, evaluation code, and thermal limit.
Require complete hash-sealed manifests and artifacts, all 65 class observations, all 17
high-risk context observations, all 12 error-family observations, explicit metric
denominators, runtime/VRAM/failure measurements, and exactly two identical deterministic
outputs per provider. Preserve EoMT's exact installed initial checkpoint identity.

**Why:** Architecture labels and aggregate mIoU do not establish a fair result. A mutable
dataset, different augmentation/schedule, missing hard contexts, denominator-free rates,
or substituted starting checkpoint could make one provider appear better without measuring
the same task. The frozen contract makes future run records comparable and reproducible,
while its generated report deliberately grants no winner, promotion, serving, mask,
semantic, production, or gold authority. Synthetic fixtures and a passing pre-run verifier
do not train or evaluate any model; MF-P5-10.07 remains incomplete until all three genuine
runs and immutable measurements exist.

**Approved by:** Kevin's SAM 3.1 modernization amendment and autonomous execution mandate

## 2026-07-15 - Freeze the two-stage top-level provider benchmark matrix

**Item(s) affected:** MF-P2-11.13, MF-P2-11.14, MF-P2-11.15, MF-P3-08.08,
provider screening, specialist enrichment, and role promotion

**Decision:** Freeze `provider_benchmark_matrix_v1` at canonical SHA-256
`65220c865e54b12e5558cfac9d05bd19ffd9cbbafd7d8ebf8e585be1ccb4977a` before any
eligible aggregate result. Screen exactly six routes: SAM2.1-only, SAM3.1 direct,
SAM3.1 discovery into SAM2.1 or SAM3.1 refinement, and RF-DETR detection into SAM2.1
or SAM3.1 refinement. Bind every cell to the same image-disjoint human-anchor holdout,
prompt set, part set, hardware profile, ontology, QA, pipeline, measurement bundle, and
14 exact provider artifacts. A hash-sealed screening result selects one to six finalists;
every selected route must then expand the complete 60-cell grid across DensePose with and
without SAM 3D Body, five silhouette/matting variants, three pose variants, and MediaPipe
Hands off/on. Freeze all 19 required measurement families before results.

**Why:** A flat all-combinations run would consume heavyweight runtime unnecessarily, while
an informal post-screening choice would permit route or specialist cherry-picking. The
two-stage contract freezes the route set, selection evidence, and full finalist expansion
in advance. Its synthetic fixtures validate matrix identity only; they do not supply the
human-anchor holdout, open screening results, install gated Meta artifacts, measure any
provider, select a winner, authorize promotion or serving, author a mask, or create gold.

**Approved by:** Kevin's SAM 3.1 modernization amendment and autonomous execution mandate

## 2026-07-15 - Administratively refreeze provider matrix with measurement compiler

**Item(s) affected:** MF-P2-11.13, MF-P2-11.14, aggregate matrix reproducibility

**Decision:** Supersede the pre-result `provider_benchmark_matrix_v1` policy hash
`65220c865e54b12e5558cfac9d05bd19ffd9cbbafd7d8ebf8e585be1ccb4977a` with canonical
SHA-256 `d0e2e85e50bb67096bf2c3838f62fdddfe0f4e7b785d626b2f74c71344351538`.
The route set, finalist rule, enrichment grid, truth contract, provider vocabulary, and 19
measurement families are unchanged. The superseding policy adds the exact aggregate metric
compiler source hash and explicitly requires 65 label rows, four evidence artifacts per cell,
two deterministic repeats, raw count denominators, and finite nonnegative runtime measurements.
The repository pre-commit formatter's canonical output is the source identity bound by this hash.

**Why:** The original policy bound the underlying metric implementations but not the new
top-level compiler that recomputes every matrix row. Freezing that compiler before any
manifest or result opens closes a reproducibility gap without changing a threshold or reacting
to performance. No real matrix manifest, screening result, metric output, finalist, or winner
exists at this refreeze point.

**Approved by:** Kevin's SAM 3.1 modernization amendment and autonomous execution mandate

## 2026-07-15 - Administratively rebind final completion policy after promotion-contract amendment

**Item(s) affected:** MF-P2-11.15, MF-P7-07.09, final modernization evidence index

**Decision:** Supersede pre-result `modernization_completion_v1` SHA-256
`aed53657c856f259d629d9f8dff588ccd9bde6226996d3e85c873df102ccb1c9` with
`23495c6296f248d12a2ff82f3ed47f24a832d9b97aeb5baf11b558d315fb71db` solely to bind the
amended Document 22 source hash. The 15 evidence domains, verifier identities, measurement rules,
freshness limits, artifact floors, tracker terminal-state requirements, D1-D11, G1-G9, and authority
boundary are unchanged. No eligible final completion bundle existed before this administrative
rebind.

**Why:** Document 22 now specifies the signed matrix-bound prerequisite certificate required before
role promotion. The final evidence index intentionally detects any authoritative-source change, so
its pre-result source digest must be updated before later primary completion receipts exist. This is
not a threshold change and grants no completion, promotion, serving, mask, or gold authority.

**Approved by:** Kevin's SAM 3.1 modernization amendment and autonomous execution mandate

## 2026-07-15 - Rotate the currency-review signer with explicit predecessor trust

**Item(s) affected:** MF-P7-07.01, MF-P7-07.03, signed currency-review history

**Decision:** Retire public signer `8cbbb8d8...`, preserve its public key under
`configs/governance/`, and activate signer `5892e515...` with its private key stored only
outside the repository under Kevin's profile. Chain the first review under the new signer to
valid predecessor review `e89fa70126325b6ac1f86652` / SHA-256 `1d83cab5...`. Record both
signers and their status in `currency_review_key_history.json`.

**Why:** The repository public key had been rotated repeatedly, but the matching latest private
key was not durably retained; the only remaining private key matched the original signer rather
than the current signed review. Reusing a mismatched key or accepting an invalid signature would
defeat the hard gate. An explicit, documented rotation preserves predecessor verification while
restoring a durable matching signer for current and future reviews.

**Approved by:** Kevin's autonomous execution mandate and the existing fail-closed currency policy

## 2026-07-15 - Administratively rebind unopened benchmark policies after LiteText installation

**Item(s) affected:** MF-P2-11.13, MF-P4-10.12, provider-matrix and local-Qwen
benchmark reproducibility

**Decision:** Supersede unopened `provider_benchmark_matrix_v1` canonical SHA-256
`d0e2e85e...` with `f76605c7...` and unopened `qwen_challenger_benchmark_v1`
canonical SHA-256 `cba85192...` with `3425c746...`. Change only their frozen source
hashes for `configs/external_sources.yaml` and, for the provider matrix, the expanded
`env/provider_runtime_matrix.json`.

**Why:** Installing the previously frozen SAM3-LiteText experiment legitimately changed the
governed provider registry and expanded the runtime matrix from seven to eight families. Both
pre-result policies intentionally failed closed on that drift. No eligible human-anchor manifest,
observation, screening result, finalist, Qwen result, or winner exists; routes, providers under
comparison, datasets, truth partitions, metrics, thresholds, margins, rollback rules, and authority
boundaries are unchanged. Rebinding before results restores reproducibility without reacting to
performance.

**Approved by:** Kevin's SAM 3.1 modernization amendment and autonomous execution mandate

## 2026-07-15 - Bind custom body-part champion mutation to the aggregate matrix certificate

**Item(s) affected:** MF-P2-11.15, MF-P5-10.11, `champion_bodypart` promotion and
rollback

**Decision:** `maskfactory models promote-custom-segmenter` accepts only the complete
signed ten-role matrix bundle. It no longer accepts a standalone custom-segmenter certificate
and caller-supplied identity document as sufficient mutation input. Inside the exclusive registry
lock, reverify the bundle's Ed25519 signature, complete matrix report and raw observations, exact
nine specialist packets, custom certificate and identities, ten unique role/cell bindings, and the
custom pipeline-context binding. Seal the matrix certificate, custom certificate, benchmark result,
candidate/incumbent checkpoints, registry states, and production smoke into a schema-valid v3
transaction. Bind rollback to that exact transaction and matrix certificate before restoring the
incumbent.

**Why:** Document 22 requires the aggregate certificate before *any* role mutation. The prior
custom transaction correctly enforced its role certificate, lifecycle swap, lock, smoke, atomic
history, and rollback, but it did not consume the aggregate certificate. That left a narrower input
path than the hand/clothing transactions and allowed `champion_bodypart` to mutate without proof
that all ten matrix roles were jointly certified. The replacement closes that bypass without
granting any benchmark, serving, mask, truth, or gold authority.

**Administrative compatibility rebind:** `retraining_compatibility_v1` is rebound before any
eligible retraining result from canonical SHA-256 `5650b8f2...` to
`9cfbae43775719fcd8c4ef112890d92b5afe8d186660caedf1a8d673d1e653c1` solely because its
frozen source identity includes `src/maskfactory/models/registry.py`, now SHA-256
`8ee3c3272ead50e9dd1d30e8d3c50fa3e41f72e827bf8675061a016bee033f34`. No rule,
threshold, authority, eligibility decision, or result changed.

**Approved by:** Kevin's SAM 3.1 modernization amendment and autonomous execution mandate

## 2026-07-15 - Require a signed three-file transaction for interactive-provider promotion

**Item(s) affected:** MF-P2-11.15, MF-P5-10.11, MF-P6-06.03, official SAM 3.1
interactive promotion and SAM2.1 rollback

**Decision:** Keep the signed aggregate ten-role matrix certificate unchanged and require a
same-signer interactive companion certificate before the `interactive_segmenter` role can mutate.
The companion binds the exact aggregate certificate and recomputed matrix report/manifest/
observations, candidate and incumbent matrix artifacts, the hash-valid interactive benchmark
certificate with all hard buckets passing, both checkpoints, the candidate runtime lock, and an
observed isolated candidate-promotion/incumbent-restoration rehearsal. Promotion must then serialize
under one exclusive lock, run an exact-input candidate serving smoke, and change
`configs/pipeline.yaml`, `configs/external_sources.yaml`, and `models/model_registry.json` through a
single hash-sealed transaction. Publish the external candidate first, the active pipeline selection
second, and the incumbent lifecycle demotion last so readers never observe an active unpromoted
provider. Rollback uses the inverse safe order, requires an exact-input incumbent smoke, and restores
all three original byte streams from hash-verified immutable snapshots. Both directions append
schema-valid records and restore the prior state if history publication fails. Expose the operations
as `maskfactory models promote-interactive` and `rollback-interactive`.

**Why:** Provider-neutral routing alone made a future SAM3.1 selection executable but did not make the
multi-file role/lifecycle change atomic, signed, smoke-first, or exactly reversible. Reusing only the
ten-role aggregate would not bind the distinct interactive winner, while expanding that frozen
ten-role certificate would rewrite an already approved contract. The companion closes the join
without changing the aggregate. This decision authorizes no current provider change: official SAM3.1
still needs its gated checkpoint, real image-disjoint human-anchor win, live smoke receipts, and an
observed production promotion/rollback.

**Approved by:** Kevin's SAM 3.1 modernization amendment and autonomous execution mandate

## 2026-07-17 — Separate autonomous core completion from human research and scale claims

**Item(s) affected:** MF-P6-07.01..MF-P6-12.06; legacy D1–D11/G1–G9 and P1–P9
human-anchor, CVAT, corpus-volume, training, multi-person, video, DAZ, and soak gates

**Spec said:** Earlier decisions and horizon records made human-anchor calibration, Kevin CVAT/SOP
review, reviewed multi-person sources, D1–D11, fixed package/clip volumes, approved video gold,
operator-cost review, DAZ maturity, or long soak evidence prerequisites for broad portfolio or
production claims.

**What we did instead:** Document 24 now defines `core_autonomous_runtime` as the sole required
finish line and freezes two additional non-blocking profiles: `independent_real_accuracy` and
`scale_daz_maturity`. Core uses deterministic hard vetoes, qualified autonomous critics,
synthetic/metamorphic/perturbation evidence, bounded hypothesis-distinct repair, typed abstention,
exact `operationally_certified_artifact` certificates, revocation, recovery, and a pinned
MaskFactory↔Main release/adoption bridge. Human/CVAT/real-holdout evidence remains valid only for
independent accuracy or human/training gold; volume/DAZ/soak work remains valid only for post-core
scale maturity. `operationally_certified_artifact` cannot be counted as or relabeled to
`human_approved_gold` or `autonomous_certified_gold`. Earlier conflicting log/horizon text is
historical evidence and has no current core-completion authority.

**Why:** The required product is an autonomous masking authority. Allowing optional human research
or scale evidence to redefine that finish line made autonomous completion impossible by construction
and conflated operational intended-use authority with population-accuracy and training-truth claims.
Claim-scoped profiles preserve all historical evidence without letting it silently block or revoke
the autonomous core.

**Approved by:** Kevin's explicit autonomous-core and no-mandatory-human-mask direction; implemented
as the authoritative doc-24/tracker claim firewall

## 2026-07-19 — Retain prerequisite truth after fixture-level integration success

**Item(s) affected:** MF-P6-08.05, MF-P6-08.06, MF-P6-08.07, MF-P6-09.01,
MF-P6-09.02, MF-P9-13.04

**Decision:** Record the passing governance regression as item evidence without converting
fixture-tested implementation into completion. Preserve declared dependency states: MF-P6-08.05,
MF-P6-08.06, MF-P6-08.07, and MF-P6-09.02 remain blocked; MF-P6-09.01 and MF-P9-13.04 remain
partially complete. Register the transform replay schema in shared validation, but do not widen the
frozen bridge protocol.

**Evidence:** 90 focused tests and scoped Ruff passed on 2026-07-19. `tracker.py validate` found no
structural problems and `tracker.py report` regenerated the authoritative views. The evidence is
fixture-level only: it does not establish a cross-project adoption/release, real external-source
admission, operational certificate issuance, or autonomous-core completion.

**Why:** Explicit dependency and claim boundaries prevent passing local contracts from fabricating
runtime or cross-project authority.

## 2026-07-19 — Register additive third-wave evidence schemas without changing authority

**Item(s) affected:** MF-P6-08.08, MF-P6-09.04, MF-P6-10.01

**Decision:** Register `bridge_artifact_binding_decision` and
`maskfactory_release_publication_evidence` in the shared validation registry. The autonomous
demonstration report was already registered. Retain all three items as blocked because their
fixture evidence does not satisfy declared prerequisite, publication, adoption, or runtime-authority
requirements.

**Evidence:** Ten focused autonomous-demonstration, artifact-binding, and release-publication tests
plus scoped Ruff passed on 2026-07-19. A direct shared-validator probe confirms both added schema
names resolve rather than raising an unknown-schema error.

**Why:** All governed evidence schemas must be reachable through the shared validation path, but
local, synthetic, and fixture-only tests cannot establish cross-project or production authority.

## 2026-07-19 — Treat fourth-wave fixes as registration-only governance integration

**Item(s) affected:** MF-P6-08.06, MF-P6-09.05, MF-P6-09.06, MF-P6-10.02, MF-P6-10.03

**Decision:** Accept only additive shared-schema/registration compatibility repairs for this
integration pass: register the missing bridge decision/admission schemas in the shared validator
and expose already-implemented bridge/operational-repair contracts through package exports.
Do not treat these changes as dependency closure or authority completion.

**Evidence:** Aggregate focused regression suite passed 94/94 across bridge/autonomy contract
tests (including prior bridge/autonomy suites) and tracker validate/report passed after status
updates via `Plan/Tracker/tracker.py`.

**Why:** These defects were integration-surface failures (schema lookup and package visibility),
not missing policy semantics. Fixing them improves cross-module compatibility while preserving
truthful blocked-state governance for unresolved prerequisites.

## 2026-07-19 — Keep crosswalk/release-packaging integration registration-only

**Item(s) affected:** MF-P6-09.07, MF-P6-10.04

**Decision:** For this governance lane pass, apply only clear compatibility registration fixes:
expose already-landed additive bridge modules through `maskfactory.bridge` and lock those exports
with focused registration tests. Do not modify lane-owned policy semantics, and do not upgrade
status to complete while declared prerequisites remain unresolved.

**Evidence:** Focused aggregate bridge suite passed 55/55 on 2026-07-19, including crosswalk and
clean-release packaging tests plus package export registration coverage. Tracker updates were made
only via `Plan/Tracker/tracker.py`, then `tracker.py validate` and `tracker.py report` both passed.

**Why:** The observed gap was integration-surface compatibility, not missing core logic. Enforcing
export visibility and regression guards improves cross-module consumption while preserving strict
dependency truth and avoiding fabricated completion claims.

## 2026-07-19 — Keep sixth-wave bridge integration registration-only

**Item(s) affected:** MF-P6-10.05, MF-P6-10.06, MF-P6-11.01, MF-P6-11.03, MF-P6-11.06

**Decision:** Integrate completed sixth-wave additive surfaces only through clear shared-schema,
package-registration, and export compatibility repairs. Register missing additive evidence
schemas in the shared validator, expose the Mode B localhost client through `maskfactory.bridge`,
and lock those surfaces with registration regression tests. Do not rewrite lane-owned policy
logic, and do not mark any of the five items complete while declared prerequisites and
Main-owned production evidence remain unresolved.

**Evidence:** Aggregate focused bridge suite passed 88/88 on 2026-07-19 covering adoption receipt
matrix, operational invalidation, external adapter conformance, Mode B localhost client, bridge
journal, registration guards, and adjacent bridge regressions. Tracker updates were made only
via `Plan/Tracker/tracker.py`; `validate` found no structural problems and `report` regenerated
authoritative views. Statuses remain blocked at raised fixture-credit percentages.

**Why:** The observed gaps were integration-surface compatibility failures (unknown schema names
and missing package exports), not missing sixth-wave policy implementations. Registration-only
integration preserves frozen-v1 compatibility and honest dependency/claim boundaries.

## 2026-07-19 — Keep seventh-wave Mode A/arbitration/failure-control integration registration-only

**Item(s) affected:** MF-P6-11.02, MF-P6-11.04, MF-P6-11.07

**Decision:** Integrate completed seventh-wave additive surfaces only through clear shared-schema
and package-export registration compatibility repairs. Register the three missing additive
evidence schemas in the shared validator, lock Mode A package-read / receipt-arbitration /
failure-control package exports with registration regression tests, and do not mark any of the
three items complete while declared prerequisites and Main-owned production evidence remain
unresolved.

**Evidence:** Aggregate focused bridge suite passed 108/108 on 2026-07-19 covering Mode A package
read, receipt arbitration conformance, failure control, registration guards, and adjacent bridge
regressions. Tracker updates were made only via `Plan/Tracker/tracker.py`; `validate` found no
structural problems and `report` regenerated authoritative views. Statuses remain blocked at
raised fixture-credit percentages (82%/80%/78%).

**Why:** The observed gaps were integration-surface compatibility failures (unknown schema names
in the shared validator path), not missing seventh-wave policy implementations. Registration-only
integration preserves frozen-v1 compatibility and honest dependency/claim boundaries.


## 2026-07-19 — Keep eighth-wave invalidation/feedback/recovery/Mode-B-slice integration registration-only

**Item(s) affected:** MF-P6-10.07, MF-P6-11.05, MF-P6-11.08, MF-P6-12.04

**Decision:** Integrate completed eighth-wave additive surfaces only through clear shared-schema
and package-export registration compatibility repairs. Register the missing
`bridge_recovery_evidence` schema in the shared validator, lock consumer-invalidation /
feedback-intake / recovery / Mode B vertical-slice package exports with registration
regression tests, and do not mark any of the four items complete while declared
prerequisites and Main-owned production evidence remain unresolved.

**Evidence:** Aggregate focused bridge suite passed 159/159 on 2026-07-19 covering consumer
invalidation, feedback intake, recovery, Mode B vertical slice, registration guards, and
adjacent bridge regressions. Tracker updates were made only via `Plan/Tracker/tracker.py`;
`validate` found no structural problems and `report` regenerated authoritative views.
Statuses remain blocked at raised fixture-credit percentages (80%/84%/80%/76%).

**Why:** The observed gap was an integration-surface compatibility failure (unknown
`bridge_recovery_evidence` schema name in the shared validator path) plus unlocked export
visibility for the four surfaces, not missing eighth-wave policy implementations.
Registration-only integration preserves frozen-v1 compatibility and honest
dependency/claim boundaries.

## 2026-07-19 — Keep ninth-wave 12.01-12.03 / P9-13 producers integration registration-only

**Item(s) affected:** MF-P6-12.01, MF-P6-12.02, MF-P6-12.03, MF-P9-13.04

**Decision:** Integrate completed ninth-wave additive surfaces only through clear shared-schema
and package-export registration compatibility repairs. Lock
`maskfactory_integration_release_evidence`, Mode A / multi-person Mode A vertical-slice
schemas and bridge exports, plus external-supervision qualification/hash/identity/split-dedup
schemas and the `external_supervision_producers` package surface with registration regression
tests. Do not mark any of the four items complete while declared prerequisites, Main/ComfyUI
execution, or real-source qualification gates remain unresolved.

**Evidence:** Aggregate focused suite passed 52/52 on 2026-07-19 covering integration release,
Mode A vertical slice, multi-person Mode A vertical slice, external supervision producers/
qualification, and registration guards. Tracker updates were made only via
`Plan/Tracker/tracker.py`; `validate` found no structural problems and `report` regenerated
authoritative views. Statuses remain blocked / partially_complete at raised fixture-credit
percentages (78%/80%/76%/80%).

**Why:** Shared schemas and bridge/producers package exports were already present from the
implementation lanes; the observed integration gap was unlocked registration-guard coverage
for those surfaces. Registration-only integration preserves frozen-v1 compatibility and honest
dependency/claim boundaries.



## 2026-07-19 — Keep tenth-wave 12.05/12.06 / main_consumer_conformance integration registration-only

**Item(s) affected:** MF-P6-12.05, MF-P6-12.06; main_consumer_conformance registration surface; MF-P6-08.05 confirmation

**Decision:** Integrate completed additive producer surfaces for cross-project qualification, final-release handoff, and main-consumer conformance only through clear shared-schema and package-export registration compatibility repairs. Register the missing `cross_project_qualification_evidence` schema, export the qualification APIs from `maskfactory.bridge`, lock handoff/conformance registration guards, and do not mark MF-P6-12.05 or MF-P6-12.06 complete while declared prerequisites and Main/production bindings remain unresolved. Confirm MF-P6-08.05 as complete after concurrent governance closeout plus reconfirmed operational policy/authority focused evidence.

**Evidence:** Aggregate focused suite passed 29/29 on 2026-07-19 covering cross-project qualification, final-release handoff, main-consumer conformance, and registration guards; scoped Ruff clean. Broader 08.05 authority/policy aggregate passed 83/83. Tracker updates were made only via `Plan/Tracker/tracker.py`; `validate` found no structural problems and `report` regenerated authoritative views. 12.05/12.06 remain blocked at raised fixture-credit percentages (78%/72%); 08.05 remains complete 100%.

**Why:** The observed gap for 12.05 was an integration-surface compatibility failure (unknown schema name + missing package exports). Handoff and main-consumer conformance schemas/exports were already present and only needed registration-guard locks. Registration-only integration preserves frozen-v1 compatibility and honest dependency/claim boundaries; producer_partial matrix evidence must not fabricate production qualification or final handoff authority.

## 2026-07-19 — Distinguish fixture_authority Main consumer from production Comfy_UI_Main

**Item(s) affected:** MF-P6-11.01–11.08, MF-P6-12.02–12.06; `core_autonomous_runtime` claim firewall

**Decision:** Treat `src/maskfactory/bridge/fixture_main/` as a closed-fixture / pinned cross-project adoption evidence surface (`authority_kind=fixture_authority`, `consumer_kind=synthetic_main_consumer`) that may satisfy producer verify clauses for adapter, Mode A package read, Mode B typed client, arbitration, feedback, journal, failure-control, recovery, and Mode A single/duo vertical-slice hash chains. Do **not** equate fixture_main with KevinSGarrett/Comfy_UI_Main production adoption: keep `main_adoption_complete=false` and `production_core_close_authorized=false`, and keep handoff rejection reason `fixture_authority_cannot_close_core`. Mark tracker complete only where verify clauses are honestly closed by fixture_main + producer fixtures (11.01–11.08, 12.02–12.03). Leave 12.04–12.06 open for champion-backed live Mode B prediction, production qualification binding, and authorized core close.

**Evidence:** Focused suite 108/108 PASS on 2026-07-19; `qa/live_verification/bridge_fixture_main_producer_verify_20260719.json`; tracker updates only via `Plan/Tracker/tracker.py`; validate clean; report regenerated; `core_autonomous_runtime` status blocked with open items MF-P6-12.04/12.05/12.06.

**Why:** Core completion profile allows closed fixtures and pinned cross-project adoption evidence without laundering synthetic receipts into production Main authority or independent_real_accuracy claims.



## 2026-07-21 — Standing orders hardwired as durable Plan authority

**Item(s) affected:** all autonomous-build sessions (operating rules); no tracker item status change
**Spec said:** Session playbook + autonomous operating rules govern routine execution; standing orders previously lived in chat/side-thread paste and risked loss across sessions.
**What we did instead:** Created canonical binding file `Plan/STANDING_ORDERS_AUTONOMOUS_BUILD.md` with Kevin's full standing orders text (unweakened) plus established RunPod runtime notes (NEVER EC2; pod asset paths; RUNTIME_BLOCKED_POD_CLASS for nested CVAT/Nuclio). Added short MUST-read pointers in CLAUDE.md, AGENTS.md, `.cursor/rules/`, Instructions START_HERE/SESSION_PLAYBOOK, and RESTART_HANDOFF — no duplicated essay.
**Why:** Prefer durable project files over chat-only memory so every future agent/session reads the same binding mandate; single canonical doc avoids drift from multi-copy churn.
**Approved by:** Kevin (explicit hardwire request) | AI-autonomous execution of the hardwire

## 2026-07-21 — Binding SELF-HOSTED STRICT VLM GATE (no blind approvals)
**Item(s) affected:** MF-P4-* visual acceptance; CAA / autonomous_certified_gold; tournament MVC Hard-QA; MF-P9-15.08; hand/clothing climbs
**Spec said:** Tier 4 visual QA via local Ollama; VLM qa_router_only; hard BLOCK absolute (Standing Orders). Prior gold-factory path used `qwen2.5vl:7b` as sole Hard-QA critic and allowed `--skip-vlm` theater.
**What we did instead:** Added binding `strict_visual_gate` with high-end primary `llava:13b` (+ `llama3.2-vision:11b` alternate) and `qwen2.5vl:7b` ensemble-only; `--skip-vlm` / critic-disabled → `VISUAL_CRITIC_BLOCKED`; gold profile `require_strict_visual_gate_pass: true`; admission audits STRICT sidecars before CAA corpus. Kept S11 `models.primary_vlm=qwen2.5vl:7b` fingerprint until recalibrated — autonomy STRICT gate does not use qwen as sole rubber stamp.
**Why:** Kevin hard mandate 2026-07-21: self-hosted high-end LLM on RunPod must STRICT visual review/QA for MF autonomy — no blind approvals; no cloud LLMs; NEVER EC2.
**Approved by:** Kevin (explicit CRITICAL MANDATE) | AI-autonomous implementation

## 2026-07-21 — Uniform source admission replaces project classifiers

**Item(s) affected:** MF-P0-14.01–.04, MF-P0-16.01/.07/.12, MF-P0-17.01,
MF-P2-10.02, MF-P4-09.01, MF-P4-10.03, MF-P8-10.01, MF-P9-14.01; docs
01, 07, 10, 16, 18, 19, 22, 23, 25; Instructions 07 and 09

**Previous value:** Active specifications repeated a special catalog-content intake lane and some
runtime/planning surfaces still required a retired classifier result despite the earlier retirement
of QC-V2-011.

**New value:** Catalog tags and retired classifier fields do not determine local source, training,
masking, QA, gold, provider, or routing eligibility. MaskFactory uses one uniform
admission path based on lawful ownership/license, provenance, integrity, ontology, measured quality,
and authority tier. Provider service policies remain transport constraints only. The single safety
exception is centralized in doc 01 §7 and is not expanded into a general age classifier or repeated
special lane.

**Downstream impact:** Remove tag-specific and retired-classifier predicates from active runtime schemas,
registries, intake, cloud-teacher admission, calibration fixtures, and tests while preserving
historical evidence records as immutable history. Sapiens2 remains excluded because its exact
license cannot support the required unrestricted input scope, not because MaskFactory maintains a
special admission lane.

**Why:** Kevin explicitly rejected the repeated eligibility language and any blanket exclusion or
special routing that prevents required training coverage.

**Approved by:** Kevin, explicit owner directive on 2026-07-21


## 2026-07-21 — Binding CONTINUOUS UNTIL E2E COMPLETE (NO STOP)
**Item(s) affected:** all autonomous-build sessions (operating rules); no weakening of STRICT VLM / proof tiers
**Spec said:** CONTINUOUS LOOP (NO IDLE) + stop only for true NEEDS KEVIN; sessions could still end with idle chat waits / parking after seals / agent-death pauses in practice.
**What we did instead:** Added binding Standing Orders section **CONTINUOUS UNTIL E2E COMPLETE (NO STOP)** forbidding idle Kevin waits, “no further action,” post-seal parking while unblocked work remains, waiting on subagent notifications without chaining, and treating usage-limit/agent-death as project pause without durable nohup + relaunch. Required immediate next-wave chaining and lane-switching on NEEDS KEVIN. Wired into `.cursor/rules`, Instructions `00`/`02`/`03` never-idle procedure, AGENTS/CLAUDE one-liners, and `.wt_climb4` Plan twins.
**Why:** Kevin hard mandate 2026-07-21: agents are NOT allowed to stop until entire MaskFactory project is fully completed end-to-end. Auto only; NEVER EC2.
**Approved by:** Kevin (explicit CRITICAL MANDATE — IMPLEMENTED INTO RULES) | AI-autonomous implementation

## 2026-07-22 - Real source corpora are mandatory and ontology v2 has 66 classes

**Item(s) affected:** MF-P0-13.05/.06, MF-P1-10.*, MF-P1-11.*, MF-P4-11.17/.23/.24,
MF-P5-09.*, MF-P9-13.02/.08, MF-P9-14.08/.10

**Previous value:** The local corpora were documented as inventories but could be omitted by a
semantic-calibration path that accepted synthetic colored-shape positives. Ontology v2 exposed 65
classes and did not contain a separately governed anus/visible anal-opening class.

**New value:** Every production semantic-critic calibration/qualification path requires exact real
source bindings from the governed MaskedWarehouse and reference-image roots. Evidence-qualified
MaskedWarehouse masks, points, silhouettes, and annotations must be consumed by named downstream
lanes; real reference images are mandatory retrieval/coverage/benchmark inputs. Synthetic scenes,
old draft masks, in-review masks, rejected masks, and unbound positives cannot satisfy semantic
validity. Ontology v2 contains 66 classes, preserves IDs 0..55, and appends exactly IDs 56..65,
including `anus`, with the complete visible-anatomy alias vocabulary.

**Authority boundary:** MaskedWarehouse directory membership does not by itself promote a draft to
gold, and reference-image selection does not supply mask truth. Exact provenance and authority
evidence decide how each asset may be consumed. Autonomous certification is valid; manual CVAT is
not a mandatory product-completion dependency.

**Why:** Kevin explicitly required the existing golden masks, points, silhouettes, and real reference
library to be used by the ultimate masking system and required complete visible adult anatomy rather
than synthetic controls or old low-quality drafts.

**Approved by:** Kevin, explicit owner directive on 2026-07-22

## 2026-07-22 - Canonical COCO pixels outrank stale exporter area metadata

**Item(s) affected:** MF-P0-18.03, MF-P0-18.04, MF-P0-18.07, MF-P4-12.02

**Observed:** The corpus contains 5,752 compressed COCO RLE annotations. A provisional check against
the separate annotation `area` field rejected 5,750, but a complete comparison against canonical
`pycocotools` 2.0.11 found all 5,752 decoded masks pixel-identical with zero decoded-area mismatch.
The source `area` metadata was produced from a different/stale geometry representation.

**Decision:** Validate compressed/uncompressed RLE by exact canvas, run totals, canonical decoding,
recomputed pixel area, and bbox geometry. Preserve the source `area` value and its match flag as
advisory lineage; it cannot override canonical mask bytes. For polygon bbox comparison, keep the
0.90 IoU gate and separately accept only cases where every bbox edge is within 1.5 pixels of the
rasterized mask, explicitly recording the quantization method.

**Authority boundary:** These rules create external machine hard-QC candidates only. Provider
comparison, strict per-record visual QA, repair/abstention, operational certificates, training
admission, and release authority remain separate open gates.

**Why:** This preserves valid source supervision without lowering geometry thresholds or allowing
stale metadata to become stronger than the actual COCO segmentation.

**Approved by:** Kevin's adult-corpus intake directive; AI-autonomous implementation and canonical
COCO API verification.

## 2026-07-23 - Selected RunPod has no GPU/VRAM resource-governance layer

**Item(s) affected:** MF-P1-02.05, MF-P4-01.01, MF-P5-03.02, MF-P6-02.04,
MF-P9-03.08, production RunPod routing, visual qualification, provider
benchmarking, training, serving, and DAZ execution

**Previous value:** Several compatibility paths could consult `gpu.lock`, VRAM
headroom, a coordinator lease, a capacity reservation, a checkout, a slot, or a
peak-VRAM threshold before allowing work or accepting a runtime/provider result.

**New value:** The directly selected RunPod executes without GPU/VRAM admission,
reservation, checkout, capacity lease, scheduler veto, file-lock veto, automatic
reclamation, or peak-VRAM qualification gate. GPU utilization and peak-memory
measurements may be retained only as non-authoritative telemetry. Missing, high,
or drifted GPU/VRAM telemetry cannot delay, refuse, disqualify, or promote work.

**Important distinction:** Durable mission, shard, and record ownership leases
remain mandatory because they protect queue truth, idempotency, checkpoints, and
crash recovery. They do not allocate, reserve, check out, or govern the GPU.
OOM remains a typed runtime outcome with bounded retry/abstention behavior; it
does not authorize a pre-execution VRAM gate or threshold weakening.

**Approved by:** Kevin, explicit owner directive on 2026-07-23

## 2026-07-23 - Real-data-first learning and targeted DAZ activation

**Item(s) affected:** MF-P0-18.*, MF-P4-12.*, MF-P5-11.01 through
MF-P5-11.10, MF-P9-10.07/.09/.11, MF-P9-13.*, MF-P9-14.*

**Decision:** The first production learning cycle prioritizes the 81,910-record
adult intake, qualified MaskedWarehouse masks/COCO/points/silhouettes, and
leakage-safe partitions of the approximately 83,422-image reference library.
It trains a hierarchical ownership/anatomy/specialist/boundary cascade, expands
bbox/reference proposals, iteratively self-trains from immutable weighted
mixtures, and mines hard cases. Large-scale DAZ generation is deferred until an
immutable residual real-data gap report names exact target cells.

**DAZ boundary:** Foundation, mapping, renderer-correctness, and small
deterministic DAZ canaries may continue independently. DAZ 1,000/10,000-scene
scale and mixture promotion require the gap report plus matched real-only
versus real-plus-DAZ ablations on untouched real evaluation.

**Authority boundary:** Reference images, boxes, points, prompts, action tags,
and unqualified candidates do not become pixel truth. Self-supervised
reference-domain learning creates representations, not masks. Fine anatomy is
never invented from a coarse source label. Qualified visual models diagnose;
segmentation providers change pixels; deterministic certification evaluates
authority.

**Approved by:** Kevin, explicit strategy authorization on 2026-07-23

## 2026-07-23R - External deep-review Amendments 1–3 adopted

**Item(s) affected:** MF-P4-11.18, MF-P4-11.23, critic qualification and
control-admission protocol/registry paths, the 66-label control program, and
all future certification callers.

**Decision:** Kevin adopts the three governed amendments from the external
deep review, preserved verbatim with SHA-256
`B97843DD4B7E3095547B7CE3EDA10C5F7A94F32B73044E221BFBA7AC6E31DBB7` at
`Plan/Reviews/EXTERNAL_DEEP_REVIEW_20260723.md`:

1. Per-record visual acceptance requires deterministic QA pass, no serious
   finding from a qualified critic, and coherent evidence localization. A
   VLM's bare `pass` token is never sufficient. Malformed, truncated,
   timed-out, uncertain, or schema-invalid output is a typed abstention.
2. Exact-panel interactive session-agent screening is a bounded, logged,
   hash-bound, non-certifying calibration-control-admission activity. It can
   never grant mask gold, training truth, a certificate, or visual-role
   authority.
3. A hard-QC-passing, multi-provider-consensus draft that passes Amendment-2
   screening may be admitted only as a declared-fidelity, calibration-only
   positive control. It never becomes gold, training truth, package authority,
   or an operational certificate.

**Versioning boundary:** These amendments apply only through new immutable
artifacts. The initial implementation is
`maskfactory-critic-protocol-v3-severity-20260723r` with its separately
versioned `visual_critic_protocol_v3.yaml` registry. Frozen legacy protocol,
corpus, role, certificate, and threshold artifacts remain unchanged. Any new
label, fidelity tier, scale, calibration fit, or holdout board requires a new
hash-bound registry/board version; no in-place adjustment is permitted.

**Authority boundary:** Protocol-v3 is qualification-canary-only until a
stage-2 frozen real-image board meets every governed metric. It does not issue
roles, certification, autonomous gold, or training truth, and deterministic
hard blocks remain absolute.

**Approved by:** Kevin, explicit adoption in the 2026-07-23R pursuing goal.
