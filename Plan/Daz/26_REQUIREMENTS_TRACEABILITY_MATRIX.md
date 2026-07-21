# Requirements Traceability Matrix

## 1. Use

Each requirement has one design authority, implementation area, verification family, and completion
artifact. Implementation may add tests but may not close a requirement without the named evidence.

## 2. Core architecture and autonomy

| ID | Requirement | Design | Implementation | Verification/evidence |
|---|---|---|---|---|
| RQ-001 | Bulk DAZ data uses F:\DAZ | 11 | paths/storage | root identity + tree diff |
| RQ-002 | MaskFactory repo stores code/schemas/docs only | 11,23 | ignore scanner | seeded source-file test |
| RQ-003 | No autonomous purchasing or billable action | 1,7,12 | no account/purchase API | schema/CLI surface review |
| RQ-004 | Installed assets are autonomously scanned | 13 | asset scanner | deterministic snapshot |
| RQ-005 | Dependencies/compatibility are automatic | 13,14 | registry graph | graph fixture suite |
| RQ-006 | Broken assets are isolated/retestable | 14,22 | quarantine state | failure/retest evidence |
| RQ-007 | Scenes are deterministic and replayable | 19,20 | recipe/worker | canonical recipe + replay hash |
| RQ-008 | Routine operation requires no UI clicks | 20 | scripted worker | unattended pilot |
| RQ-009 | Worker survives prompts/crashes/timeouts | 20,22 | watchdog/retry | failure-injection report |
| RQ-010 | Heavy GPU work is serialized | 20,27 | global lease | contention test |

## 3. Character and asset breadth

| ID | Requirement | Design | Verification/evidence |
|---|---|---|---|
| RQ-011 | Adult male and female figures supported | 12,16 | character matrix |
| RQ-012 | Broad body height/weight/muscularity/proportion | 16 | distribution report |
| RQ-013 | Adult age-appearance variation | 12,16 | category/control readbacks |
| RQ-014 | Broad skin/material response | 16 | inventory × scene coverage |
| RQ-015 | Hair length/texture/construction/facial hair | 16 | hair qualification matrix |
| RQ-016 | Clothed/partial/unclothed configurations | 16 | wardrobe-state coverage |
| RQ-017 | Tight/loose/layered/formal/casual/athletic/outerwear | 16 | garment-property coverage |
| RQ-018 | Male/female anatomy geometry | 15,16,21 | mapped golden fixtures |
| RQ-019 | Poses span static, locomotion, seated, floor, athletic | 17 | pose-family report |
| RQ-020 | Self-contact, person contact, and prop contact | 17 | geometry relationship fixtures |

## 4. Multi-person, camera, and image formation

| ID | Requirement | Design | Verification/evidence |
|---|---|---|---|
| RQ-021 | One through four promoted people | 17 | accepted count pilots |
| RQ-022 | All M/F composition families | 12,17 | complete combination matrix |
| RQ-023 | Separated/overlap/contact/crossed-limb scenes | 17 | relationship coverage |
| RQ-024 | Deterministic p0–pN prominence | 17,23 | permutation fixtures |
| RQ-025 | No cross-instance pixel ownership | 21,22 | full-image exclusivity |
| RQ-026 | Front/back/left/right/profile/three-quarter views | 18 | camera azimuth report |
| RQ-027 | High/low/level/rolled camera | 18 | camera elevation/roll report |
| RQ-028 | Wide/normal/portrait/telephoto perspective | 18 | focal-distance matrix |
| RQ-029 | Full/three-quarter/portrait/close/cropped framing | 18 | framing metrics |
| RQ-030 | Studio/indoor/outdoor/simple/complex backgrounds | 18 | environment coverage |
| RQ-031 | Soft/hard/back/rim/low/high/mixed lighting | 18 | lighting coverage |
| RQ-032 | Blur/noise/compression/resolution variants | 18,21 | transform replay fixtures |

## 5. Mapping and render truth

| ID | Requirement | Design | Verification/evidence |
|---|---|---|---|
| RQ-033 | Active ontology comes from canonical loader | 15,23 | snapshot/hash test |
| RQ-034 | Genesis mapping bound to topology fingerprint | 15 | changed-facet rejection |
| RQ-035 | Left/right uses character perspective | 15,22 | multi-view swap fixtures |
| RQ-036 | Clothing has PART territory + clothing MATERIAL | 15,21 | garment gold fixtures |
| RQ-037 | Hair transparency yields visible-pixel masks | 16,21 | alpha threshold suite |
| RQ-038 | RGB and semantic passes share frozen scene | 20,21 | scene-state hash |
| RQ-039 | Instance/PART/MATERIAL/protected are exact IDs | 21 | codec exhaustive test |
| RQ-040 | Depth and normals have declared coordinates | 21 | analytic primitive test |
| RQ-041 | Hidden/amodal geometry is separate and not trainable | 21,23 | export negative test |
| RQ-042 | Contact/occlusion derived from geometry | 17,21 | known-distance fixture |
| RQ-043 | v1 never emits v2-only IDs | 15,21 | code-table negative test |
| RQ-044 | v2 is separate and inactive by default | 15,23 | config/schema test |

