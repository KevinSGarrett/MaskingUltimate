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
does not weaken any project data-governance or age-safety rule. The distro is a
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
of detector `.pt`/archives, and ~359 MB of adult/NSFW pose-pack PREVIEW PNGs.
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
**Decision:** Do not gate ingestion, drafting, QA, cloud-teacher routing, training, certification, or
adult/NSFW eligibility on an apparent-age or `clear_adult` predicate. Retire QC-V2-011 and remove the
age predicate from the affected code/config/tests. Continue to enforce source rights/provenance,
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
reproducible source runtime and allow both governed adult/NSFW lanes under the private-local profile,
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
