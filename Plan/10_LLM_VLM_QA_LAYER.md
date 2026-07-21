# Document 10: LLM / VLM QA Layer

**Doc-24 authority amendment:** this document remains the design for the LLM/VLM observation,
diagnosis, routing, and optional-review surfaces. The LLM/VLM is never unilateral pixel or certificate
authority. Required `core_autonomous_runtime` may nevertheless accept an exact output through doc 24's
machine-enforced operational-autonomy certificate after deterministic hard vetoes, independent critics,
stability tests, bounded repair, and revocation controls pass. Human review, human-anchor calibration,
and the population-confidence gate described below belong to optional `independent_real_accuracy`;
their absence is not a core-runtime blocker. Where this older document says a candidate must go to a
human or cannot be accepted until human review, read that as the optional review route, not as a ban on
doc-24 exact-output operational authority.

Role (constitutional): the LLM/VLM layer is the **brain / QA / router / tool controller — never
unilateral pixel authority**.
It decides which masks are required, reads manifests, catches missing labels, compares overlay
panels, produces QA reports, routes hard cases, generates correction instructions, checks L/R
naming, and detects impossible claims. It never directly authors or approves gold pixel masks.
It may direct a governed segmentation tool (initially SAM2) to create a separate correction
candidate, compare before/after evidence, reject an unsafe candidate, and send a bounded proposal
to the autonomous certification transaction, autonomous abstention/quarantine, or optional human
review. The authoritative PART map changes only through a separate validated transaction; an LLM/VLM
verdict alone can never make that change.

---

## 1. Model Selection (decision made)

| Slot | Model | Runtime | Use |
|------|-------|---------|-----|
| Primary VLM | **Qwen2.5-VL 7B Q4** | Ollama (Docker, 127.0.0.1:11434) | All image-panel review — local, private, no content-block friction on body-part QA |
| Fallback VLM | llama3.2-vision 11B Q4 | Ollama | If Qwen unavailable/regresses on eval set |
| Text LLM (local) | qwen2.5:7b-instruct | Ollama | Manifest lint, correction-instruction drafting |
| Cloud teachers (optional) | Gemini / OpenAI / Anthropic | Provider APIs, disabled by default | Per-image-opt-in shadow review and bounded correction proposals under doc 19. They never approve gold or overwrite a mask. |

VRAM: VLM runs in its own exclusive GPU slot (doc 05 §5). Batch S11 model-major.

## 2. Inputs Per Review

- Legacy compatibility: the 5-tile zoom panel.
- Workhorse mode: six separately encoded images — full-person context with crop box, source crop,
  binary mask, overlay, contour, and protected-neighbor overlap. Diagnostic images are individually
  1024×1024 and MUST NOT be compressed into one 1024×205 strip.
- Whole image: clean source and all-parts color overlay as two independent images + compact predicted
  presence digest. An absent prediction is explicitly unknown, never evidence that anatomy is not visible.
- The relevant qa_report excerpts (which QCs warned/routed).

## 3. Prompt Suite (versioned in `src\maskfactory\vlm\prompts\`, version stamped in reports)