## 6. QA and packaging

| ID | Requirement | Design | Verification/evidence |
|---|---|---|---|
| RQ-045 | Every accepted scene passes all required validators | 22 | acceptance certificate |
| RQ-046 | Semantic invariants scan every pixel | 22 | deliberate pixel defects |
| RQ-047 | Repairs are bounded and replayable | 22 | retry-history fixture |
| RQ-048 | Partial/corrupt output cannot be accepted | 20,22 | process-kill tests |
| RQ-049 | Package file map/hashes are exhaustive | 22,23 | tamper tests |
| RQ-050 | Shared scene derives consistent per-person packages | 21,23 | complement/hash fixtures |
| RQ-051 | Scene variants/instances remain one split group | 23 | builder split tests |
| RQ-052 | Asset/mapping changes enumerate descendants | 12,23 | revocation query |
| RQ-053 | Accepted semantic pass replays byte-identically | 21,22 | independent replay |

## 7. MaskFactory and training

| ID | Requirement | Design | Verification/evidence |
|---|---|---|---|
| RQ-054 | No fifth truth tier | 23 | schema enum test |
| RQ-055 | DAZ uses weighted_pseudo_label | 23 | package fixture |
| RQ-056 | Geometry exactness is a source attribute | 23 | schema fixture |
| RQ-057 | DAZ is train-only | 23,25 | builder/launcher tests |
| RQ-058 | DAZ weight remains 0.10–0.25 | 23,25 | boundary/adversarial tests |
| RQ-059 | Synthetic image share remains ≤30% | 23,25 | independent rejection tests |
| RQ-060 | DAZ never counts as real gold/certified coverage | 23 | dashboard/count fixture |
| RQ-061 | Synthetic package does not fabricate human review | 23 | forbidden-field test |
| RQ-062 | DAZ bypasses mask voting, not package QA | 23 | S00 integration test |
| RQ-063 | Historical schemas/packages remain valid | 23 | regression corpus |
| RQ-064 | DAZ-disabled behavior remains unchanged | 23 | full-suite comparison |
| RQ-065 | Model promotion is based on untouched real images | 25 | matched ablation report |
| RQ-066 | Real hard labels/identity/runtime do not regress | 25 | promotion report |
| RQ-067 | Model rollback is one tested operation | 25,29 | rollback rehearsal |

## 8. Operations and recovery

| ID | Requirement | Design | Verification/evidence |
|---|---|---|---|
| RQ-068 | Disk thresholds stop new work before corruption | 11,27 | controlled fill test |
| RQ-069 | Retention preserves critical lineage/mappings | 11,27 | dry-run/invariant test |
| RQ-070 | Registry/mapping/config/recipe recovery works | 27,29 | clean-root restore |
| RQ-071 | Queue rebuilds from durable manifests/events | 23,27 | DB corruption exercise |
| RQ-072 | Seven-day unattended soak succeeds | 24,27 | soak evidence |
| RQ-073 | Daily report covers throughput/quality/coverage/storage | 27 | report fixture |
| RQ-074 | Runtime/asset updates invalidate bound results | 12,14,23 | update propagation |
| RQ-075 | DAZ can pause/drain/disable without core disruption | 20,29 | operations rehearsal |
| RQ-076 | Capacity model uses measured bytes/time | 11,27 | pilot capacity report |
| RQ-077 | Billable expansion waits for Kevin | 7,27 | no unattended billable API |

## 9. Traceability maintenance

- New requirements receive the next immutable ID.
- Deleted requirements are marked retired, never renumbered.
- Each code PR lists affected RQ IDs.
- Each test embeds its RQ ID in metadata or name.
- Evidence index maps RQ ID to artifact hash and date.
- A release report lists pass/fail/not-applicable for every active RQ.
- Any active requirement lacking design, implementation, test, or evidence is incomplete.

## 10. Package-level acceptance

This matrix is complete when all 77 requirements resolve to existing documents and every referenced
test/evidence type is instantiated in the implementation evidence index. Later expansion adds rows
without changing the meaning of existing IDs.
