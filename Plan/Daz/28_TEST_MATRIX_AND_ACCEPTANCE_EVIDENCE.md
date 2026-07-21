# Test Matrix and Acceptance Evidence

## 1. Evidence standard

A test is complete only when its command, environment, exact inputs, expected result, observed result,
artifact paths, hashes, and pass/fail status are recorded. Live DAZ tests additionally record Studio,
renderer, script, plugin, driver, asset-registry, and mapping snapshots.

## 2. Static and schema tests

| ID | Test | Expected |
|---|---|---|
| T-001 | DAZ config schema positive fixture | validates |
| T-002 | unknown key/invalid version | rejected with stable code |
| T-003 | path traversal/junction escape | rejected |
| T-004 | historical MaskFactory manifests | unchanged pass |
| T-005 | synthetic manifest complete | passes new version |
| T-006 | synthetic missing lineage | rejected |
| T-007 | synthetic claims human review/certified gold | rejected |
| T-008 | invalid truth tier/partition/weight | rejected |
| T-009 | v1 package includes v2 ID | rejected |
| T-010 | source-asset extension seeded into Git staging | detected |

## 3. Registry and asset tests

| ID | Test | Expected |
|---|---|---|
| T-011 | repeat filesystem/DIM scan | identical snapshot hash |
| T-012 | CMS unavailable | offline inventory succeeds with declared metadata gaps |
| T-013 | same filename/different hash | distinct assets |
| T-014 | duplicate identical file | deterministic alias record |
| T-015 | missing dependency | asset incompatible |
| T-016 | dependency cycle | declared graph error |
| T-017 | content file modified | new hash; certificates revoked |
| T-018 | shadowed content-root file | deterministic winner + warning |
| T-019 | missing texture/external path | technical quarantine |
| T-020 | unexpected DAZ dialog | watchdog terminates and records asset |
| T-021 | supported asset smoke | certificate bound to hashes |
| T-022 | runtime changes | certificate stale |

## 4. Mapping tests

| ID | Test | Expected |
|---|---|---|
| T-023 | neutral G9 topology fingerprint | exact golden |
| T-024 | one facet/order/group mutation | mapping rejected |
| T-025 | all v1 allowed IDs | complete mapping table |
| T-026 | front/back/profile left/right fixtures | character-perspective consistency |
| T-027 | fingers/toes articulation | correct parent/side |
| T-028 | torso/pelvis/glute/chest boundaries | golden match |
| T-029 | bounded morph/pose stress | topology and labels stable |
| T-030 | tight garment transfer | boundary tolerance pass |
| T-031 | loose/layered garment transfer | visible-territory pass |
| T-032 | hair construction/alpha fixtures | declared coverage pass |
| T-033 | anatomy/geograft composition | no base overlap or hole |
| T-034 | v2 atomics reconstructed to unions | exact derived-region match |

## 5. Recipe and sampler tests

| ID | Test | Expected |
|---|---|---|
| T-035 | same seed/snapshots/config | byte-identical recipe |
| T-036 | registry iteration shuffled | same selection |
| T-037 | change camera stream only | unrelated selections unchanged |
| T-038 | incompatible asset combination | never emitted |
| T-039 | morph/joint boundary values | valid finite readback |
| T-040 | all M/F person-count compositions | schedulable |
| T-041 | asset cooldown/dominance | caps observed |
| T-042 | injected coverage deficit | selection shifts toward deficit |
| T-043 | impossible deficit | honest unsatisfied report |
| T-044 | recipe replay after scanner rebuild | identical resolved assets |

## 6. Worker and process tests

| ID | Test | Expected |
|---|---|---|
| T-045 | primitive file-protocol job | terminal success last |
| T-046 | kill before result | partial quarantined |
| T-047 | kill after files before result | not accepted |
| T-048 | stale heartbeat/lease | one recovery, no duplicate |
| T-049 | simultaneous GPU request | serialized |
| T-050 | renderer fallback attempt | job fails |
| T-051 | default scene pollution | detected/cleaned by restart |
| T-052 | path with spaces/non-ASCII/long name | correct round trip |
| T-053 | worker timeout | process tree terminated |
| T-054 | persistent-worker sequence | no state or memory leakage |

## 7. Render-pass tests

| ID | Test | Expected |
|---|---|---|
| T-055 | ID codec exhaustive values | exact decode |
| T-056 | aliased/unknown color | rejected |
| T-057 | all pass dimensions/camera/crop | identical |
| T-058 | semantic pass repeated | byte-identical |
| T-059 | RGB rerender tolerance | meets pinned profile |
| T-060 | transparent hair edge | hard owner + alpha convention |
| T-061 | lace/sheer/straps | declared thin-material behavior |
| T-062 | depth analytic primitive | correct linear units |
| T-063 | normals analytic primitive | correct handedness/unit length |
| T-064 | diagnostic amodal export | physically separate, not trainable |
| T-065 | hidden body under garment | absent from visible PART |
| T-066 | clothing pixel | body territory in PART, clothing in MATERIAL |

