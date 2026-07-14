# Document 19: Multi-Provider Teacher and Continuous-Improvement Spec

## 1. Decision and Intended Outcome

MaskFactory uses a governed hybrid, not an autonomous self-training loop. The local Qwen workhorse,
Gemini, OpenAI, and Anthropic may inspect evidence, identify likely defects, select a correction tool,
and produce isolated mask candidates. SAM2, polygons, specialist segmenters, deterministic cleanup,
and later trained MaskFactory models produce pixels. Humans remain the only gold authority.

The optimization target is **less human correction time at equal or better gold quality**. More model
calls, higher confidence, provider agreement, or visually plausible masks are not success metrics.
No model is allowed to learn from its own unverified output. That prohibition prevents confirmation
bias and irreversible pseudo-label poisoning.

## 2. Roles

| Component | Role | Pixel output | Authority |
|---|---|---:|---:|
| Local Qwen VLM | Always-available private auditor, defect classifier, tool planner, before/after critic | No | Shadow/advisory until calibrated |
| Deterministic QA | Geometry, topology, overlap, hashes, ontology, left/right and invariant vetoes | Cleanup candidates only | May block; never approves gold alone |
| Gemini teacher | First cloud call for difficult parts; semantic audit and normalized polygon proposal | Polygon candidate | Shadow only |
| OpenAI teacher | Independent semantic disagreement critic and correction-plan challenger | Points/polygon proposal only | Shadow only |
| Anthropic teacher | High-resolution tie-breaker for unresolved or serious cases | Points/polygon proposal only | Shadow only |
| SAM2 / specialist models | Execute approved point, box, polygon, or model correction plans | Isolated candidate | Never writes authoritative map in S11 |
| Human reviewer | Selects/edits/rejects candidates and records defect/correction usefulness | Gold correction | Sole semantic gold authority, subject to automatic hard QA |

Image generation/edit models such as GPT Image are not boundary authorities. Their edit masks guide a
generative operation rather than guarantee exact binary geometry. They may be evaluated later for
synthetic-data generation in a separate provenance lane, but not used to repair gold masks.

## 3. Per-Part Runtime Cascade

1. Render six independent images: full-person context, source crop, binary mask, overlay, contour,
   and protected-neighbor overlap. Preserve full-body orientation and a high-resolution crop.
2. Run deterministic QA and the local Qwen audit. A deterministic non-pass vetoes a Qwen pass.
3. Escalate only high-risk labels, local fail/uncertain cases, automatic-QA non-passes, component
   overrides, or meaningful model disagreement. Easy local passes do not consume cloud budget.
4. Verify exact-image cloud eligibility independently for each provider. Default is deny.
5. Reserve worst-case cost in the local hash-chained ledger before dispatch. Do not retry a billable
   request automatically. Unknown usage after dispatch is charged at the full reservation.
6. Ask Gemini first. Stop if it agrees with local evidence and no independent contradiction exists.
   Otherwise ask OpenAI; ask Anthropic only when the first two disagree or a serious defect remains.
7. Strictly parse the closed JSON schema. Invalid JSON, missing observations, bad coordinates, unknown
   defect labels, or a pass containing a correction become unusable evidence.
8. Materialize polygons directly or invoke SAM2 with bounded positive/negative points. Store under the
   S11 cloud-candidate directory; never overwrite `label_map_part.png` or package masks.
9. Reject empty, wrong-sized, excessive-change, protected-overlap, or prompt-polarity-violating masks.
   Run automatic QA and blinded before/after review on surviving candidates.
10. Present baseline and candidates to the human without silently preselecting an uncalibrated model's
    choice. Record whether each diagnosis was correct, whether its proposed correction was useful, edit
    time, final gold hash, baseline IoU, and boundary F-score.

Provider consensus is correlated evidence, not truth. A unanimous answer cannot clear a deterministic
block and cannot create a quick-pass queue.

## 4. Budget Contract

- `configs/cloud_teacher.yaml` is disabled by default and shadow-only.
- The current Kevin-authorized daily operational target is $14.50 and the absolute local hard cap is
  $15.00. The limit is configuration-bound and may only be raised after a new explicit spending
  authorization; unused capacity is not an authorization for a different image or purpose.
- Each request reserves $1.00 before dispatch, even though expected cost is much lower. At most three
  provider calls are allowed per image/part cascade.
- Six images exactly; each is at most 2048 px on its long side and 10 MiB, with a 30 MiB bundle cap.
- There are no automatic HTTP or semantic retries. Timeouts and malformed results consume their full
  reservation because billing status cannot be proven locally.
- The ledger is append-only, hash-chained, lock-protected, date-bounded in America/Chicago, and refuses
  a request whose reservation could exceed the hard cap.
