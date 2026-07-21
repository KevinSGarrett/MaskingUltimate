# Video Segmentation / Tracking Horizon Decision

Date: 2026-07-12

> **Doc-24 supersession (2026-07-17):** the D1–D11, human-keyframe, CVAT, approved-video-gold,
> fixed-real-clip, and operator-cost prerequisites below are retained only for optional
> `independent_real_accuracy`/human-training-gold or post-core scale claims. They do not gate
> `core_autonomous_runtime`. Core video/frame/span masking uses exact source-video/frame/PTS/timebase
> identity, track/owner continuity, temporal hard QA, qualified autonomous critics, perturbation and
> seeded-drift tests, bounded re-anchoring/repair, typed abstention, exact operational certificates,
> revocation, and the adopted bridge. Human keyframes or CVAT cannot block or revoke this route.

Core decision: **GO FOR DOC-24 CONTRACT/RUNTIME IMPLEMENTATION; PRODUCTION USE ONLY AFTER THE EXACT
AUTONOMOUS TEMPORAL CERTIFICATE AND BRIDGE GATES PASS.** The historical no-go remains only for an
independent real-video accuracy, human/training-gold, or operator-cost claim.

Historical decision: **NO-GO for implementation or production promotion now; architecture-compatible
re-evaluation after D1–D11.** This wording is retained as the optional-profile historical record and
does not redefine the doc-24 autonomous-core gate.

SAM2 tracking capability alone remains insufficient. Core must implement and qualify the temporal
package, track identity/ownership authority, drift QA, repair/abstention, certificate, invalidation,
and bridge contracts before production use. A temporal CVAT workflow, measured per-frame human-review
cost, approved video gold, and open legacy image DoD remain optional evidence; their absence does not
prevent contract work, autonomous fixtures, fault injection, or an operationally certified route.

## Required temporal package schema

Each clip needs immutable `video_id`, source hash, frame rate/time base, and source governance.
Each frame package adds `frame_index`, timestamp, `track_id`, keyframe status, adjacent-frame
links, propagation provenance, and visibility. Track IDs remain stable through exits/re-entries;
an identity switch is a hard failure, never an automatic merge. Existing per-person
`instances/pN` remains nested beneath each frame.

## Required pipeline and QA

Raw SAM2 propagation is draft-only. The autonomous controller selects/re-anchors keyframes from
scene cuts, occlusion, identity/topology changes, confidence decay, and temporal critic evidence;
each repair is bounded and must preserve immutable accepted parents. Checks cover temporal flicker,
area jumps, boundary velocity, track continuity, identity switches, ownership, topology, transforms,
protected regions, and drift against exact synthetic/metamorphic or other qualified reference
evidence. Unresolved ambiguity abstains. Human keyframes and CVAT clip/keyframe review may create
optional human/training gold but are never required for operational certification.

## Optional human-workflow review-cost model

For optional human-workflow/scale claims, measure keyframes per minute by motion/occlusion tier,
correction minutes per keyframe, skim seconds per propagated frame, re-anchor frequency by body
part, storage/QA cost, and total operator minutes per approved video minute. These measurements and
the image G1 baseline have no core-runtime authority.

Core qualification proceeds under MF-P6-09/MF-P6-12 with governed available or generated clips,
deterministic truth/perturbation fixtures, image/video-time identity, seeded track/ownership/drift
faults, restart/revocation/rollback drills, and zero hard-veto bypass. Operational promotion requires
all applicable temporal/per-frame hard checks clean and exact certificate scope; otherwise repair or
abstain. The optional independent real-video/human-gold claim still requires its separately governed
10-clip corpus, reviewed truth, measured drift, and operator-cost evidence and cannot change core.
