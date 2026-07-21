# Camera, Lighting, Environment, Prop, and Degradation Specification

## 1. Goal

Prevent the model from learning a narrow DAZ studio look by deliberately varying image formation,
background complexity, occluders, support geometry, scale, crop, and post-render artifacts while keeping
annotation alignment exact.

## 2. Camera coordinate contract

Every recipe stores:

- camera asset/procedural profile;
- projection type;
- world transform and look-at target;
- focal length or orthographic scale;
- sensor/frame aspect assumptions;
- resolution and crop;
- focal distance, f-stop, depth-of-field state;
- shutter/motion-blur state;
- lens distortion state;
- target-person projected bboxes and prominence.

The worker records final values read back from DAZ after all presets.

## 3. View taxonomy

### Azimuth relative to target character

- front (±15°);
- left/right three-quarter front (15–75°);
- left/right profile (75–105°);
- left/right three-quarter back (105–165°);
- back (165–180°).

MaskFactory's existing closed view vocabulary maps these to front, back, profiles, and three-quarter
values. The DAZ manifest retains the finer continuous angle and bin.

### Elevation

```text
ground_level     -35° to -20° relative look
low              -20° to -8°
eye_level        -8° to +8°
high             +8° to +25°
overhead         +25° to +60°
near_top_down    +60° to +85°  # stress/diagnostic, capped
```

### Roll

- level;
- mild ±5°;
- moderate ±15°;
- strong/Dutch ±30° capped at a small share.

## 4. Focal-length families

Full-frame-equivalent design targets, calibrated to DAZ camera behavior:

| Family | Nominal values | Purpose |
|---|---|---|
| ultra-wide | 18–20 mm | strong perspective, environmental/truncation stress |
| wide | 24–28 mm | groups and close environmental portraits |
| normal-wide | 35 mm | documentary/body context |
| normal | 50 mm | baseline |
| portrait | 70–85 mm | flatter full/medium person views |
| telephoto | 105–135 mm | compressed depth/overlap |
| orthographic | no perspective | mapping diagnostics only; capped/excluded from real-style training by default |

Focal length is crossed with distance to avoid confounding every wide lens with a tiny person or every
telephoto lens with a close crop.

## 5. Framing and crop taxonomy

- full body with margin;
- full body tight;
- three-quarter body;
- waist-up;
- chest/head;
- head/shoulders;
- limb/hand/foot/anatomy close-up;
- intentional top/bottom/left/right truncation;
- multi-person group full;
- multi-person mixed truncation;
- negative-space composition;
- off-center subject.

Training samples must retain enough visible person area to satisfy the intended MaskFactory promotion
policy. Specialist close-ups use a declared close-up profile and do not pretend to be whole-person
packages when the person cannot be promoted.

## 6. Aspect ratio and resolution

Core aspect ratios:

```text
1:1
4:5 / 5:4
2:3 / 3:2
9:16 / 16:9
```

Pilot render resolutions:

- 512 px short side for asset smoke;
- 768–1024 px short side for scene pilot;
- 1024–1536 px short side for core training;
- 2048 px or targeted close-ups for boundary-specialist data, subject to VRAM/profile tests.

Annotation passes are rendered at final training-source resolution. Upscaling a coarse ID map to match a
high-resolution beauty render is forbidden.

## 7. Depth of field and motion blur

### Beauty render

- DOF off for 70% core baseline;
- mild DOF 20%;
- strong but person-relevant DOF 10% stress lane;
- motion blur off for initial core;
- mild camera/subject motion blur introduced only after exact sharp-source packaging and transformed
  supervision policy is validated.

### Annotation pass

DOF and motion blur are off. To train against a blurred RGB variant, transform the accepted sharp RGB
while retaining the geometry-aligned label map and mark the degradation. For severe blur where a binary
boundary is not objectively visible, use ignore bands or exclude from pixel-perfect training.

## 8. Lens effects

- radial distortion barrel/pincushion;
- chromatic aberration;
- vignetting;
- bloom/glare;
- sensor flare;
- rolling-shutter-like warp as a postprocess research lane.

Effects are derived after pristine acceptance. Geometry-changing warps transform masks with the same
coordinate map using nearest-neighbor IDs and validate topology; color-only effects touch RGB only.

## 9. Lighting taxonomy

### Studio

- large softbox/front soft;
- three-point key/fill/rim;
- beauty/clamshell;
- hard single source;
- side/split light;
- overhead/top light;
- underlight stress;
- backlight/rim silhouette;
- high-key white;
- low-key dark;
- colored gel/mixed color.

### Environment/natural

- overcast diffuse;
- open shade;
- direct midday sun;
- low-angle sunrise/sunset-like;
- window light;
- indoor practical warm;
- fluorescent/cool interior;
- mixed indoor/outdoor;
- HDRI soft/hard/colored.

### Exposure/contrast

- normal exposure;
- mild under/overexposure;
- high dynamic range;
- deep cast shadow crossing body;
- low person/background contrast;
- high contrast and clipped highlights stress lane.

No lighting preset may change renderer, dimensions, camera, or output path silently.

## 10. Skin-tone × light coverage

Every skin-tone band needs coverage under:

- soft neutral light;
- hard directional light;
- back/rim light;
- low-key dark background;
- high-key light background;
- warm and cool mixed light;
- mild underexposure;
- specular highlight conditions.

