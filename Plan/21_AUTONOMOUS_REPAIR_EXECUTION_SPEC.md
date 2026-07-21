# MaskFactory Autonomous Repair Execution Specification

**Status:** approved implementation contract
**Applies to:** S05, S09, S10, S11, S12, CVAT review drafts
**Authority:** machine repair may improve a reversible non-gold review draft but grants no gold
authority itself; downstream gold authority is either human-anchor approval or an exact-scope,
unexpired, unrevoked autonomous-certification gate under documents 20 and 22

## 1. Purpose and success condition

The subsystem is not complete when a model merely describes a bad mask. It is complete only when it
repeatedly inspects the exact current candidate, creates pixel-level alternatives, rejects unsafe
alternatives, selects the best evidence-backed alternative, and gives the human a reversible non-gold
draft or certificate-gated candidate. The operational target is minimum correction time without
weakening hard QA, human-anchor truth, or autonomous-certification requirements.

Experimental committee convergence and calibrated 95% acceptance are separate evidence rules. Raw
model confidence is not a calibrated probability and must never be relabeled as one. Committee
convergence requires all of these to concern the same exact candidate:

1. Complete-map deterministic QA introduces no new BLOCK and does not regress map score.
2. Local Qwen and every enabled, available, exact-image-eligible cloud reviewer return `pass` at or
   above the configured advisory floor (0.80 initially), with at least three independent reviewers.
3. Every required reviewer participates; missing, malformed, failed, or uncertain output is not pass.
4. Format, topology, components, ROI, protected-region, area, and ontology guards pass.

Committee convergence alone may publish only a review draft. A real 95% claim requires a current
certificate computed from frozen image-disjoint human-anchor truth and one-sided confidence bounds.
Uncalibrated convergence cannot approve gold, clear a BLOCK, or create holdout truth. A calibrated
result may become `autonomous_certified_gold` only through the separate exact-scope certificate gate;
repair never grants that authority directly and never creates human-anchor or holdout truth.

## 2. Architecture

```text
S05 geometry ROI + S06 exact atomics/parent-union support + S09 baseline
                       |
             provenance-preserving candidates
                       |
              local guards and SAM2
                       |
          transactional complete PART map
                       |
                 S10 hard QA
                       |
             candidate tournament
                       |
  exact-winner Qwen + Gemini + OpenAI + Anthropic review
              | unanimous exact-candidate pass + QA
              |------------------> reversible S12/CVAT draft
              |
              | fail/uncertain/correction plan
              v
       new ROI polygon/SAM2 candidates -> repeat
```

The cost-saving cloud diagnosis cascade may stop on agreement. The final-candidate committee must call
every enabled reviewer; a vote from an earlier or different candidate cannot be inherited.

Whole-hand and whole-foot specialist masks are parent-union support, not exact atomic candidates.
They may be shown to reviewers and used to localize repair, but cannot be relabeled as `hand_base`,
`foot_base`, a finger, or `toes`. A whole bare foot becomes exact `foot_base` and `toes` candidates
only after the configured COCO WholeBody heel/big-toe/small-toe landmarks produce a valid,
provenance-recorded metatarsophalangeal split. Whole-hand support remains support-only until an
equally validated palm/finger decomposition exists.

## 3. Spatial repair contract

The current mask is evidence, not spatial truth. Repair regions are selected from S05 character-side
geometry, validated specialist boxes, pose chains, then current-mask geometry only as a last resort.
Production requires S05 geometry and the promoted-person box. The padded ROI is clipped to source and
is the actual evidence focus and SAM2 box prompt.

Cloud coordinates are integers in 0..1000 normalized within the ROI. Qwen correction points are
full-source coordinates inside it. Positive SAM2 points outside it are rejected.

Ordinary refinement and catastrophic reconstruction use different change limits. Component-overflow or
ontology-area catastrophes may use the reconstruction limit but still must stay inside the anatomy ROI,
fit person-relative area bounds, and avoid immutable protected pixels.

## 4. Pixel tools and proposal authority

Reviewers never edit maps directly. They may emit ROI-normalized polygons, positive/negative SAM2
points, deterministic small-component removal, or `human_review`/`none`. Each result is an isolated
strict-binary proposal with reviewer, model, prompt, tool, and ROI provenance. Empty, wrong-size,
outside-ROI, excessive-change, protected-overlap, component-overflow, and area-implausible results are
rejected before the tournament.

Atomic boundary guards run before reviewer acceptance. When the companion atomic label is visible and
pose evidence is confident, `foot_base` containing both toe landmarks is vetoed as
`MF-BOUNDARY-foot_mtp-whole_foot_as_foot_base`; `toes` containing the heel is vetoed; and `hand_base`
containing multiple fingertips is vetoed. Closed shoes do not trigger the bare-foot/toe split guard.
These guards are deterministic semantic authority and cannot be overridden by unanimous model votes.

Point plans have explicit operation semantics. `boundary_too_tight`/`missing_visible_area` plans are
additive deltas: ROI-clipped, positive-anchored SAM components are unioned with the safe current mask.
Removal/contamination defects use replacement semantics. Every positive/negative point is verified on
the result. Multi-point misses may retry individual points against the cached embedding; unresolved
points reject the proposal rather than weakening the contract.

## 5. Transactional label reassignment

A mislabeled part cannot be repaired if every incumbent label is treated as immutable. Candidate
application is therefore atomic:

