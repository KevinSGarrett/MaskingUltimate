# Document 13: ComfyUI Integration

Two integration modes, both non-invasive to Kevin's existing native-Windows ComfyUI install:
**Mode A — Package Reader** (offline: nodes read gold/derived masks straight from
`data\packages\`), and **Mode B — Live Inference** (nodes call the FastAPI service for
never-before-seen images using qualified installed models). D8 retains that legacy node/workflow
evidence. Doc 24 adds the production bridge: a controller-side adapter, immutable release/adoption
handshake, exact authority/instance/transform receipts, failure recovery, and claim-scoped core exit.

---

## 1. Node Pack Install (Mode A requires zero heavy deps)

- The pack is a plain folder copied (or junctioned) to
  `ComfyUI\custom_nodes\maskfactory_nodes\` — implemented in `serve\comfy_export.py` source tree
  and versioned with the repo; `maskfactory comfy install --comfy-root <path>` performs the copy
  + writes `maskfactory_nodes\config.json`:
  `{"packages_root": "C:\\Comfy_UI_Main_Masking\\data\\packages", "api_url":
  "http://127.0.0.1:8765", "format_version": "1.x"}`.
- Dependencies: only what ComfyUI already ships (numpy, PIL, torch); Mode A does **no** model
  loading, no cv2, no MMSeg imports — it must never destabilize the ComfyUI env.
- Compatibility: nodes check `manifest.format_version` (doc 04) and refuse packages from a newer
  major version with a clear error instead of misreading them.

## 2. Node Reference (category `MaskFactory/…`)

| Node | Inputs | Outputs | Behavior |
|------|--------|---------|----------|
| MF Package Browser | status filter (default `human_approved_gold`), search | image_id (STRING), count | Lists/paginates packages by reading manifests; feeds ids to loaders |
| MF Load Source | image_id | IMAGE | Loads `source.*` (RGB, 0–1 float) |
| MF Load Gold Mask | image_id, label (dropdown from ontology.yaml) | MASK | Reads `masks\<label>.png`; missing → per `on_missing` toggle: error (default) or empty mask + warning |
| MF Load Union Mask | image_id, union label | MASK | Reads `masks_regions\`/derived union (e.g., both_hands, visible_body_skin) |
| MF Load Projected Region | image_id, projected label | MASK | Reads `projected\`; node UI is purple-tagged NON-TRUTH, mirroring doc 02 §5 |
| MF Load Inpaint Mask | image_id, label, dilate_px (def 8), feather_px (def 4), mode existing/derive | MASK | `existing`: loads `inpaint\inpaint_<label>_d<k>f<f>.png` if present; `derive`: computes on the fly with the exact `derive-inpaint` algorithm (binary dilate, then Gaussian feather ramp), scaled by image size @1024 ref. On-the-fly results are never written back to the package |
| MF Mask From Label Map | image_id, map (part/material), id or name | MASK | Binarizes directly from `label_map_part/material.png` — any ID, even ones without exported binaries |
| MF Combine Masks | mask_a, mask_b, op (union/intersect/subtract/xor), binarize (bool) | MASK | Pixel ops at full res; refuses shape mismatch |
| MF Mask Stats | mask | STRING | area px/%, bbox, component count — for QA-in-workflow |
| MF Predict Masks (Mode B) | IMAGE, labels csv, dilate/feather (optional) | MASK batch, label list, JSON | POSTs the image to the API; returns requested masks from champion models |

**AMENDED (doc 17 §11):** every node above that takes `image_id` also takes an optional
`person_index` input, **defaulting to 0** — every existing single-person workflow keeps working
with zero changes. The Package Browser lists `(image_id, person_index)` pairs once multi-instance
packages exist. Paths resolve to `data\packages\<image_id>\instances\p<person_index>\...`
(doc 03 §2).

Mask semantics: ComfyUI MASK = float [0,1], H×W. Gold binaries map {0,255}→{0.0,1.0} exactly;
inpaint feather ramps keep their gradient. **Nodes never resize silently** — every mask must
match the source dims or the node errors (Global Convention 2 survives into ComfyUI).

## 3. Inference Service (`serve\api.py`, Mode B — built in P6)

- FastAPI + uvicorn inside WSL2, bound **127.0.0.1:8765** (localhost only, no auth surface;
  Windows reaches it via WSL localhost forwarding). Start: `maskfactory serve --port 8765`.
- Endpoints:
  `GET /health` → versions, loaded models, VRAM;
  `GET /models` → registry roles + champion pointers;
  `POST /predict` (multipart image + `{labels:[], return: binaries|label_maps|both,
  inpaint:{dilate,feather}|null}`) → base64 PNGs + a manifest-lite JSON (per-label visibility
  guess, areas, model provenance);
  `POST /refine` (image + label + clicks[]) → SAM2 single-part interactive refine (powers
  click-fix inside future ComfyUI UIs).
- Model residency loads champion body-part, hand-specialist, and clothing
  providers directly on the selected RunPod. No GPU/VRAM scheduler, reservation,
  checkout, or `runs\gpu.lock` refusal governs service execution.
- Latency targets (1024 px): /predict warm ≤ 4 s all-labels, ≤ 2 s single-label; /refine ≤ 1.2 s
  per click. Cold start ≤ 60 s.
- Predictions are drafts by definition: `status: draft_model_generated` in the returned JSON;
  the service never writes into `data\packages\`.

## 4. Reference Workflows (shipped as JSON in `maskfactory_nodes\workflows\`)

1. **wf_inpaint_gold_hand.json** — Package Browser → Load Source + Load Inpaint Mask
   (left_hand, d8f4) → VAEEncode(inpaint) → sampler → composite: repaint a hand with a gold-true
   edit region.
2. **wf_bodypart_conditioned.json** — Load Union (visible_body_skin) + Combine(subtract
   clothing_visible via Mask From Label Map/material=3) → use as attention/latent mask for
   skin-only img2img without touching clothing.
3. **wf_live_predict_inpaint.json** — LoadImage (any new image) → MF Predict Masks
   (left_forearm) → inpaint chain: the full Mode-B loop with zero pre-annotation.

## 5. Failure Modes & Rules

- Package not found / not approved → node error listing nearest ids + statuses (never silently
  loads a rejected package's masks).
- API down → Predict node raises with the exact `maskfactory serve` command to run.
- Version skew (node pack older than package format) → hard error per §1.
- The node pack is read-only by design: **no ComfyUI path may mutate gold** (mirrors doc 03 §6 /
  QC-030). Anything ComfyUI produces is ordinary workflow output, outside the truth chain.

## 6. Production Controller Bridge (doc 24 authority)

The node pack is not the autonomous control plane. The main ComfyUI project owns an external
`MaskFactoryAdapter` that submits/reads through versioned contracts and binds each result into its pass
DAG. ComfyUI nodes remain thin operator/execution helpers and never own durable retry, route,
certificate, promotion, cache, or recovery decisions.

Mode A validates an immutable package, source and mask hashes, ontology, character/scene instance,
provider person index, coordinate transforms, exact authority/certificate scope, and revocation state.
Mode B validates health/capabilities and returns drafts by default. A Mode B artifact reaches production
authority only through a separate MaskFactory operational-certification transaction; the API response,
node, LLM, and main controller cannot self-upgrade it.

The adapter blocks only the dependent pass where safe. Service outage, missing capability, ambiguous
instance, transform mismatch, incompatible version, stale/revoked certificate, insufficient authority,
or hash drift produces a typed error. It never silently substitutes an empty mask, wrong person, weaker
truth tier, or unqualified provider.

## 7. Release and Session Handshake

The MaskFactory session publishes immutable release and capability snapshots with Git/build/node-pack/
wheel/API/OpenAPI/schema/package-format/ontology/workflow/evidence hashes. The main-project session
publishes consumer requirements and an adopted/partially-adopted/rejected receipt. Both projects pin the
same snapshot and run compatibility fixtures. Dirty worktrees, editable installs, and copied-but-unpinned
node packs are not production authority.

Certificate, package, provider, ontology, policy, capability, and release changes emit idempotent
invalidation events. The main controller invalidates affected routes/cache and revalidates. It returns
hash-bound repair feedback, but never mutates MaskFactory packages or certificates.

## 8. Core Integration Qualification

`core_autonomous_runtime` requires:

1. clean installation with source/installed node inventory parity;
2. single-person Mode A package-to-inpaint/edit vertical slice;
3. overlapping/contact two-person Mode A ownership/transform slice;
4. Mode B draft prediction/refinement and service-down behavior;
5. separate subsequent certification of an eligible exact original Mode B prediction plus an abstained
   branch, while proving refinement/derived descendants cannot exceed parent authority;
6. incompatibility, hash, authority, transform, idempotency, outage, OOM, restart, stale-cache,
   invalidation, and rollback fault tests; and
7. matching MaskFactory release and main-project adoption receipts.

Human-anchor masks, CVAT corrections, package-volume targets, full-library download, DAZ, and soak
evidence are not prerequisites for this core integration profile.
