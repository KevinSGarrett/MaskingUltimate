# Official Technical Source Registry

## 1. Purpose

This registry records the technical references used to design the DAZ subsystem. It is an engineering
reference list: implementation must verify behavior against the pinned local DAZ Studio build because
documentation can describe multiple versions.

Last blueprint review: 2026-07-14.

## 2. DAZ Studio scripting

| ID | Official source | Used for |
|---|---|---|
| SRC-DAZ-001 | [DAZ Studio scripting reference](https://docs.daz3d.com/public/software/dazstudio/4/referenceguide/scripting/start) | scripting model, API navigation |
| SRC-DAZ-002 | [DAZ Script API samples](https://docs.daz3d.com/public/software/dazstudio/4/referenceguide/scripting/api_reference/samples/start) | supported scripting patterns |
| SRC-DAZ-003 | [Rendering samples](https://docs.daz3d.com/public/software/dazstudio/4/referenceguide/scripting/api_reference/samples/rendering/start) | renderer and output automation |
| SRC-DAZ-004 | [Command-line options](https://docs.daz3d.com/public/software/dazstudio/4/referenceguide/tech_articles/command_line_options/start) | script arguments, instance/startup modes |

Implementation verification:

- launch a script with an explicit recipe path;
- capture arguments and return/result behavior;
- verify no-prompt and named-instance behavior on the installed build;
- benchmark headless versus hidden-GUI execution rather than assuming either.

## 3. Content and asset APIs

| ID | Official source | Used for |
|---|---|---|
| SRC-DAZ-010 | [DzContentMgr](https://docs.daz3d.com/public/software/dazstudio/4/referenceguide/scripting/api_reference/object_index/contentmgr_dz) | registered content roots and content lookup |
| SRC-DAZ-011 | [DzAssetMgr](https://docs.daz3d.com/public/software/dazstudio/4/referenceguide/scripting/api_reference/object_index/assetmgr_dz) | asset metadata/management access |
| SRC-DAZ-012 | [DAZ Install Manager settings](https://docs.daz3d.com/public/software/install_manager/userguide/configure_install_manager/tutorials/settings_for_install_manager/start) | separate download/content locations |
| SRC-DAZ-013 | [DIM install manifest technical article](https://docs.daz3d.com/_export/raw/public/software/install_manager/referenceguide/tech_articles/install_manifest/start) | installed product/file inventory |

Implementation verification:

- enumerate the exact registered F content root;
- compare DIM file lists, CMS results, and filesystem inventory;
- verify logical URI resolution and shadow precedence;
- keep an offline filesystem/DIM fallback.

## 4. Scene, figure, and geometry APIs

| ID | Official source | Used for |
|---|---|---|
| SRC-DAZ-020 | [DzScene](https://docs.daz3d.com/public/software/dazstudio/4/referenceguide/scripting/api_reference/object_index/scene_dz) | scene graph, nodes, selection, lifecycle |
| SRC-DAZ-021 | [DzSkeleton](https://docs.daz3d.com/public/software/dazstudio/4/referenceguide/scripting/api_reference/object_index/skeleton_dz) | figures, bones, posing, ownership |
| SRC-DAZ-022 | [DzFacetMesh](https://docs.daz3d.com/public/software/dazstudio/4/referenceguide/scripting/api_reference/object_index/facetmesh_dz) | facet/vertex/topology inspection |
| SRC-DAZ-023 | [DzMaterial](https://docs.daz3d.com/public/software/dazstudio/4/referenceguide/scripting/api_reference/object_index/material_dz) | surfaces, materials, pass overrides |

Implementation verification:

- enumerate stable nodes/bones/surfaces/facets after loading;
- verify topology behavior before/after morph, subdivision, smoothing, and geograft application;
- verify final property readback and controller side effects;
- verify scene clearing between jobs.

## 5. Renderer and camera APIs

| ID | Official source | Used for |
|---|---|---|
| SRC-DAZ-030 | [DzRenderMgr](https://docs.daz3d.com/public/software/dazstudio/4/referenceguide/scripting/api_reference/object_index/rendermgr_dz) | active renderer/options/render lifecycle |
| SRC-DAZ-031 | [DzRenderer](https://docs.daz3d.com/public/software/dazstudio/4/referenceguide/scripting/api_reference/object_index/renderer_dz) | renderer capabilities and invocation |
| SRC-DAZ-032 | [Cameras and views](https://docs.daz3d.com/public/software/dazstudio/4/userguide/chapters/cameras_and_views/start) | camera construction, projection, framing |
| SRC-DAZ-033 | [Iray Uber Shader general concepts](https://docs.daz3d.com/public/software/dazstudio/4/referenceguide/interface/panes/surfaces/shaders/iray_uber_shader/shader_general_concepts/start) | material IDs and shader concepts relevant to passes |

Implementation verification:

- enumerate renderer name/version and option snapshot;
- validate exact ID output rather than assuming material-ID behavior;
- record camera matrices/crop/resolution in every pass;
- prove original materials/settings restore after annotation overrides.

## 6. Local MaskFactory sources

The implementation session must resolve exact current paths through repository search because the
project evolves. Required local authorities are:

| ID | Local authority | Used for |
|---|---|---|
| SRC-MF-001 | `Plan\Instructions\00_START_HERE.md` through current instruction set | work/evidence/tracker process |
| SRC-MF-002 | `Plan\SIDE_THREAD_HANDOFF_SAM31_AUTONOMOUS_GOLD_20260713.md` | current autonomous-gold amendment |
| SRC-MF-003 | `Plan\00_MASTER_INDEX.md` through `Plan\17_MULTI_PERSON_MULTI_CHARACTER_MASKING_SPEC.md` | complete MaskFactory design |
| SRC-MF-004 | `Plan\Tracker\DASHBOARD.md` and tracker CLI output | live project state |
| SRC-MF-005 | active ontology YAML/JSON loaded by production code | canonical IDs/derived regions |
| SRC-MF-006 | active instance/source/package JSON Schemas | package contracts |
| SRC-MF-007 | dataset/training specification and implementation | split, weight, 30% constraint |
| SRC-MF-008 | multi-person QC implementation/tests | p-index, QC-035/036 behavior |
| SRC-MF-009 | current full test suite and fixtures | backward compatibility |

## 7. Local machine evidence

Official documentation never substitutes for local verification. Freeze:

- DAZ Studio executable path, version, and SHA-256;
- renderer/plugin inventory;
- DAZ Script bundle SHA-256;
- NVIDIA driver/GPU profile;
- DIM and content-root configuration;
- installed product/asset registry snapshot;
- base topology and mapping hashes;
- render/pass profile;
- primitive and representative asset smoke results.

## 8. Source-review procedure

For a DAZ runtime upgrade:

1. snapshot the old source registry and runtime;
2. review relevant current official API pages;
3. record changed page dates/content where detectable;
4. run API capability probes;
5. rerun primitive, asset, mapping, render, and replay fixtures;
6. issue a new runtime/source-registry version;
7. never rewrite historical evidence.

## 9. Documentation gaps

Where official API pages are incomplete:

- prefer runtime introspection and a minimal reproducible script;
- record installed-version behavior and output;
- isolate the behavior behind an adapter;
- add a regression fixture;
- avoid UI-coordinate automation as the routine implementation;
- do not assume undocumented renderer exactness.

## 10. Completion criteria

- Every external technical claim in this blueprint maps to a source above or a local verified probe.
- Every DAZ API used by production has a pinned-runtime contract test.
- Source links and review dates are checked during runtime upgrades.
- Local MaskFactory schemas/tests remain the final authority for integration behavior.
