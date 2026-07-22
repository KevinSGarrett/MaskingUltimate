# ULTIMATE MASKING SYSTEM — SELF-HOSTED VISUAL AUTHORITY AND RUNPOD MIGRATION

## Document 25: Evidence-Qualified Critics, Proposal Consensus, and Cloud Asset Reconciliation

This document is Kevin's 2026-07-21 MaskFactory amendment derived from the
self-hosted review and golden-mask plan. It supersedes fixed model-name claims
in docs 06 and 10 and in Instruction 13 wherever those claims conflict with
measured evidence. It also defines the permitted read-only AWS inventory and
the governed AWS-to-RunPod migration path.

Planning text, a downloaded checkpoint, a successful JSON parse, or rejection
of bad masks is not visual authority. A model earns a role only by passing the
frozen positive-and-negative calibration contract in this document.

## 1. Scope and project boundary

MaskFactory owns image-mask generation, visual mask criticism, bounded mask
repair, exact-output operational certification, package release, and rollback.
The broader pasted plan's image/video/audio generation, speech, music, and
general ComfyUI workflow-engineering lanes belong to `C:\Comfy_UI_Main` and
may consume MaskFactory only through the frozen bridge. They are not copied
into MaskFactory and cannot become MaskFactory completion gates.

Video matting providers such as Robust Video Matting remain horizon
challengers until the existing video go/no-go authority activates them. Image
masking and multi-person ownership remain the current MaskFactory product.

## 2. Source registration

The same technical and data rules apply to every source:

- the source must be lawfully usable under its recorded license or ownership;
- source bytes and provenance must be immutable and hash-bound;
- masks enter authority tiers only through the same format, ontology, QA,
  provenance, and certificate rules as every other source.

## 3. Visual-authority role hierarchy

The runtime exposes roles, not hard-coded brands:

| Role | Required behavior | Initial challenger family |
|---|---|---|
| fast screener | cheap defect localization and bounded repair plan; never a sole pass | Qwen3.6-35B-A3B |
| primary visual critic | complete target-contract and panel review | Qwen3.6/Qwen3.5 feasible deployment |
| independent juror | independently trained family; same-family variants do not create quorum | InternVL3.5 feasible deployment |
| senior arbiter | resolves critic disagreement only after deterministic gates | Qwen3.5-122B-A10B or 397B-A17B |
| deterministic authority | pixel, topology, ownership, transform, format, and provenance measurements | MaskFactory QA code |

`llava:13b`, `llama3.2-vision:11b`, and `qwen2.5vl:7b` are legacy
challengers only. They retain no autonomy role solely because earlier files
called them primary, fallback, or high-end. The measured hand-mask result of
zero positive passes and repeated scene hallucination caps the current legacy
stack at `VISUAL_CRITIC_BLOCKED` until a new frozen calibration passes.

No weighted score, VLM vote, senior-model answer, or consensus count may clear
a deterministic hard veto. Missing, malformed, timed-out, truncated,
hallucinated, or scope-incomplete reviews are abstentions, never passes.

## 4. Hardware-qualified deployment tiers

Model catalog presence and hardware feasibility are separate facts.

### 4.1 Current single-GPU RunPod tier

The current RTX 6000 Ada provides about 48 GiB VRAM. A model may enter this
tier only after its exact quantization, runtime, context, image budget, peak
VRAM, latency, and deterministic response hash are measured on that GPU.
Qwen3.6-35B-A3B and a smaller independent InternVL3.5 checkpoint are
challengers, not assumed winners.

### 4.2 Multi-GPU arbitration tier

The official Qwen3.5-122B-A10B FP8 repository is about 127 GB and therefore
does not fit on the current 48 GiB GPU. Qwen3.5-397B-A17B FP8 and
InternVL3.5-241B-A28B likewise require a qualified multi-GPU RunPod class.
They remain planned senior/independent challengers until an exact pod class,
tensor-parallel runtime, cost ceiling, model hash, and live benchmark exist.
Never substitute CPU offload or a smaller model while retaining the larger
model's name or authority claim.

### 4.3 Service boundary

Self-hosted critics use a loopback or private authenticated endpoint. Model
servers must not expose an unauthenticated public port. Credentials remain in
environment-only secret storage and never appear in requests, evidence, logs,
tracker notes, or Git.

## 5. Golden-mask proposal stack

For every target label and person instance, MaskFactory creates hypothesis-
distinct proposals when the providers are installed and eligible:

1. semantic/open-vocabulary discovery from official SAM 3.1;
2. incumbent point/box/mask refinement from SAM 2.1;
3. fine-boundary or alpha proposals from SAM2Matting and qualified matting
   challengers;
4. temporal/identity-aware proposals from MatAnyone2 or PDFNet only where
   their input contract applies;
