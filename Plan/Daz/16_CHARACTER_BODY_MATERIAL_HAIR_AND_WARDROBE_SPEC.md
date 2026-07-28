# Character, Body, Material, Hair, and Wardrobe Specification

## 1. Goal

Generate a broad population of unambiguously adult synthetic characters without manually creating and
saving each figure. Character construction is deterministic, coverage-driven, and constrained by asset
compatibility. The unit of generation is a character manifest, not a `.duf` file.

## 2. Character assembly order

The system applies attributes in this order because later steps depend on earlier geometry:

1. select supported base figure and mapping family;
2. select explicit adult anatomy configuration;
3. select adult age band;
4. apply character/head foundation morph;
5. apply correlated body-shape vector;
6. apply bounded face variation;
7. apply skin/eye/body-detail materials;
8. attach mapped anatomy geograft when required;
9. select hair and facial hair;
10. select wardrobe state and compatible garment layers;
11. fit/autofit garments and hair;
12. apply pose/expression;
13. run rig adjustment, simulation, collision, and final active-property audit;
14. freeze the explicit character manifest.

Changing the order is a versioned generator change because it can alter fit and shape.

## 3. Character manifest

```yaml
character_id: char_<hex>
person_slot: p0
base_figure_asset_id: daz_asset_...
mapping_id: daz_map_g9_body_parts_v1_0001
anatomy_configuration: adult_female_anatomy
presentation: feminine
adult_age_band: adult_30_44
character_preset_asset_id: daz_asset_...
morphs:
  - property_uri: <stable property reference>
    value: 0.23
    category: body_composition
materials:
  skin: daz_asset_...
  eyes: daz_asset_...
hair:
  asset_id: daz_asset_...
  style_tags: [shoulder_length, curly, loose]
wardrobe:
  state: layered_clothed
  items: [<ordered inner-to-outer item records>]
adult_audit_sha256: ...
final_geometry_fingerprint: ...
```

The manifest stores actual final property values after presets and auto-follow, not only intended
inputs.

## 4. Anatomy configuration and presentation

Initial anatomy configurations:

- `adult_male_anatomy`;
- `adult_female_anatomy`.

Presentation is independent:

- `masculine`;
- `feminine`;
- `androgynous`;
- `neutral`;
- `mixed_style`.

The sampler must cross presentation and anatomy where the asset library supports it. It must not infer
gender identity, pronouns, or real-world identity from either axis.

## 5. Adult age-appearance representation

Use the categories defined in document 12. Variation can include adult facial/body aging, posture, hair
color/density, skin details, and body composition through compatible bundled controls. Age appearance is
not a single slider. The generator uses a correlated profile so face, body, skin, posture, and hair
remain coherent.

For each band, record:

- age-profile ID;
- all age-appearance property URIs/values;
- skin-detail/material choices;
- hair color/density tags;
- posture modifications, if any;
- final applied-profile readback hash.

## 6. Body-shape vector

Body diversity uses normalized axes with asset-specific transforms:

```text
stature
overall_scale
body_mass
body_fat_distribution
muscularity_total
upper_body_muscularity
lower_body_muscularity
shoulder_width
chest_depth
chest_or_bust_volume
waist_width
abdomen_prominence
pelvis_width
hip_width
glute_volume
torso_length
arm_length
forearm_proportion
hand_scale
leg_length
thigh_volume
calf_volume
foot_scale
head_scale
neck_length
```

### Sampling method

- Generate a correlated latent vector from a versioned covariance profile.
- Transform into supported morph properties by figure/configuration.
- Clamp each property to its smoke-tested safe range.
- Enforce multi-property constraints such as shoulder/torso compatibility, limb/hand scale continuity,
  and clothing-fit feasibility.
- Allocate most samples to ordinary ranges and a controlled minority to safe extremes.

Default distribution per continuous axis:

| Range | Target share |
|---|---:|
| central 50% | 50% |
| moderate low/high | 35% |
| validated extremes | 15% |

The 15% extreme share is spread across axes; it does not mean 15% of characters are extreme on every
axis simultaneously.

## 7. Body-type strata

Reports aggregate continuous shapes into non-authoritative technical bins:

- short / medium / tall stature;
- low / medium / high body mass;
- low / medium / high muscularity;
- narrow / medium / broad shoulders;
- narrow / medium / broad pelvis/hips;
- short / medium / long torso;
- short / medium / long limb proportions;
- small / medium / large hands and feet.

These bins support coverage and are not labels predicted by MaskFactory.

## 8. Face and head variation

Vary within adult-safe, topology-preserving controls:

- head width/height/depth;
- jaw width/angle;
- chin projection/height;
- cheek volume/height;
- forehead shape;
- nose length/width/projection;
- eye spacing/size/tilt within plausible limits;
- brow shape;
- lip shape/volume;
- ear size/projection;
- neck thickness/length.

Do not create random combinations that produce invalid eyelids, teeth, oral geometry, ear intersections,
unsupported controller coupling, or obvious mesh breakage.

## 9. Skin and material diversity

Skin coverage uses observable rendering attributes rather than race labels:

- six broad skin-tone bands spanning very light through very dark;
- warm, cool, neutral, olive, and red undertone tags when supported;
- matte, balanced, and oily/specular response profiles;
- freckles, moles, scars, stretch marks, veins, wrinkles, body hair, and texture variation as optional
  overlays when technically compatible;
- multiple vendors/material families with per-family caps;
- body/face material matching tests;
- exposure response under every lighting class.

Initial marginal target per tone band is approximately balanced enough to prevent sparse extremes, not
necessarily uniform. No band may fall below 10% of the accepted core corpus once inventory supports it;
the planner reports inventory limitations honestly.

## 10. Eye, makeup, tattoo, and body-detail policy

- Eye colors and sclera/iris materials vary without changing mask classes.
- Makeup is a material appearance attribute, not a skin/body-part class.
- Tattoos/body paint are permitted appearance variations when the underlying skin material remains
  class `skin`.
- Heavy body paint that changes person/background contrast is a valuable stress lane.
- Decals must resolve and reproduce; missing or floating decals quarantine the combination.
- Body details cannot create apparent clothing/material labels unless the ontology says so.

## 11. Hair taxonomy

### Construction

- scalp cap plus polygon cards;
- polygon strands/cards;
- strand-based procedural/dynamic;
- fitted hair;
- parented prop hair;
- facial hair;
- brows/lashes;
- body hair overlays.

### Length

```text
bald
shaved
very_short
short
chin_length
shoulder_length
mid_back
waist_length
very_long
```

### Texture/style

```text
straight
wavy
curly
coily
afro
braids
locs
twists
ponytail
pigtails
bun
updo
bangs
side_swept
wet_or_slicked
wind_displaced
```

### Occlusion behavior

- face clear;
- partial forehead/eye/cheek coverage;
- ear coverage;
- neck coverage;
- one/both shoulder coverage;
- chest/breast coverage;
- upper-back coverage;
- torso-long-hair overlap;
- arm/hand interaction with hair.

The sampler tracks style and occlusion separately. A “long” asset does not guarantee chest/back
occlusion in every pose.

## 12. Hair color and material

Cover black, dark/medium/light brown, blonde, red/auburn, gray, white, dyed natural variation, and
controlled non-natural colors. Color is crossed with tone and lighting to prevent the model from
learning fixed associations. Hair material remains `hair_material`; translucent fringes use the alpha
policy in document 15.

## 13. Facial hair

Categories:

- clean-shaven;
- stubble;
- moustache;
- goatee;
- short beard;
- full beard;
- long beard;
- sideburn variation.

Facial hair must be included across anatomy configurations/presentations where compatible rather than
hard-coded to a single group. It maps to PART hair and MATERIAL hair, while uncovered pixels remain
head/face skin.

## 14. Wardrobe-state taxonomy

```text
unclothed
underwear_only
swimwear
minimal_clothing
tight_fitted
standard_casual
loose_clothing
layered_clothing
formal
athletic
sleepwear
outerwear
workwear_or_uniform_generic
costume_or_stylized_adult
```

`unclothed` and anatomy-visible configurations are intentional training coverage, not failure states.
All characters remain unambiguously adults.

## 15. Garment taxonomy

### Upper body

- bra/bralette;
- undershirt;
- crop top;
- tank/camisole;
- fitted/loose short-sleeve top;
- fitted/loose long-sleeve top;
- shirt/blouse;
- sweater/hoodie;
- vest;
- jacket/coat;
- strapless/halter/asymmetric top.