## 8. Pixel and semantic tests

| ID | Test | Expected |
|---|---|---|
| T-067 | full-image ownership equations | zero violations |
| T-068 | seed one illegal ID pixel | detected |
| T-069 | seed one missing PART pixel | detected |
| T-070 | swap one left/right region | detected by fixtures |
| T-071 | disconnect finger/toe territory | adjacency check fails |
| T-072 | offset label pass by one pixel | alignment check fails |
| T-073 | corrupt alpha boundary | boundary check fails |
| T-074 | change mapping after package | descendant invalidation |
| T-075 | wrong scene-state hash | complete pass set rejected |
| T-076 | asset geometry changed silently | topology check fails |

## 9. Multi-person tests

| ID | Test | Expected |
|---|---|---|
| T-077 | p-index construction order permutations | same prominence result |
| T-078 | MM/MF/FF separated | correct owners |
| T-079 | overlap/crossed limbs | correct owners |
| T-080 | contact pair | reciprocal relationship |
| T-081 | overlap without 3D contact | occlusion, not contact |
| T-082 | duplicate ownership pixel | exclusivity failure |
| T-083 | swap limb instance ID | bleed failure |
| T-084 | derive target/other views | exact complements |
| T-085 | trio/quartet all compositions | complete/nonempty |
| T-086 | all scene items and variants | one image/split group |

## 10. Package and dataset tests

| ID | Test | Expected |
|---|---|---|
| T-087 | complete accepted package | verifies/ingests |
| T-088 | one output byte modified | hash failure |
| T-089 | missing mandatory file | package failure |
| T-090 | DAZ disabled | normal suite unchanged |
| T-091 | synthetic placed in validation/test | builder rejects |
| T-092 | 30.0% synthetic | accepts |
| T-093 | >30.0% synthetic | builder and launcher reject |
| T-094 | weight 0.10/0.25 | accepts |
| T-095 | weight outside range | builder and launcher reject |
| T-096 | synthetic counts queried as gold | zero contribution |
| T-097 | near variants assigned across splits | grouping catches |
| T-098 | mixed ontology/mapping incompatibility | dataset fails |

## 11. Capacity and recovery tests

| ID | Test | Expected |
|---|---|---|
| T-099 | reach soft floor | new planning pauses |
| T-100 | reach hard floor | render leasing drains |
| T-101 | reach emergency floor | controlled stop |
| T-102 | F drive disappears | no corrupt acceptance |
| T-103 | queue DB corrupted | restored/rebuilt |
| T-104 | retention dry-run twice | identical plan |
| T-105 | active lease during retention | protected |
| T-106 | Tier A clean-root restore | integrity passes |
| T-107 | restored recipe semantic replay | exact hash |
| T-108 | seven-day soak | targets satisfied |

## 12. Training and model tests

| ID | Test | Expected |
|---|---|---|
| T-109 | E0–E6 dataset reproducibility | stable hashes |
| T-110 | matched real-only/mixed runs | comparable manifests |
| T-111 | real holdout contains synthetic | hard failure |
| T-112 | primary real metric comparison | finite paired CI |
| T-113 | hard-label non-inferiority | all declared results |
| T-114 | left/right/cross-person regression | reported/rejects candidate |
| T-115 | gain only on synthetic diagnostic | no promotion |
| T-116 | champion rollback | exact prior serving state |

## 13. Evidence bundle layout

~~~text
evidence/<release-id>/
  environment.json
  code_and_config.json
  registry_mapping_runtime.json
  test_results.jsonl
  commands/
  reports/
  golden_hashes/
  negative_fixture_results/
  capacity/
  soak/
  training/
  restore/
  evidence_hashes.json
~~~

## 14. Acceptance report

The report contains:

- release ID and scope;
- active requirements and test mapping;
- pass/fail/skip totals by tier;
- every skip with reason and impact;
- known defects and excluded asset/scene families;
- pilot/soak/capacity results;
- real-image ablation result;
- rollback target and rehearsal result;
- evidence bundle hash.

## 15. Completion criteria

- T-001 through T-116 applicable tests have implementations.
- Every critical negative fixture demonstrably fails for the expected reason.
- Live tests are bound to exact local runtime/asset hashes.
- No result is accepted from screenshots or file presence alone.
- Evidence bundle verifies from its top-level hash.