5. silhouette/hair proposals from qualified BiRefNet HR-matting, MODNet, or
   other registered specialist challengers;
6. existing parsing, pose, geometry, protected-region, and custom-model lanes.

At least three proposal paths are preferred, but correlated variants count as
one family. Missing optional providers reduce diversity and are recorded; they
do not authorize a fabricated proposal or a weaker silent substitute.

Every proposal records source/pixel identity, instance owner, label, provider,
checkpoint, runtime, prompt/ROI/points, coordinate transform, raw output hash,
normalized mask hash, latency, VRAM, and authority ceiling.

## 6. Disagreement and deterministic measurement

The controller builds a pixelwise disagreement map from eligible proposals
and computes, before visual review:

- binary/value/dimension integrity;
- connected components, holes, perimeter, compactness, and area ratios;
- boundary alignment and edge distance;
- foreground/background leakage;
- containment, adjacency, topology, side, protected-region, and exclusivity;
- person/character ownership and cross-instance bleed;
- proposal IoU, boundary disagreement, and uncertainty concentration;
- transform round-trip and source/panel hash integrity.

Uncertainty regions become bounded repair ROIs. Whole-mask regeneration is
forbidden when a local repair can preserve already accepted regions.

## 7. Positive-and-negative visual calibration

Every visual role and every bound prompt/controller revision must pass one
frozen, image-disjoint calibration manifest containing:

- real source pixels and evidence-qualified known-good masks that must pass
  rather than universally abstain;
- seeded boundary, leakage, missing-area, flood, wrong-label, wrong-side,
  anatomy, ownership, protected-region, and transform defects;
- small-part, hand, hair, contact, occlusion, crop, and multi-person cases;
- source, binary mask, translucent overlay, contour, full-context view, and
  uncertainty-region zooms;
- exact model, quantization, runtime, prompt, seed, panel, response, parser,
  and decision hashes.

The gate reports defect recall, precision, false-pass rate, good-mask pass
rate, abstention rate, per-defect coverage, latency, VRAM, and deterministic
replay. Passing only negative controls is insufficient. A critic that rejects
everything is unavailable, not safe. Role thresholds are frozen before the
run and cannot be adjusted from the observed answers.

The production semantic corpus must draw its labeled positive controls from
`C:\Comfy_UI_Main\MaskedWarehouse` (RunPod:
`/workspace/assets/MaskedWarehouse`) or from exact human-anchor/autonomous-
certified package bytes. It must retain source, annotation/base-mask, remap,
authority, partition, and qualification hashes for every case. The real-image
coverage, retrieval, benchmark, and hard-case source is `F:\Reference_Images`,
especially `F:\Reference_Images\Ultimate_Masking_Reference_Images` (RunPod:
`/workspace/assets/Reference_Images/Ultimate_Masking_Reference_Images`).
Synthetic geometric scenes may validate schemas, parsers, renderers, and
defect operators, but they are ineligible as valid positive controls for a
semantic critic role. Draft model outputs, `in_review` packages, rejected
outputs, and historical low-quality masks are also ineligible. A live runner
must fail closed when the real-source binding manifest is absent, hash-drifted,
synthetic, draft, or outside its declared authority scope.

MaskedWarehouse annotations retain `external_labeled_reference` authority and
may support bounded training and critic calibration after exact source-level
provenance, rights, remap/ontology, integrity, visual alignment, instance
identity, and split/leakage qualification. This use does not convert them into
operational gold or allow them to mint certificates. Reference-library images
remain no-truth inputs until independently paired with an authority-qualified
mask.

## 8. Review and bounded correction loop

Each review starts from a versioned target contract: target label, person
owner, visible-pixel rule, expected empty/nonempty state, protected neighbors,
allowed ROI, and edge behavior. Critics receive the contract plus source,
mask, overlay, contour, context, zooms, deterministic measurements, and
relevant proposal disagreements.

Critics return closed JSON containing verdict, per-dimension findings,
evidence-cited regions, uncertainty, and a bounded repair plan. They never
write pixels, mutate gold, clear hard QA, expand authority, or execute tools.
The repair controller may translate an allowed plan into new boxes, points,
ROI parameters, provider choice, or threshold changes; pixel tools create a
new candidate. The full deterministic and visual gate then reruns.

Stop on pass, typed abstention, no progress, duplicate hypothesis, time/round/
resource cap, or regression. Preserve the immutable parent and every rejected
candidate.

## 9. Golden-mask package and regression evidence

An accepted package includes binary masks, master maps, overlay/contour/zoom
panels, uncertainty map, measurements, proposal manifest, critic responses,
repair lineage, target contract, QA report, operational certificate when
earned, and exact source/output hashes. A VLM pass is never itself gold.

