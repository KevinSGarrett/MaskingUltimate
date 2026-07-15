# Document 18: Adult Anatomy Ontology v2 Specification

**Target ontology:** `body_parts_v2`

**Base ontology:** `body_parts_v1`

**Status:** approved design; gated migration, not an ad-hoc edit to the active v1 map

**Scope:** confirmed-adult source images only

---

## 1. Decision and non-negotiable principles

MaskFactory will support observable adult anatomy as an append-only ontology upgrade. Existing
PART IDs `0..55` never move. Nine visible-surface labels are appended as IDs `56..64`, producing
exactly **65 PART logits including background ID 0**. The old phrase "57-class (56 PART IDs plus
background)" is invalid because v1 ID 0 is already background; v2 removes that ambiguity.

The upgrade preserves the constitutional rules:

1. Only confirmed-adult images may provide anatomy evidence. A yes/uncertain age screen stays quarantined.
2. Atomic gold is visible-pixel-only. No anatomy is invented beneath clothing or occlusion.
3. Clothing owns clothing pixels in the MATERIAL map. A contour through fabric is not visible anatomy truth.
4. A missing mask never means absent. Every v2 label has an explicit reviewed state.
5. `unreviewed_for_v2` is not a negative label and cannot enter v2 supervised training.
6. Ambiguous pixels become ignore index `255`; the annotator never guesses a boundary or side.
7. Projected/amodal estimates, if ever enabled, remain separate and can never become visible-mask gold, training truth, or approval evidence.
8. Anatomy applicability is never inferred from name, gender presentation, clothing, or model guess. `not_applicable` requires human-reviewed evidence.

## 2. Append-only PART registry

| ID | Canonical label | Boundary and exclusivity rule | Side | Parent/derived group |
|---:|---|---|---|---|
| 56 | `left_areola` | Visible areolar ring; explicitly excludes nipple pixels | character-left | `both_areolae` |
| 57 | `right_areola` | Visible areolar ring; explicitly excludes nipple pixels | character-right | `both_areolae` |
| 58 | `left_nipple` | Visible nipple only; carved out of left areola/breast | character-left | `both_nipples` |
| 59 | `right_nipple` | Visible nipple only; carved out of right areola/breast | character-right | `both_nipples` |
| 60 | `vulva` | Visible external vulvar anatomy only; never the internal vaginal canal | center | `external_genitalia_visible` |
| 61 | `penis_shaft` | Visible shaft/foreskin surface, excluding visible glans | center | `penis_visible` |
| 62 | `glans_penis` | Visible glans only; no inference beneath foreskin or clothing | center | `penis_visible` |
| 63 | `left_scrotal_region` | Character-left visible scrotal surface; not an internal testicle mask | character-left | `scrotum_visible` |
| 64 | `right_scrotal_region` | Character-right visible scrotal surface; not an internal testicle mask | character-right | `scrotum_visible` |

All nine labels are `atomic_exclusive`, enabled in v2, and belong to the PART-map exclusivity
group. Existing `left_breast`, `right_breast`, and `pelvic_region` masks must carve out pixels
owned by these new atomics. The full surface remains available through derived unions.

### 2.1 User-facing aliases

Aliases are accepted for search/UI convenience but never create duplicate truth classes:

| User term | Canonical authority | Important meaning |
|---|---|---|
| `vagina` | `vulva` | External visible region only; no internal vagina segmentation |
| `penis head` / `penis_head` | `glans_penis` | Visible glans |
| `penis` | `penis_visible` | Derived union, not hand-authored |
| `testicles` | `scrotum_visible` | External scrotal surface; not internal organs |
| `left_testicle` | `left_scrotal_region` | UI alias only; external character-left surface |
| `right_testicle` | `right_scrotal_region` | UI alias only; external character-right surface |
| `areolas` | `both_areolae` | Derived union |
| `nipples` | `both_nipples` | Derived union |

APIs and manifests emit canonical names. Alias resolution happens before validation and must be
recorded in provenance when a user supplied an alias.

## 3. Derived unions

These outputs are script-generated and never manually annotated:

- `both_areolae = left_areola | right_areola`
- `both_nipples = left_nipple | right_nipple`
- `left_nipple_areola_complex = left_areola | left_nipple`
- `right_nipple_areola_complex = right_areola | right_nipple`
- `both_nipple_areola_complexes = left_nipple_areola_complex | right_nipple_areola_complex`
- `left_breast_full = left_breast | left_areola | left_nipple`
- `right_breast_full = right_breast | right_areola | right_nipple`
- `both_breasts_full = left_breast_full | right_breast_full`
- `penis_visible = penis_shaft | glans_penis`
- `scrotum_visible = left_scrotal_region | right_scrotal_region`
- `external_genitalia_visible = vulva | penis_visible | scrotum_visible`
- `pelvic_anatomy_visible = pelvic_region | external_genitalia_visible`