- Batch APIs may be used only for frozen offline evaluation after a separate cost estimate and approval;
  they are not the interactive correction path.

No paid call is authorized merely by enabling code or storing a credential. Kevin must approve billable
execution, and the exact image must independently pass the cloud-eligibility registry.

## 5. Privacy, Adult Content, and Provider Eligibility

Adult/NSFW images are allowed in the local MaskFactory training and gold workflow when all other data
governance rules are satisfied. Cloud transmission is narrower: every transmitted artifact must be
clear-adult, rights-cleared, hash-bound, explicitly approved, and provider-allowlisted. A provider's
content policy may make a lawful local image ineligible for that provider; the system then remains
local-only. Apparent-minor or age-uncertain content is never sent to a cloud teacher.

Credentials are read only from environment variables at dispatch. Logs contain hashes, model IDs,
token usage, cost, verdict structure, and errors, but not credentials or raw provider responses. Data
retention and provider policy must be re-reviewed before enabling a provider or changing its endpoint.

## 6. Frozen Incremental-Value Gate

Each provider/model/prompt is evaluated separately on at least 200 real, human-truthed, image-disjoint
cases containing naturally occurring errors. The corpus must cover serious anatomy swaps, missing parts,
neighbor/person contamination, clothing/skin boundaries, hair, hands/fingers, feet/toes, occlusion,
multi-person contact, and good masks. The gate is invalid if it is not frozen or if training images leak
into it.

All thresholds must pass simultaneously:

- serious-defect recall >= 0.95;
- overall defect recall >= 0.90;
- precision >= 0.80;
- false-pass rate <= 0.02;
- incremental recall over local Qwen + deterministic QA >= 0.05;
- human-rated correction usefulness >= 0.70 among true-positive diagnoses;
- cloud cost per useful correction <= $0.50;
- no increase in median total human review time;
- no material regression by high-risk label, pose, body presentation, or solo/duo/group context.

Passing permits continued shadow use and may justify showing ranked candidates. It does not grant mask,
gold, blocker-clearance, or quick-pass authority. A provider that fails incremental value is disabled for
mask QA even if its standalone accuracy appears high.

## 7. Human-Gold-Only Improvement Loop

After human review and package freeze, MaskFactory harvests a hash-bound resolution record containing
the baseline mask hash, final gold mask hash, baseline IoU and boundary F, teacher judgments, reviewer,
and approval time. Only records marked `human_approved_gold_only` enter learning.

The records are split by source image, never by panel, into immutable training and holdout IDs. At least
50 balanced train records are required before constructing prompt/retrieval exemplars. At least 500
balanced train records are required before a Qwen LoRA candidate may be trained. These numbers indicate
readiness, not automatic promotion.

Each Qwen improvement candidate gets a new immutable model/prompt identity and is tested against:

1. the untouched teacher holdout;
2. the approved-gold 40-panel local gate;
3. the >=200-case incremental-value set;
4. per-label and serious-defect regressions;
5. latency/VRAM and reviewer-time budgets.

Only a measured challenger may replace the prior local model. Rollback is the prior registry pointer.
Cloud-generated masks, provider agreement, synthetic diagnostics, and unreviewed SAM2 candidates are
never Qwen targets or segmentation training labels.

## 8. Implemented Control Surface

- `configs/cloud_teacher.yaml`: provider cascade, costs, thresholds, learning gates.
- `configs/cloud_eligibility.yaml`: default-deny exact-image/provider admissions.
- `src/maskfactory/vlm/cloud_budget.py`: local daily spend authority.
- `src/maskfactory/vlm/cloud_providers.py`: strict provider adapters.
- `src/maskfactory/vlm/cloud_teacher.py`: escalation, consensus, proposals, and gold harvesting.
- `src/maskfactory/vlm/cloud_eval.py`: frozen offline incremental-value scoring.
- `maskfactory vlmqa cloud-status`: readiness/spend check; never billable.
- `maskfactory vlmqa evaluate-cloud-teacher`: offline gate; never billable.
- `maskfactory vlmqa harvest-teacher-resolution`: human-gold resolution append.
- `maskfactory vlmqa build-distillation`: image-disjoint prompt/LoRA readiness manifest.
- `maskfactory golden-reference import`: losslessly normalizes user-authored BW layers, cross-checks
  every solid overlay, maps only honest ontology candidates, and records missing/overlapping/ambiguous
  layers without manufacturing package-gold authority.
- `maskfactory golden-reference verify`: rechecks every normalized mask, source hash, manifest hash,
  geometry, and strict `{0,255}` encoding.

The subsystem remains disabled until credentials, exact-image approvals, frozen evaluation data, and
explicit spending approval exist. That disabled state is correct and does not block local production.