Structural QA, statistical risk certification, and multi-provider pixel
consensus do not prove that the selected pixels represent the declared anatomy
label. Before autonomous freeze and before training consumption, every package
must therefore carry a package-specific semantic-alignment report bound to the
exact source, final mask set, every active label and mask, label-aware panels,
deterministic QA, and a current primary-critic plus independent-family-juror
quorum. Every active label must pass. Missing or incomplete coverage, defect,
abstention, stale/revoked/same-family authority, hard veto, or hash drift
rejects the package from autonomous gold and training use.

Legacy frozen packages lacking `semantic_alignment_report_sha256` or
`critic_quorum_sha256` remain immutable historical evidence but are
quarantined from training and positive critic calibration until a new package
version passes this gate. Do not rewrite or delete the legacy version. This
prevents a geometrically good head, hair, or whole-person silhouette from
becoming torso or other body-part truth merely because structural QA and model
consensus passed.

Semantic requalification is bulk by default. The system groups all eligible
packages into deterministic hash-bound batches, renders label-aware panels and
contact sheets, runs the promoted primary high-capability critic and an
independent model over every case, automatically accepts exact label/pixel
matches, creates a new immutable relabeled version only when both critics and
hard QA support an unambiguous label, and otherwise rejects or abstains. A
single malformed or uncertain case becomes an exception row and does not stop
the remaining batch. Operator output is a compact batch summary plus exception
report; human review is an optional exception path, never the default
throughput dependency. `C:\Comfy_UI_Main\MaskedWarehouse` and
`F:\Reference_Images` plus their exact RunPod mirrors feed this same bulk lane
under their distinct truth-authority rules.

Regression includes the accepted target plus protected invariants: unchanged
identity/owner, untouched accepted regions, neighboring labels, materials,
transforms, instance exclusivity, and prior known-good fixtures.

## 10. AWS read-only inventory and AWS-to-RunPod migration

AWS authentication authorizes source discovery only. MaskFactory must not
start EC2, attach or snapshot EBS, alter S3, or execute MaskFactory workloads
on EC2. Read-only inventory may inspect instance metadata, EBS volume metadata
when permitted, known S3 buckets/prefixes, object metadata, sizes, timestamps,
ETags/checksums, and manifests to determine what RunPod lacks.

The migration workflow is:

1. inventory known AWS sources without enumerating or exposing credentials;
2. inventory the persistent RunPod volume and root disk separately;
3. classify each AWS object as MaskFactory-required, ComfyUI-only, duplicate,
   incomplete transfer, quarantined, or unknown;
4. verify license/provenance, expected role, exact checksum, required bytes,
   destination capacity, and filename/path mapping;
5. copy only explicitly selected objects from S3 to the persistent RunPod
   volume, never to the 20 GB container root;
6. verify destination hashes and write a migration receipt;
7. leave AWS unchanged and preserve restart-safe resumable transfer state.

Multipart/chunk transfers require a manifest, contiguous chunk set, total
size, whole-object checksum, and completion marker before assembly. Presence
of recent chunks is not completion evidence.

The authenticated July 21 inventory supersedes the earlier planning estimate:
the governed historical S3 bucket returns `NoSuchBucket`; EBS contents cannot
be inspected with the authorized read-only role and have no qualifying object
manifest; the persistent RunPod inventory already contains the governed
reference and MaskedWarehouse assets. The gap comparison therefore authorizes
zero transfers. Reopen migration only when a newly discovered object has exact
role, version, license/allowed-use, size, and integrity evidence.

## 11. RunPod storage, durability, and recovery

`/workspace` must be proven to be the persistent network volume before large
downloads or migrations. The small container root stores only runtime-local
packages and logs needed for the current boot. Large models, caches, datasets,
evidence, and resumable transfer state belong on `/workspace`.

Every long job runs under a managed durable supervisor with PID, stdout,
stderr, start command, environment identity, lock ownership, and restart
instructions. A successful process launch is not a completed output. On
failure, stop only the owned process and retain logs and partial-transfer
manifests.

## 12. Acceptance boundary

This amendment is complete only when:

- the critic hierarchy has at least one qualified primary and one genuinely
  independent qualified juror on available RunPod hardware;
- known-good and known-bad calibration cases meet frozen thresholds;
- the proposal/disagreement/targeted-repair loop passes deterministic,
  authority, and regression tests;
- the exact current RunPod stack can issue or abstain under the operational
  certificate contract without manual mask creation;
- selected AWS assets, if any, have verified RunPod destination hashes and a
  migration receipt;
- tracker, registry, release, and bridge artifacts bind the exact deployed
  bytes.

Until then, legacy visual-critic evidence remains bounded or blocked and no
planning, download, negative-only smoke, or model-size reputation is promoted
to runtime authority.

## 13. Canonical claim firewall and authority matrix