Existing `both_breasts` remains the v1 union of IDs 5 and 6 for compatibility. New callers that
need complete v2 breast surface use `both_breasts_full`.

The inactive machine authority is `configs/derived_v2.yaml`; it must remain byte-identical to the
generator before activation. It contains exactly one executable formula for every v2
`derived_union`. `full_body_parts_visible`, `person_full_visible`, and `visible_body_skin` cover all
visible atomic PART IDs `1..49`, `54..55`, and `56..64`, while protected QA IDs `50..53` remain
excluded. The active `configs/ontology.yaml` and `configs/derived.yaml` remain v1 until the complete
MF-P7-06.06 gate passes.

Activation readiness is rehearsed only on isolated copies. The ontology/derived pair is staged and
validated together, exact post-replace bytes are verified, and any first-write, second-write, or
post-replace validation failure restores both exact v1 inputs. Rehearsal evidence cannot activate v2;
the eventual production switch must remain part of the complete atomic registry/config/workflow/model
activation and one-command rollback transaction.

## 4. Visibility and review states

The v2 manifest vocabulary is:

`visible | partially_visible | occluded | occluded_by_clothing | cropped_out | not_visible |
not_applicable | unreviewed_for_v2 | ambiguous_do_not_use`

| State | Mask rule | Training rule |
|---|---|---|
| `visible` | Nonempty exact visible mask required | Positive/negative pixel supervision allowed |
| `partially_visible` | Mask only visible pixels | Visible pixels supervised |
| `occluded` | No hidden pixels; optional visible remainder only | Hidden extent never supervised |
| `occluded_by_clothing` | Anatomy mask must be null; garment owns pixels | Reviewed non-visible state, never a projected positive |
| `cropped_out` | Mask null | Valid reviewed non-visible state |
| `not_visible` | Mask null; view/occlusion explains why | Valid reviewed non-visible state |
| `not_applicable` | Mask null; human evidence required | No positive expectation; never inferred from presentation |
| `unreviewed_for_v2` | Mask null | Package is ineligible for v2 supervised train/val/test |
| `ambiguous_do_not_use` | Uncertain zone recorded separately | Pixels burn to `255`; excluded from metrics/loss |

`fully_occluded` is accepted as an input alias for `occluded`, but canonical manifests write
`occluded`. Older v1 packages migrate all nine new labels to `unreviewed_for_v2`; they are never
automatically marked absent, occluded, or not applicable.

## 5. CVAT annotation SOP

For every promoted person and every v2 label, the reviewer must select one state before approval.

1. Work at 400–800% zoom for nipple/areola and genital boundaries.
2. Label only exposed visible surface. Underwear, swimwear, sheer fabric without a reliable skin boundary, and ordinary clothing remain MATERIAL pixels.
3. Areola is the pigmented ring excluding the nipple. Nipple is a separate carve-out. If the boundary cannot be resolved, mark the uncertain complex `ambiguous_do_not_use`.
4. Use `vulva` for observable external anatomy. Do not outline an imagined vaginal canal.
5. Shaft excludes visible glans. If the glans is covered, label only visible shaft/foreskin.
6. Split scrotal surface by the visible midline/raphe and character perspective. If side cannot be defended, mark the uncertain scrotal zone `ambiguous_do_not_use`; never force a split.
7. Pubic hair or another body part owns visible occluding pixels according to normal z-order.
8. Covered anatomy uses `occluded_by_clothing` with no mask. A fabric contour is not sufficient.
9. A missing/cropped finger follows the same system: visible mask, explicit occluded/cropped state, or ignored ambiguous region. Omission is never an implicit negative.
10. CVAT export refuses approval until all 65 PART entries have a valid state and every v2-visible entry has a mask.

## 6. Automatic QA additions

The v2 QA battery adds hard checks:

- **QC-V2-001 — state completeness:** all IDs `0..64` represented; no `unreviewed_for_v2` in a v2-approved package.
- **QC-V2-002 — state/mask consistency:** visible states require a nonempty mask; null-mask states prohibit one; ambiguity requires an ignore region.
- **QC-V2-003 — atomic exclusivity:** new labels do not overlap any PART atomic.
- **QC-V2-004 — nipple/areola topology:** nipple is adjacent to or enclosed by its same-side areolar ring after scale-aware tolerance; neither crosses the body midline.
- **QC-V2-005 — breast carve-out:** breast atomics exclude same-side areola/nipple; `*_breast_full` restores the surface.
- **QC-V2-006 — genital carve-out:** pelvic_region excludes IDs 60–64; the pelvic union restores the complete visible region.
- **QC-V2-007 — penis topology:** glans and shaft are exclusive, adjacent when both visible, and remain one anatomical component unless honestly occluded.
- **QC-V2-008 — scrotal side integrity:** left/right obey character perspective; unresolved sides must be ambiguous.
- **QC-V2-009 — clothing authority:** `occluded_by_clothing` requires null anatomy mask and visible clothing material in the reviewed region.
- **QC-V2-010 — no hidden-authority leak:** projected/amodal anatomy cannot satisfy visible-mask, gold, training, metric, or approval requirements.
- **QC-V2-011 — adult governance:** every positive ID 56–64 references a `clear_adult` intake decision and allowed source origin.
- **QC-V2-012 — alias canonicalization:** maps/manifests never persist aliases as labels.

