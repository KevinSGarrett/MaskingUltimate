# Document 20: Progressive Autonomous Mask Factory Spec

## 1. Objective and Truth Contract

The system creates, reviews, corrects, compares, and selects almost all masks without manual drawing.
Human work becomes calibration and statistical auditing rather than per-mask production. Autonomy is
earned separately for each ontology label and operating context (`solo | duo | small_group`, plus pose
and visibility strata when evidence shows material differences).

No confidence statement is accepted without measured human truth. `machine_verified_candidate` and
`calibrated_auto_accepted` are explicit non-human truth tiers. Neither is renamed
`human_approved_gold`, satisfies gold-count gates, or enters frozen holdouts.

## 2. Autonomous Candidate Tournament

For each label, the controller collects up to 12 candidates over at most three rounds from the custom
MaskFactory segmenter, S09 fusion, SAM2, parsing/specialist models, deterministic cleanup, cloud-teacher
plans, and disagreement-region variants. Every candidate records immutable hashes, generator versions,
independent source count, consensus IoU, boundary agreement, pose consistency, critic votes, topology,
protected/exclusive overlap, and BLOCK findings.

Hard vetoes execute before scoring. Invalid format, any BLOCK, protected overlap >1%, mutually exclusive
overlap >0.5%, ontology component overflow, or fewer than three independent sources prevents selection
regardless of model confidence. Eligible candidates score by consensus (25%), boundary agreement (20%),
pose consistency (15%), source diversity (15%), and reliability-weighted critic support (25%). The
winner needs score >=0.88 and margin >=0.03. Provider disagreement currently forces residual review.

## 3. Correction Rounds

If no candidate wins, critics localize disagreement and choose bounded SAM points/boxes, polygons,
specialist reruns, component removal, or boundary refinement. Corrections create isolated candidates.
Each round reruns hard vetoes and blinded before/after comparison. The loop stops after three rounds or
twelve candidates so uncertainty cannot consume unbounded compute, money, or repeatedly erode a mask.

## 4. 95%-Confidence Autonomy Certificate

Autonomous acceptance requires a current certificate for the exact label, context, and complete
pipeline fingerprint. It uses only a frozen, image-disjoint, human-truthed sample of cases the machine
would have accepted. The one-sided 95% Wilson upper confidence bound must show:

- overall false-accept rate <=1%;
- serious false-accept rate <=0.5%;
- at least 300 audited autoaccepted cases, with the serious bound generally requiring roughly 600
  zero-serious-failure cases;
- exact pipeline/model/prompt/controller fingerprint match;
- no holdout leakage;
- certificate age <=30 days.

Any pipeline change, expiry, serious audited failure, distribution drift, or hash mismatch revokes the
certificate. A hair certificate cannot authorize fingers, occlusion, or multi-person contact.

## 5. Lifecycle Outcomes

| Outcome | Meaning | Per-mask human action |
|---|---|---|
| `residual_human_queue` | Veto, disagreement, low score/margin, or exhausted corrections | Required |
| `machine_verified_candidate` | Tournament winner without a valid certificate | Audit during calibration |
| `calibrated_auto_accepted` | Winner under exact valid certificate | No routine review; random audit only |
| `human_approved_gold` | Human-approved and hard-QA-passing package truth | Human authority |

Calibrated autoaccepted masks may enter semi-supervised training at loss weight 0.25; human gold remains
weight 1.0. Machine labels never enter validation, test, hard-case, calibration, or certificate truth.

## 6. Minimal Human Audit Instead of Per-Mask Labor

Calibrated strata use a deterministic random 2% audit sample with at least 20 audits per week. Sampling
occurs before results are known. The first serious false accept revokes the certificate. Overall failures
update the interval and revoke on threshold breach. Drift checks compare pose, label, visibility,
multi-person context, style, mask area, disagreement, and generator mix against the certificate corpus.

This can reduce manual work toward 1–10% of masks while retaining a measured error bound. It does not
promise zero human input: calibration and random auditing are how the system knows it remains correct.

## 7. Continuous Improvement

Residual corrections and audit outcomes update failure mining, specialist training, provider
reliability, Qwen exemplars/adapters, and tournament calibration. Retraining creates a new fingerprint
and requires a new certificate. Provider reliability is learned by label/context; pass-everything and
false-positive critics lose influence. Correction plans earn credit only when candidates improve
human-reference IoU/boundary F and pass all hard vetoes.

## 8. Implemented Control Surface

- `configs/autonomous_masks.yaml`: tournament, certificate, audit, and pseudo-label policy.
- `src/maskfactory/autonomy/calibration.py`: frozen audit certificates, Wilson bounds, and the complete
  autonomy-pipeline fingerprint. The fingerprint binds the VLM gate plus the MaskFactory source tree,
  autonomy/VLM/cloud/pipeline/ontology configs, model registry, dependency lock, and project manifest;
  a change to any component invalidates the prior certificate scope.
- `src/maskfactory/autonomy/tournament.py`: deterministic scoring, vetoes, margins, and outcomes.
- `src/maskfactory/autonomy/controller.py`: bounded correction rounds, candidate hash/ID deduplication,
  and deterministic stopping on selection, exhausted rounds, or no novel candidate.
- `src/maskfactory/autonomy/audit.py`: confidence-blind deterministic 2% sampling and immediate
  serious-failure/distribution-drift revocation.
- `src/maskfactory/autonomy/adapters.py`: converts real strict-PNG candidates and protected anatomy
  into hash-bound tournament evidence with consensus, boundary, topology, and overlap measurements.
- `src/maskfactory/autonomy/lifecycle.py` plus `autonomy_lifecycle.schema.json`: writes validated,
  non-gold lifecycle sidecars and enforces scoped certificate/revocation lookup.
- `src/maskfactory/autonomy/operations.py`: builds deterministic weekly audit queues, processes exact
  human outcomes, immediately revokes unsafe strata, and emits governed retraining tasks. Revocation
  markers are pipeline-fingerprint-specific so concurrent or historical scopes cannot overwrite and
  accidentally re-enable one another.
- `src/maskfactory/autonomy/pseudo_dataset.py`: builds hash-verified train-only pseudo-label manifests;
  frozen human holdout overlap is a hard error and calibrated masks retain reduced loss weight.
- `maskfactory autonomy build-certificate`: creates a hash-bound label/context certificate.
- `maskfactory autonomy tournament`: creates an auditable selection decision.
- `maskfactory autonomy build-audit-queue`, `process-audits`, and `build-pseudo-dataset`: operate the
  recurring audit, revocation, and semi-supervised retraining lifecycle.
- S11 now writes real baseline/local/cloud candidate masks, runs the tournament per label, and emits a
  validated lifecycle sidecar. It remains residual-only until an exact unrevoked certificate is supplied.
- `tools/weekly_qa.ps1` creates the certificate-blind weekly audit sample on the registered cadence.

Implementation readiness is not a current 95%-confidence performance claim. Image1 supplies one human
reference; certificates require hundreds of independent human-truthed autoaccepted cases per stratum.