These names are the only current cross-project status vocabulary. A package,
trainer, service, bridge, report, or tracker entry must not shorten them to
`gold`, `approved`, `certified`, or `pass` without its exact tier, scope,
certificate ID, and package revision.

| State | Exact meaning | Authority ceiling |
|---|---|---|
| `source_reference` | Original image with no mask truth | retrieval/context only |
| `detection_proposal` | Box, point, prompt, pose, ownership hypothesis, or scene metadata | no pixel authority |
| `mask_candidate` | One provider-generated mask | draft only |
| `machine_verified_candidate` | Deterministic tournament gates passed | no semantic/gold authority |
| `strict_visual_pass_bounded` | Exact target passed a qualified primary and independent-family juror | no gold/certificate authority by itself |
| `operationally_certified_artifact` | Exact operational certificate for declared production uses | never training/human truth |
| `autonomous_certified_gold` | Exact immutable package passed the complete contract in section 14 | declared training/benchmark uses only; no human-accuracy claim |
| `human_anchor_gold` | Separately governed voluntary human authority | optional, never a default autonomous dependency |
| `abstained`, `quarantined`, `rejected` | Typed non-authority outcome | none |

Population statistics, provider consensus, contact sheets, VLM votes, and
operational certificates cannot upgrade an individually unreviewed mask.

## 14. Canonical autonomous-certified-gold contract

`autonomous_certified_gold` requires one closed, versioned, package-specific
record that binds every active label and the complete final mask set. It must
bind encoded and canonical decoded source identity; decoder/orientation/color/
ICC/alpha policy; image, person, and character-instance identity; ontology
version/hash and canonical label; label scale; laterality under character
perspective; visible/amodal and presence/absence/occlusion state; explicit
inclusions, exclusions, protected regions, overlap/containment/topology rules,
and truncation/contact/occlusion/crop context; complete invertible transform
chain and round-trip evidence; encoded and decoded mask identity; strict binary
geometry; immutable package revision and parent; exact provider/prompt/runtime
lineage; frozen per-label/context QA vector; current qualified primary and
independent-family juror certificates and responses; semantic-alignment report;
repair lineage; policy fingerprint; permitted uses; signer; validity; revocation
snapshot; and claim limits.

Every pixel change creates a new candidate and reruns deterministic QA,
ownership, complete-map recomposition, semantic review, critic quorum, package
verification, and certification. Missing, ambiguous, stale, revoked,
same-family, hash-drifted, contact-sheet-only, or partially covered evidence
abstains or quarantines. Historical packages missing package-specific
`semantic_alignment_report_sha256` or `critic_quorum_sha256` remain immutable
but are ineligible for training, champion, positive calibration, autonomous
gold metrics, and production mask authority until a new revision qualifies.

The 2026-07-22 live reconciliation corrects the earlier population boundary:
the 641 lifecycle/database identities now exactly match 641 materialized
primary packages under `data/packages`; there are zero lifecycle-only and zero
package-only identities. `data/packages_caa_iso220` is an exact 220-identity
subset retained for the earlier isolated training/audit run, not the complete
materialized population and not 220 additional packages. All 641 current
source and winner-mask hashes verify, but zero packages bind both current
semantic alignment and independent critic quorum, and zero retain their
recorded lifecycle byte hash. Therefore all 641—not only the isolated 220—are
quarantined from every authority-bearing use. Relative `package_truth` paths
are interpreted only beneath their declared primary package root; existence in
that context never repairs a stale lineage or missing semantic/quorum binding.

## 15. Per-label and per-context quantitative QA registry

`configs/autonomous_gold_qa_thresholds.yaml` is the single versioned registry
for deterministic quantitative QA. It resolves every enabled ontology label
through its mask type and explicit ontology metadata, then applies only named
context modifiers. It covers expected presence; area relative to image,
person, parent, and proposal; components and holes; owner containment;
protected, mutually exclusive, and cross-person overlap; laterality and
front/back consistency; parent/child coverage and atomic-map exclusivity;
boundary alignment, precision, recall, F-score, symmetric distance, and p95
edge error; underfill, overfill, leakage, missing visible area, unsupported
pixels; thin structures; topology; transform round-trip; perturbation
stability; duplicate person/mask detection; and exact complete-map
recomposition.

The initial `0.1.0` registry is a frozen engineering-prior candidate only. It
is explicitly `uncalibrated_no_gold_authority` and cannot authorize gold.
Every enabled label must resolve exactly, unknown or duplicated contexts fail
closed, and cross-person bleed remains zero. Qualification must bind frozen
positive/negative calibration evidence by label, context, domain, size,
occlusion/contact, and multi-person risk. Promotion creates a new immutable
registry version; observed qualification results may never rewrite this
candidate in place or lower thresholds to manufacture passes.