These pairwise targets are mandatory because marginal skin and lighting diversity can still leave dark
skin under backlight or light hair on bright background untested.

## 11. Background and environment taxonomy

### Controlled backgrounds

- transparent/solid neutral;
- solid light/dark/skin-adjacent colors;
- gradients;
- simple geometric backdrop;
- patterned/high-frequency backdrop.

### Indoor

- studio;
- bedroom/living room;
- kitchen/dining;
- office;
- gym/studio generic;
- hallway/stairs;
- bathroom-like hard surfaces without mirrors in the initial lane;
- warehouse/industrial generic;
- furnished/cluttered variations.

### Outdoor

- open sky/field;
- wooded/foliage;
- urban street/plaza;
- beach/waterfront without reflective ambiguity in initial lane;
- rocky/desert;
- garden/park;
- day/evening-like illumination.

Environments are chosen for boundary and occlusion diversity, not scene storytelling.

## 12. Environment restrictions for initial production

Exclude or quarantine:

- mirrors and clear person reflections;
- transparent/refractive walls producing duplicate silhouettes;
- screens/posters containing undeclared people;
- volumetric fog that makes exact binary visibility ambiguous;
- moving simulations not replayable;
- environment presets that load additional human figures;
- unbounded scene scale or geometry causing render/OOM failures.

Later support requires explicit reflected-instance and transparency truth design.

## 13. Props and support surfaces

### Support surfaces

- floor/ground;
- chair/stool/bench;
- couch/bed;
- table/desk edge;
- wall/rail;
- step/stairs;
- exercise mat/platform.

### Handheld/worn props

- bag;
- box/book-like object;
- cup/bottle-like cylinder;
- phone-like rectangle;
- handle/tool-like generic object;
- ball;
- fabric/towel-like occluder only after mapping tests;
- glasses/jewelry/watch/hat/scarf.

### Occluders

- foreground plant/rail/furniture edge;
- doorframe/pillar;
- tabletop;
- another prop crossing limbs/torso;
- shared prop between people.

Props receive stable object IDs and role `occluding_object`, `support_surface`, or `accessory_or_prop` per
target instance. They never become body PART pixels.

## 14. Prop-placement recipes

Prop placement uses named anchors and constraints:

- hand grip anchor to prop handle;
- foot/floor support;
- hip/chair seat;
- back/chair back;
- elbow/table;
- foreground occluder with target coverage percentage;
- shared prop with two hand contacts.

The solver verifies contact distance, penetration, and that the prop occludes the requested body region
by a target percentage. Random floating props are rejected.

## 15. Image degradation pipeline

Start only from accepted pristine RGB + exact maps. Derived variants can add:

### Resolution and resampling

- downscale/upscale with nearest/bilinear/bicubic/Lanczos RGB methods;
- anisotropic resize;
- thumbnail-like low resolution;
- crop and pad;
- aspect-ratio conversion.

### Sensor/noise

- Gaussian/Poisson-like noise;
- luminance/chroma noise;
- fixed-pattern-like mild noise;
- hot/dead pixels at small controlled rates.

### Blur

- mild Gaussian/defocus;
- directional motion blur;
- local blur;
- sharpening/oversharpen halos.

### Compression

- JPEG quality ladder;
- repeated JPEG recompression;
- WebP-like compression only if training ingestion supports decoded PNG/RGB;
- chroma subsampling artifacts;
- screenshot-like scaling/compression.

### Color/tone

- exposure, gamma, contrast;
- white balance/tint;
- saturation/hue within plausible ranges;
- tone curves;
- limited dynamic range;
- grayscale/sepia as small stress lanes.

### Occlusion overlays

Synthetic 2D overlays are not used unless they have exact protected-object masks and realistic compositing
metadata. Geometry props are preferred.

## 16. Mask transformation rules

- Pure color/noise/compression operations do not change masks.
- Crop/pad/resize/warp applies the exact same transform to all maps.
- Indexed maps use nearest-neighbor only.
- Continuous alpha/depth/normals use type-appropriate resampling with validity masks.
- A geometric transform that merges/disconnects small labels is revalidated.
- Severe blur creates a boundary ignore band or is diagnostic-only.
- Every derived image records parent pristine hash, transform list, parameters, seed, and output hashes.

## 17. Initial target distribution

| Axis | Core target |
|---|---|
| azimuth | balanced across six MaskFactory view bins, with extra profile/3-4 hard coverage |
| elevation | 50% eye, 20% low, 20% high, 5% ground, 5% overhead |
| focal family | 10% ultra/wide, 25% 35 mm, 35% 50 mm, 25% 70–85 mm, 5% tele |
| framing | 50% full, 20% three-quarter, 15% waist-up, 10% close-up specialist, 5% deliberate truncation stress initially |
| lighting | no single profile >15%; at least 20% hard/high-contrast and 15% back/low-key |
| environment | 20% controlled, 40% indoor, 40% outdoor once inventory supports it |
| degradation | 60% pristine, 40% one or more derived variants, capped per family |

## 18. Validation

- camera final values match recipe;
- every promoted person meets intended prominence/framing;
- lighting produces finite nonempty RGB without unintended renderer changes;
- no undeclared human/reflection appears;
- props/support contacts satisfy geometry constraints;
- protected masks match visible prop ownership;
- pristine and annotation pass cameras/crops agree;
- derived-transform chain is invertible/auditable where required;
- no unknown pixel IDs after transformation;
- distribution caps and pairwise targets are reported.
