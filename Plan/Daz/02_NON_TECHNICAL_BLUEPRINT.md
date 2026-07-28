# Non-Technical Blueprint

## 1. The idea in plain language

DAZ Studio supplies rigged adult figures, body-shape controls, skin materials, hair, clothing, poses,
cameras, lights, rooms, outdoor sets, and props. MaskFactory will use those building blocks to create
large numbers of controlled synthetic images. Because the subsystem controls the 3D scene, it can also
produce an exact answer sheet for the pixels: which person owns each pixel, which body region it
represents, whether it is skin or clothing, what is in front, and what is hidden.

Kevin does not pose or dress every character. After assets are installed, the
system catalogs them, tests them, combines compatible items under strict constraints, rejects broken
results, and remembers the exact seed and recipe for every accepted or failed scene.

## 2. The end-to-end operating loop

1. **Kevin obtains assets.** Kevin purchases or downloads figures, morphs, hair, wardrobe, poses,
   cameras, lights, environments, and props. No automation spends money.
2. **The asset enters technical qualification.** Newly installed content is scanned, hashed, linked to
   its product and dependencies, and placed in a pending state.
3. **The subsystem identifies it.** It determines whether the item is for Genesis 9, Genesis 8.1, or
   something else; whether it is a pose, material, hair, garment, prop, camera, light, or morph; and
   what it depends on.
4. **The subsystem tests it.** A small scene is built and rendered. Missing files, pop-up dialogs,
   incompatible rigging, clothing explosions, invalid textures, extreme intersections, and wrong
   metadata cause automatic quarantine.
5. **A coverage planner decides what is needed.** It looks for deficits such as rear views, crouching,
   dark skin under hard light, long hair covering shoulders, hands touching another body, two people
   crossing limbs, small anatomy regions, loose clothing, or low camera angles.
6. **A scene recipe is generated.** A deterministic seed selects compatible adult figures, body shapes,
   materials, hair, wardrobe state, poses, cameras, lights, environments, and props. Constraints prevent
   impossible or incompatible combinations.
7. **DAZ Studio builds the scene.** A dedicated scripted worker loads the required assets, applies
   bounded morph values, positions the characters, resolves fit/simulation, frames the camera, and runs
   geometry checks.
8. **The scene is rendered in layers.** It produces a normal RGB image plus exact person, part,
   material, depth, normal, visibility, contact, and occlusion passes.
9. **Automated QA tries to disprove the scene.** Every pass is checked for dimensions, allowed ID values,
   holes, missing people, person overlap, left/right consistency, mapping completeness, mask/RGB
   alignment, missing textures, clipping, intersections, and reproducibility.
10. **Failures are handled without Kevin.** A bounded repair may adjust framing, pose separation, cloth
    settling, or an asset choice. Otherwise the sample is rejected and the bad combination is recorded.
11. **Accepted samples are sealed.** The exact recipe, assets, hashes, DAZ version, mapping version,
    render settings, and output hashes are stored together.
12. **MaskFactory ingests the result.** Accepted samples enter a separate synthetic lane, run the normal
    package verifier and QA battery, and become low-weight train-only supervision.
13. **Training uses a controlled mixture.** Synthetic content never exceeds 30% of a training set and
    never enters real holdouts. Experiments compare real-only training against real-plus-DAZ training.
14. **Only real-image results matter for promotion.** If DAZ improves real human-anchor IoU,
    boundary-F, hands, hair, anatomy, clothing, and multi-person performance without regressions, the
    enriched model may be promoted. Otherwise the model and mixture are rejected.

## 3. What becomes autonomous

After installation, the following are autonomous:

- asset discovery and fingerprinting;
- asset-type and figure-generation classification;
- dependency and compatibility graph construction;
- load/fit/render smoke tests;
- quarantine, retry, and retest after updates;
- coverage-gap analysis;
- single- and multi-character recipe creation;
- body shape, skin, hair, wardrobe, pose, camera, light, background, and prop selection;
- scene assembly, constrained positioning, and camera framing;
- rendering of RGB and annotation passes;
- quality checks, rejection, bounded repair, and deterministic replay;
- package creation, hashing, manifests, reports, retention, and backup;
- training-build proposals and synthetic-ratio enforcement;
- scheduled ablations and candidate evaluation once eligible real data exists.