### Lower body

- underwear bottom;
- briefs/boxers;
- shorts;
- fitted/loose pants;
- leggings/tights;
- short/mid/long skirt;
- wrap/asymmetric lower garment.

### One-piece

- dress by sleeve/length/fit;
- jumpsuit/romper;
- bodysuit;
- one-piece swimwear;
- robe/gown.

### Extremities and accessories

- gloves/mittens/fingerless gloves;
- socks/stockings/hosiery;
- barefoot, sandals, flats, sneakers, boots, heels, other footwear;
- hats/hoods/headwear;
- belts, straps, bags, jewelry, watches, glasses, scarves.

Each garment records covered body territories, layer, fit class, opacity class, dynamic/static behavior,
and known collision risks.

## 16. Clothing properties

Coverage dimensions:

- skin-tight / fitted / regular / loose / very loose;
- opaque / lace / sheer / cutout / mesh;
- short / medium / long coverage;
- sleeveless / short / elbow / long sleeve;
- low / medium / high waistband;
- no strap / thin strap / wide strap / multiple straps;
- plain / patterned / textured / reflective / dark / light;
- single / double / three-plus layers;
- dry / wet-look appearance when supported;
- symmetric / asymmetric.

Sheer/lace materials use MATERIAL `lace_or_sheer` where defined. Visible body PART truth follows actual
visible ownership; unreliable transparency becomes ignore or excludes that sample from PART training.

## 17. Wardrobe compatibility and fitting

Before a wardrobe combination is selectable:

- all items target or convert to the chosen figure;
- inner-to-outer layer order is defined;
- body morph ranges fall inside tested fit coverage;
- hidden-surface/removal modifiers are known and do not destroy mapping unexpectedly;
- required simulation is deterministic;
- garment territory maps exist;
- pose stress class is within the garment certificate;
- hair/headwear and footwear/foot-pose conflicts are resolved.

The scene validator checks final actual geometry. A nominally compatible combination can still be
rejected.

## 18. Unclothed and partially clothed coverage

For each anatomy configuration and applicable ontology:

- full front/back/profile/three-quarter views;
- upper-body exposed, lower-body clothed;
- lower-body exposed, upper-body clothed;
- underwear/swimwear boundaries;
- hands/hair/props/other-person occlusion over anatomy;
- seated, crouched, lying, twisting, and cropped states;
- varied skin tone, body type, adult age band, camera, and lighting;
- explicit `visible`, `partially_visible`, `occluded`, `cropped_out`, and configuration-not-applicable
  states.

No hidden geometry is promoted to visible truth.

## 19. Expressions

Use neutral plus mild/moderate/strong expressions: smile, frown, surprise, concentration, relaxed,
eyes open/closed/squint, mouth open/closed. Expression is secondary coverage and must not overwhelm body
pose diversity. Extreme expressions are capped because they are not a primary body-mask deficit.

## 20. Diversity and dominance controls

Default maximum contributions to an accepted corpus version:

| Entity | Maximum share |
|---|---:|
| one character preset | 3% |
| one skin material | 3% |
| one hair asset | 2% |
| one complete outfit/look | 2% |
| one individual garment | 5% |
| one pose preset | 0.5% exact; pose-family caps also apply |
| one environment | 3% |
| one product | 10% across all roles, unless it is required base content |

Base figure products are exempt from product share reporting but not from topology/runtime tracking.

## 21. Character validation

Hard checks:

- explicit figure and anatomy configuration;
- declared age-appearance profile agrees with final applied controller values;
- recognized topology/mapping;
- all property values finite/in range;
- all textures resolve;
- hair/wardrobe follows intended figure;
- no missing expected body/anatomy node;
- no unexpected topology change;
- garment/hair gross-intersection thresholds pass;
- final character and manifest values agree;
- same manifest recreates the same semantic geometry.

## 22. Output statistics

Report marginal and crossed coverage for anatomy configuration, presentation, adult age-appearance
category, body-type
bins, skin-tone band, hair length/texture/occlusion, wardrobe state, garment properties, and anatomy
visibility. Always report asset inventory support separately from accepted scene counts.
