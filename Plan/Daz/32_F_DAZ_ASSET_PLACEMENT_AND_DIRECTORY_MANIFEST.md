# F:\DAZ Asset Placement and Directory Manifest

## 1. Materialized state

The complete directory structure was created on 2026-07-14 under `F:\DAZ`:

- 24 canonical operational top-level roots (`00_control` through `23_exports` plus `99_archive`);
- the complete runtime, registry, staging, mapping, testing, generation, queue, render, annotation,
  packaging, dataset, export, logging, cache, backup, and archive subtrees;
- five manual-archive generation roots;
- 340 asset-category paths per generation root;
- explicit major, sub, micro, and nano body-part directories;
- separate DAZ-managed and MaskFactory-user content libraries.

## 2. The three placement rules

### DAZ Install Manager downloads

Configure DIM to use:

~~~text
download packages: F:\DAZ\02_installers\dim_downloads
installed content: F:\DAZ\03_content\libraries\MaskFactory_DAZ_Library
~~~

Do not move individual installed files after DIM installs them.

### Manually downloaded ZIP/package archives

Keep the archive intact and place it under:

~~~text
F:\DAZ\02_installers\manual_packages\asset_dropzone\
  <figure-generation>\
    <primary-asset-category>\
      downloaded_package.zip
~~~

Examples:

~~~text
...\genesis_9\01_body_modifiers_and_morphs\04_muscularity\full_body\
...\genesis_9\03_hair\07_coily\
...\genesis_9\04_clothing_and_wardrobe\12_outerwear\jackets\
...\genesis_9\06_poses\09_multi_person\pairs\contact\
...\generation_neutral\09_cameras\01_lenses\portrait\
...\generation_neutral\10_lighting\00_hdris\
...\generation_neutral\11_environments\03_outdoor\nature\forest\
...\generation_neutral\12_props\00_support_surfaces\chairs_stools_and_benches\
~~~

The installer/scanner preserves the archive's internal `data`, `People`, `Runtime`, textures, metadata,
and support paths when installing to the content library.

### Unknown downloads

Place archives that cannot yet be classified in:

~~~text
F:\DAZ\02_installers\manual_packages\_incoming_unsorted
~~~

The scanner moves or recommends them for `_needs_classification`. Do not guess and split their contents.

## 3. Generation roots

- `genesis_9` — explicitly Genesis 9 compatible.
- `genesis_8_1` — explicitly Genesis 8.1 compatible.
- `genesis_8` — explicitly Genesis 8 compatible.
- `generation_neutral` — cameras, lights, HDRIs, environments, props, shaders, scripts, and other
  content not tied to one figure generation.
- `other_or_unknown` — other figures, unclear compatibility, or packages awaiting inspection.

A package compatible with multiple generations stays intact in the generation named by its native
base. Converters are cataloged separately.

## 4. Primary category rule

Place each archive once, under its main advertised function. A hair package containing materials goes
under hair, not both hair and materials. A complete outfit containing shoes goes under complete
outfits. The registry catalogs all secondary components after installation.

The category families are:

~~~text
00_figures
01_body_modifiers_and_morphs
02_materials_and_textures
03_hair
04_clothing_and_wardrobe
05_accessories_and_wearables
06_poses
07_expressions
08_animations_and_mocap
09_cameras
10_lighting
11_environments
12_props
13_body_part_assets
14_scene_presets
15_render_settings
16_scripts_plugins_and_tools
17_converters_and_compatibility
18_simulation_resources
19_documentation_metadata_and_support
~~~

## 5. Body-part granularity

- `01_major` — whole structural regions such as head, torso, pelvis, full arms/legs, hair, and male or
  female anatomy.
- `02_sub` — regional divisions such as face/scalp/ears, chest/abdomen/back, upper arm/forearm/hand,
  thigh/calf/foot.
- `03_micro` — small semantic structures such as eyes, lips, mouth, teeth, nipples, navel, genitalia,
  fingers, nails, toes, heel, arch, ball, and sole.
- `04_nano` — individually resolved structures such as each finger, each toe, each eye/eyelid, each ear,
  and fine surface details.

Downloaded assets whose main purpose is a body-part resource use `13_body_part_assets`. Generated
MaskFactory mappings go under `F:\DAZ\07_mappings`. Generated annotation maps go under
`F:\DAZ\13_annotations`. These three locations must not be confused.

## 6. Content-library rule

`MaskFactory_DAZ_Library` is installer-managed. Never manually sort its internal files by asset type.
`MaskFactory_User_Library` is for presets, scripts, scenes, and custom content created locally; its
contents still use DAZ-native relative paths.

## 7. Workflow states

~~~text
download archive
  -> asset_dropzone or _incoming_unsorted
  -> scanner/classification
  -> _ready_for_install
  -> installation preserving internal paths
  -> _installed_archives
  -> content library scan
  -> technical smoke/mapping qualification
  -> eligible registry pool
~~~

Failed installations move logically to `_failed_install` with a report. Asset staging under
`06_asset_staging` contains manifests/references, not duplicate vendor archives.

## 8. Operational roots that users should not fill manually

The worker populates `04_runtime` through `23_exports` as applicable. In particular:

- `07_mappings` contains generated/frozen mapping bundles;
- `08_asset_tests` contains qualification evidence;
- `09_generation` contains plans and recipes;
- `10_queue` through `14_scene_packages` contain scene jobs and products;
- `15_datasets` and `16_maskfactory_exports` contain training packages;
- `17_logs` through `23_exports` contain operations, cache, backup, and reports.

## 9. Verification

The structure is valid when every required path exists, the content libraries are distinct, each
generation root contains the same category taxonomy, and installed DAZ content retains its original
internal relative paths.