## 4. What remains Kevin's responsibility

- Buy or download assets and approve any expense.
- Approve adding storage or paid compute.
- Supply or authorize the real-image evaluation corpus required by MaskFactory's existing plan.

Kevin does not need to create one `.duf` scene per combination, manually pose characters, hand-label
DAZ renders, or manually fix routine rejected scenes.

## 5. Diversity the subsystem intentionally creates

The system is not a random character maker. It is a coverage engine. It systematically varies:

- one, two, three, and four adult characters;
- adult male-anatomy and adult female-anatomy figure configurations, mixed in all count combinations;
- masculine, feminine, and androgynous styling independently of anatomy configuration;
- height, weight, muscularity, proportions, shoulder/hip/chest shape, limb length, and adult
  age-appearance category;
- skin tone, undertone, visible skin variation, and material response;
- bald/shaved through very long hair; straight, wavy, curly, coily, braided, loc'd, tied, and facial hair;
- unclothed, underwear, swimwear, fitted, loose, layered, formal, casual, athletic, outerwear, gloves,
  socks, footwear, hats, jewelry, and accessories;
- standing, walking, seated, crouched, kneeling, lying, reaching, twisting, athletic, dance, balance,
  self-contact, hand-to-body contact, and difficult foreshortened poses;
- separated people, partial overlap, front/back occlusion, touching, embracing, side-by-side support,
  crossed limbs, seated groups, scale differences, truncation, and crowded compositions;
- front, back, profile, three-quarter, high, low, overhead, ground-level, rolled, close, medium, and full
  views with broad focal lengths;
- soft studio, hard studio, sunlight, overcast, backlight, rim light, low-key, high-key, practical,
  mixed-color, and difficult shadow conditions;
- plain, patterned, indoor, outdoor, furnished, cluttered, high-contrast, and low-contrast backgrounds;
- support surfaces, handheld objects, furniture, and accessories that cause meaningful occlusion;
- clean imagery plus controlled blur, noise, resizing, compression, exposure, and color shifts.

Every variation is recorded. Caps prevent one favorite asset or pose pack from dominating the corpus.

## 6. Why the masks can be exact but the real-world result is not guaranteed

The renderer knows exactly which synthetic triangle produced a pixel. That allows nearly pixel-perfect
synthetic annotations after edge and transparency rules are enforced. It does not prove the trained
model is nearly perfect on photographs. Real images contain sensor behavior, anatomy, fabrics, hair,
lighting, motion, environments, compression, art styles, and human interactions that synthetic assets
may not reproduce.

The strategy therefore uses DAZ for what it is unusually good at: precise labels, rare poses, controlled
occlusion, balanced left/right, small body parts, anatomy, and repeatable experiments. Real-image
human-anchor holdouts remain the judge. The system abstains rather than claiming unmeasured perfection.

## 7. Character and anatomy coverage

The generator supports adult male and adult female DAZ figures in clothed, partially clothed, and
unclothed configurations. Anatomy configuration is explicit scene metadata because it determines which
geometry and ontology mappings apply. All configurations use the same
technical requirements for mapping completeness, visible-pixel truth, instance ownership, render-pass
alignment, deterministic replay, and package validation.

## 8. What success looks like

Operational success means Kevin can add cleared assets and the system can run unattended for long
periods, with no silent dialogs, no unlabeled pixels, no cross-person mask bleed, reproducible scenes,
controlled storage use, and clear reports of accepted/rejected samples and coverage gains.

Model success means a DAZ-enriched challenger materially improves untouched real-image performance,
especially hard boundaries, fingers, toes, hair, clothing, adult anatomy, contact, occlusion, and
multi-person identity, while meeting every existing MaskFactory non-regression and rollback check.