1. Remove old target-label pixels.
2. Inside the approved ROI, displace ordinary draft labels covered by the candidate.
3. Refuse collision with `other_person`, `accessory_or_prop`, `occluding_object`, `support_surface`, or
   auxiliary protected proposals.
4. Limit displaced labels, record their pixel counts, write the target, and rerun complete-map QA.

A failed label transaction rolls back that label. The S09 base remains byte-identical and recoverable.

## 6. Bounded convergence controller

Each label has at most 12 candidates and three committee rounds. Every round rebuilds the tournament,
selects the best eligible candidate, composes and QA-checks it, renders exact candidate evidence, runs a
fresh Qwen audit, and runs the all-provider committee when eligible. Votes bind to candidate ID/path/hash
and round. If all required reviewers pass at the advisory floor and complete-map QA passes, the
candidate reaches experimental committee convergence. This is not a calibrated 95% claim. Otherwise
the rejected winner is downgraded, every executable correction is materialized and guarded, duplicates
are removed, and the loop repeats. Rejected tool reasons and missing/malformed reviewer results are fed
into the next round so a provider must replan instead of repeating an unsafe correction.

The loop stops on convergence, no eligible candidate, no novel safe proposal, candidate cap, round cap,
eligibility failure, provider failure, or budget exhaustion. Nonconvergence routes to a human and never
fabricates confidence.

Reviewer prompts include the ontology label's side, parent union, expected area, component limit,
boundary-rule code, and human-readable boundary contract. A local VLM transport/timeout failure is an
explicit confidence-0 uncertain vote; it cannot crash the job or become pass.
If a local response violates the strict schema, the single governed retry names the exact violation
(JSON, missing/extra key, observation, coordinate type/range, or verdict/tool conflict) so the model can
repair its serialization without relaxing validation. A second invalid response remains uncertain.

## 7. Selection and broken-baseline progress

The tournament uses independent-source diversity, mask consensus, boundary agreement, pose consistency,
critic support, and hard vetoes. Specialist outputs remain explicit provenance-bearing candidates. A
failed committee review downgrades the exact winner so it cannot be selected repeatedly unchanged.

QA evaluates the transactional complete map. Against an already-broken baseline, a non-regressing
candidate may advance only as review-draft repair progress when it introduces no new BLOCK IDs and its
complete-map score remains within the configured 0.001 numerical tolerance. This status never grants
acceptance authority.

## 8. CVAT publication and rollback

S12 may publish only `machine_generated_review_draft_non_gold` output. Existing-task publication must:

1. Refuse completed, validation, accepted, frozen, or gold tasks.
2. Refuse to overwrite any target PART shape marked human/manual.
3. Export a CVAT backup and raw annotations before mutation.
4. Replace only untouched automatic PART shapes and retain non-PART annotations.
5. Verify the exact semantic shape set after the write.
6. Restore old annotations immediately on mismatch.
7. Record hashes, counts, backup, task ID, and non-gold authority.

Once a person has edited a task, autonomous results must use a new task or comparison evidence.

## 9. Cost, privacy, and availability

Cloud transmission remains default-deny and requires exact source hash, rights evidence, provider approval,
credential, and budget. Spend is reserved before dispatch; unknown usage is
conservatively charged. Definite pre-billing HTTP rejections (including 400/401/403/404/409/422/429)
release their reservations; malformed or unknown post-dispatch usage remains charged at the reserved
maximum. The daily hard limit remains $15. One shared job quota caps all diagnosis and committee calls,
with a second per-label cap. When autonomous exact-candidate convergence is active, the duplicate cloud
diagnosis cascade is skipped by default. Budget or quota exhaustion terminates repeated no-novel-candidate
rounds. A missing reviewer is not a pass.

## 10. Evidence, calibration, and acceptance

Runs retain baselines/candidate hashes, plans, ROI, guards, complete-map QA, reviewer votes, spend,
tournament rankings, convergence rounds, publication audits, and rollback evidence. The production gate
must be rebuilt after this controller/prompt/evidence change using exactly 20 distinct frozen,
QA-passing, human-approved gold packages.

Acceptance tests must prove ROI reconstruction, ROI-clipped positive-anchored SAM output, additive
boundary repair, point-adherence rejection, immutable collision refusal,
ordinary-label transactional reassignment, all-provider exact-candidate review, failed-winner downgrade,
bounded correction/replanning, parent-union support isolation, pose-backed foot atomic splitting,
atomic-boundary vetoes, reviewer transport fail-closed behavior, bounded cloud calls, honest separation
of advisory convergence from calibrated 95%, CVAT backup/verification/rollback, human-edit refusal,
full test/lint/format/tracker success, and a live non-mutating shadow run.

## 11. Task 23 semantic regression record

The Task 23 v6 shadow run is invalidated as convergence evidence. Its accepted
`right_foot_base` candidate contained the visible toes: four reviewers unanimously passed the same
semantically wrong mask because the prompt and deterministic guards did not yet enforce the MTP
boundary. The artifact remains immutable for audit, but it may never be published, trained from,
promoted, or treated as gold. The v8 replay used the pose-backed base/toes split and correctly left
both labels in `residual_human_queue`; the base received a local pass but cloud participation was
blocked by the hard budget limit, while toes remained locally uncertain. No Task 23 annotations or
review package were changed by either replay.