**P-PART (per-part panel):**
"You are auditing a body-part segmentation mask for label `<label>` (left/right is from the
CHARACTER's perspective). Panel tiles: source crop, mask, overlay, contour, protected-overlap
heat. Answer STRICT JSON only: {verdict: pass|fail|uncertain, confidence: 0-1, problems: [subset of
[wrong_part, wrong_side, boundary_too_loose, boundary_too_tight, includes_clothing_as_skin,
includes_background, includes_neighbor_part, missing_visible_area, mask_on_hidden_area,
finger_merge, hair_edge_bad, occlusion_error, other]], evidence: '<≤25 words pointing at panel
location>', correction_instruction: '<≤30 words imperative for the annotator>'}."

**P-IMAGE (whole-image sanity):** receives clean source first and color overlay second. It compares
visible anatomy against predicted presence, flags missing/misplaced/LR/impossible claims, treats
prediction absence as unknown, and never infers hidden pixels.

**P-MANIFEST (text LLM):** lint manifest vs ontology (states complete, subsets consistent,
occlusion graph acyclic, notes quality) → JSON findings.

Parsing: responses must parse as JSON; one retry with "JSON only" reminder; still bad → verdict
`uncertain` (never guess).

**P-WORKHORSE:** requires a nonempty observation for every one of the six images, then emits the
ordinary verdict plus a bounded correction plan: `none | sam2_refine | human_review`, up to 12
full-source positive points, up to 12 full-source negative points, and a rationale. Points are
strictly range-checked; invalid output becomes `uncertain` and cannot invoke a tool.

**P-COMPARE:** receives the complete six-image set for the current mask followed by the complete
six-image set for the correction candidate. It reports `better | worse | no_material_change |
uncertain`, fixed problems, remaining problems, and localized evidence. Presentation order alone
is not evidence.

Controller authority is independent of model confidence. A label-specific non-pass deterministic
finding (side, protected overlap, area, components, chain geometry, model disagreement, etc.) vetoes
a VLM pass. BLOCK becomes fail; ROUTE/WARN becomes uncertain. Package-wide findings are not falsely
attributed to an individual label. The raw model verdict/confidence and every controller override are
stored separately for calibration and debugging.

## 4. Verdict Schema & Calibration

Verdicts append to `qa_report.vlm_review.verdicts[]`:
`{label, panel_file, model, prompt_version, verdict, confidence, problems[], evidence,
correction_instruction, latency_ms}`.
Calibration set: 40 panels with known ground truth (20 good / 20 seeded-defect) maintained under
`qa\vlm_eval\`; `maskfactory vlmqa eval` must show ≥ 0.90 recall on defects and ≥ 0.80 precision
before a model/prompt version is allowed in production (gate MF-P4-05). Re-run on every model or
prompt change. In workhorse mode the fingerprint also binds the comparison and whole-image prompts,
client behavior, evidence renderer, production controller, and workhorse implementation; controller
or evidence drift invalidates the gate.

The 40-panel gate is the minimum enablement check, not proof of incremental value. A separate blinded
real-image decision set must compare auto-QA alone, auto-QA+VLM, and human truth for catastrophic
false-pass rate, incremental defect recall, correction usefulness, latency, and reviewer time.

## 5. Routing Logic (`vlm/router.py`)

| Auto-QA | VLM verdict | Route |
|---------|-------------|-------|
| all pass | pass ≥0.7 conf | **quick-pass queue** (human skim, expected <1 min/part group) |
| all pass | fail | careful queue + VLM correction_instruction attached to CVAT task |
| ROUTE flags | pass | careful queue (auto-QA wins for caution) |
| ROUTE flags | fail | careful queue, priority ↑, disagreement heatmap pinned |
| any | uncertain | careful queue, no annotation hints (avoid anchoring) |
VLM can NEVER approve gold, NEVER clear a BLOCK, or directly edit an authoritative/gold mask. Its
correction instructions and non-gold draft selections are machine-generated inputs to human review.

The tool-controller extension does not weaken that authority boundary. SAM2 may write only under
`S11/correction_candidates/`; S11 never overwrites the S09 authoritative map, a gold package mask, or
a human-approved artifact. It may compose an explicitly non-gold
`autonomy_review_draft/label_map_part.png` for S12/CVAT after per-label and final complete-map hard QA.
Candidate generation requires a fail verdict at confidence ≥0.7, valid
prompt points, prompt-polarity satisfaction, changed area ≤75% of the prior, protected-neighbor
overlap ≤2%, and recorded before/after evidence. Quick-pass is disabled for workhorse output until
the real approved-gold calibration gate and a separate incremental-value study support it.

Without a current calibration gate, workhorse execution is uncalibrated shadow work only: it may
render evidence and create isolated review candidates, but emits no authoritative `qa_report`
verdict, creates no disagreement failure record, cannot alter careful routing, and cannot bypass
human review in the optional human/training route. It may improve the reversible non-gold review draft
under the hard-QA rules below, or feed the separate doc-24 operational-certification transaction without
claiming population calibration.

Doc 20 adds progressive autonomy without weakening this default. S11 candidates may enter a governed
tournament and become `machine_verified_candidate`. A label/context may become
`calibrated_auto_accepted` only under a current hash-bound 95%-confidence certificate. Neither status is
human gold. Provider disagreement, any BLOCK, certificate drift/expiry, or insufficient winner margin
forces the residual queue for autoaccept. It does not prevent a demonstrably safer, hard-QA-passing
candidate from becoming the reversible non-gold starting draft for required human review; the S09
baseline and full provenance remain available for per-label rollback. “Required human review” here is
required only when that optional truth route is selected; core instead repairs, operationally certifies,
or abstains under doc 24.

## 6. Cloud Boundary & Privacy Rules

Cloud image transmission is an explicit, separately governed exception defined by doc 19. The
teacher subsystem may be enabled, but image transmission remains default-deny. An image may leave
the machine only when an exact SHA-256 registry
record proves rights evidence, explicit transmission approval, and the named provider.
The request carries six bounded diagnostic images, no unnecessary metadata, and no credential or raw
response is logged. A hash-chained pre-dispatch reservation ledger enforces the daily circuit breaker.
Provider output is untrusted shadow evidence: it cannot approve gold, clear a blocker, alter routing,
or overwrite the PART map. Images lacking the exact opt-in remain local-only without reducing normal
pipeline functionality. Provider retention/content restrictions are operational constraints, not
evidence of mask correctness.

## 7. Intake handling (referenced by S00 step 5)

The centralized source policy in doc 01 §7 remains binding. Admission otherwise uses rights,
provenance, integrity, format, ontology, and measured technical quality.

## 8. Additional LLM Duties (batch jobs)

- Nightly: manifest lint sweep (P-MANIFEST) across new packages → findings report `qa\reports\`.
- Weekly: failure_queue clustering — text LLM groups failure_reason strings, proposes coverage
  targets (feeds doc 12 §7), drafts the weekly QA summary markdown.
- On ontology change: consistency review of ontology.yaml vs doc 02 tables (diff explanation).

## 9. Pixel Workhorse Strategy

The VLM is an investigator and tool planner, not the pixel model. Pixel candidates come from SAM2,
specialist parsing/hand/hair/feet lanes, trained body-part models, deterministic cleanup, and model
consensus. The next concept-segmentation backend to evaluate is official SAM 3.1 because it accepts
text concepts, exemplars, boxes, points, and masks. It remains uninstalled until checkpoint access and
its separate Python 3.12/PyTorch 2.7+/CUDA 12.6+ runtime are governed and a measured hardware smoke
passes. No provider is promoted on benchmark claims alone.

General VLM model upgrades are likewise evidence-gated. Qwen3-VL 8B and Qwen3.5 9B were tested on a
known-bad real left-forearm mask in July 2026: Qwen3-VL still returned a confidence-1.0 pass, while
Qwen3.5 could not complete either the six-image or reduced three-image audit within 180/300 seconds.
Neither model is a production replacement on the current 8 GB GPU.

## 10. Specialist-Aware Committee Contract

S11 consumes the validated auxiliary summary produced under S06 rather than trusting arbitrary
files from a detector workspace. It verifies proposal-only authority, source geometry, strict binary
encoding, contained normalized paths, detector identity, checkpoint SHA-256, class remap,
confidence, box, and effective runtime mode before using any specialist evidence.

For each exact ontology candidate, the local workhorse and every cloud teacher eligible for that
source receive the same independent six-image evidence. The full-context image draws the raw
specialist contour in green and the prompt carries its provenance. A specialist proposal is evidence,
never truth: it cannot approve gold, clear a BLOCK, overwrite S09, or bypass human review.

A specialist whole-hand or whole-foot mask is parent-union visual evidence only. S11 may render it and
use its box as a repair hint for every relevant child label, but it must not register that union as an
atomic tournament candidate. Bare-foot support becomes exact `foot_base` plus `toes` only through the
pose-backed MTP split defined in doc 21. Reviewer evidence explicitly identifies whether its green
contour is an exact atomic candidate or parent-union support, preventing a reviewer from treating the
entire hand/foot as the requested base label.

Auxiliary `protected_only` proposals join the protected-neighbor union used by candidate collision
checks. Exact `part_candidate` masks also enter the autonomy tournament as explicit raw candidates
with their real detector/checkpoint provenance. They undergo the same complete-map hard QA as every
other candidate. Independent-source requirements remain honest; one specialist checkpoint is one
source and is not inflated into a consensus.

Raw specialist versus final disagreement is measured over their union. At or above the configured
threshold (0.03 initially), `AUX-S11-001` forces careful routing, pins disagreement evidence, and is
included in the provider-vote and lifecycle records. This routing is investigative and conservative;
agreement does not promote a proposal's authority.

`configs/vlm.yaml:runtime.cloud_enabled` and `configs/cloud_teacher.yaml:enabled` must agree. This
single enablement state only makes the governed teacher cascade available. Actual transmission still
requires the exact source hash, rights evidence, named-provider approval, credential,
and remaining budget. Any prompt, controller, evidence renderer, or bound model change invalidates
the production VLM gate. A replacement gate may be built only from exactly 20 distinct frozen,
QA-passing, human-approved gold packages; synthetic or machine-approved masks have no calibration
authority.

## 11. Exact-Candidate Autonomous Repair

Production repair follows doc 21: S05-bound ROI, isolated polygon/SAM2 proposals, transactional
complete-map composition, deterministic QA, tournament, then a fresh review of the exact winner. The
cloud diagnosis cascade may stop early; the convergence committee may not. Qwen and every enabled
eligible cloud reviewer inspect the same candidate and must pass it at the configured advisory floor;
missing/malformed output is not pass. This unanimous advisory result is not a calibrated probability.
A failure downgrades that candidate and contributes a bounded correction proposal to the next round.
Baseline or other-candidate votes cannot be inherited. A 95% acceptance claim still requires the frozen
human-anchor calibration certificate and confidence-bound gate.

The prompt includes the requested label's full ontology boundary contract. Deterministic atomic guards
veto whole-foot-as-`foot_base`, heel-as-`toes`, and multi-fingertip-as-`hand_base` errors when the needed
pose/visibility evidence exists; reviewer agreement cannot override these vetoes. Local transport errors
become explicit uncertain votes. Cloud diagnosis and convergence share job/per-label call caps, and the
duplicate diagnosis cascade is skipped by default while exact-candidate convergence is active. Definite
unbilled HTTP rejections release their reservations; ambiguous post-dispatch failures remain charged
pessimistically.

The one local invalid-output retry receives the exact contract error rather than a generic JSON reminder.
This allows repair of missing/extra keys, observation omissions, point type/range errors, and pass/tool
conflicts without accepting malformed output. The retry does not coerce values or weaken fail-closed
parsing; a second invalid response remains confidence-0 uncertain.

The result remains a reversible non-gold draft. Calibration controls review bypass; no VLM confidence,
committee vote, or repair round approves gold or clears hard QA.