Seeded-defect fixtures must exercise every new check before activation.

## 7. Dataset and training contract

### 7.1 Eligibility

- A package may train v2 only after all nine new labels are human-reviewed and none remains `unreviewed_for_v2`.
- v1 packages remain useful for v1 pretraining and existing-class training. They do not silently become v2 negatives.
- Clothed v2-reviewed images contribute existing PART/MATERIAL supervision and explicit non-visible anatomy states. Nude/partially nude images provide positive anatomy pixels.
- Split assignment remains identity/pHash-grouped; near duplicates never cross train/val/test.

### 7.2 Model shape and sampling

- Main semantic head: `num_classes: 65` (IDs `0..64`, background included).
- Ignore index: `255` everywhere.
- Rare-class sampler: at least 50% of v2 fine-tune crops contain IDs 56–64 once inventory supports it; retain whole-body batches to prevent forgetting.
- Use inverse-square-root class weighting capped at ×8, anatomy-focused crops, and balanced anatomy/view/pose/skin-tone/lighting/occlusion coverage.
- Never balance by fabricating a positive beneath clothing.

### 7.3 Evidence gates

- Pilot mechanics: 20–30 v2-reviewed adult images spanning clothed, exposed, occluded, cropped, not-visible, not-applicable, and ambiguous states.
- Production-data target: at least 50–100 clear positive instances per new atomic class, with a dedicated identity-separated hard-case holdout.
- Publish per-class IoU, boundary-F, positive recall, false-positive rate on clothed images, and left/right swap rate. Aggregate mIoU alone cannot pass.
- No production promotion while any new class lacks a measured holdout or while false positives appear systematically on clothed images.

## 8. Migration from v1

1. Freeze and hash active v1 ontology, schemas, CVAT label map, dataset versions, and champions. Existing IDs/packages remain readable.
2. Generate v2 with unchanged IDs `0..55`, appended IDs `56..64`, new unions, aliases, states, and QA rules. CI proves no old ID/name changed.
3. Add manifest `reviewed_ontology_version` and per-class review authority. A migrated v1 package receives `unreviewed_for_v2` for all nine additions.
4. Regenerate CVAT labels and create a versioned v2 project. Do not mutate an open v1 task in place.
5. Re-review selected packages. Only fully resolved packages may freeze as `body_parts_v2` and enter v2 datasets.
6. Build a new dataset version; never rewrite an existing DVC dataset/tag.
7. Train/evaluate a 65-logit challenger. v1 champions continue serving until v2 passes every gate.
8. Update serving/ComfyUI after registry promotion. Responses expose ontology version and reject labels unsupported by the champion.
9. Run rollback: restore v1 champion pointers and prove v1 workflows remain byte-compatible.

## 9. Required system changes

Activation requires coordinated changes to:

- ontology source/generator/YAML/loader, aliases, flip pairs, visualization
- manifest/QA/failure/coverage schemas and validators
- CVAT project labels, attributes, push/pull, SOP, versioned migration
- S03/S05/S06/S07/S09 candidates, anatomy crops/prompts, fusion and carve-outs
- map/binary export, derived formulas, inpaint selectors, package verifier
- QC/topology/panels/seeded defects, VLM vocabulary and calibration
- dataset builder, v2 eligibility, augmentation, 65-class configs and metrics
- leaderboard, holdouts, promotion gates, registry vocabulary hashes
- serving API validation/provenance and champion loading
- ComfyUI selectors, package browser, workflows and unions
- coverage/failure mining/acquisition, backup/restore/reindex/GC
- all literal 56/57 assertions, D1 wording, tests, fixtures, docs and tracker items

The executable sequence is in `Plan/OntologyV2/IMPLEMENTATION_CHECKLIST.md`. The proposed
machine-readable delta is `Plan/OntologyV2/ontology_v2_additions.yaml`.

## 10. Activation gate

`body_parts_v2` is active only when every checklist item has specific evidence, generated files
are drift-clean, v1 compatibility passes, the v2 CVAT pilot is reviewed, all seeded QA defects
are caught, a v2 dataset is immutable, and the 65-class challenger passes per-class and
clothed-false-positive gates. Until then, production manifests and models remain v1.
