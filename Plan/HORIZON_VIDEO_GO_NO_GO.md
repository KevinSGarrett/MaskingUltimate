# Video Segmentation / Tracking Horizon Decision

Date: 2026-07-12

Decision: **NO-GO for implementation or production promotion now; architecture-compatible
re-evaluation after D1–D11.**

SAM2 tracking capability alone is insufficient. MaskFactory currently has no temporal package
schema, track identity authority, drift QA, temporal CVAT workflow, measured per-frame review
cost, or approved video gold. The live tracker also has multiple image-level Definitions of Done
open. Starting video now would multiply unresolved review and training work.

## Required temporal package schema

Each clip needs immutable `video_id`, source hash, frame rate/time base, and source governance.
Each frame package adds `frame_index`, timestamp, `track_id`, keyframe status, adjacent-frame
links, propagation provenance, and visibility. Track IDs remain stable through exits/re-entries;
an identity switch is a hard failure, never an automatic merge. Existing per-person
`instances/pN` remains nested beneath each frame.

## Required pipeline and QA

SAM2 propagation is draft-only. Human keyframes anchor each track; occlusion, scene cuts,
identity switches, topology changes, and confidence decay force a new keyframe. New checks cover
temporal flicker, area jumps, boundary velocity, track continuity, identity switches, and drift
against reviewed keyframes. CVAT must support clip/keyframe review without weakening per-frame
gold approval.

## Required review-cost model

Measure keyframes per minute by motion/occlusion tier, correction minutes per keyframe, skim
seconds per propagated frame, re-anchor frequency by body part, storage/QA cost, and total
operator minutes per approved video minute. No target is valid before the image G1 baseline.

Re-evaluate only after D1–D11. A first pilot requires 10 governed adult clips across motion and
occlusion tiers. Promotion requires zero identity switches in approved gold, all temporal and
per-frame hard checks clean, measured drift thresholds, and an approved operator-cost target.
