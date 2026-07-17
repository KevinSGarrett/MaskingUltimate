# ITEMS — Phase P6: ComfyUI Integration & Serving

Legacy trained-champion lane goal: D8 — the node pack loads package/predicted masks and produces
derived inpaint masks inside a workflow. Its former D6 prerequisite applies only to that optional
trained-champion lane. The required human-free autonomy/bridge lane is `MF-P6-07` through
`MF-P6-12` (doc 24) and has no D6, human, CVAT, or package-volume prerequisite. Parent IDs from doc
14 §7.

## MF-P6-01 — Node pack Mode A (spec: 13 §1–2)
- [ ] MF-P6-01.01 Implement all Mode-A nodes in `serve\comfy_export.py` tree: MF Package Browser · MF Load Source · MF Load Gold Mask (ontology dropdown) · MF Load Union Mask · MF Load Projected Region · MF Load Inpaint Mask (existing + on-the-fly derive with dilate/feather params, never written back) · MF Mask From Label Map (any PART/MATERIAL id) · MF Combine Masks (union/intersect/subtract/xor) · MF Mask Stats
- [ ] MF-P6-01.02 `maskfactory comfy install --comfy-root <path>`: copy/junction into `ComfyUI\custom_nodes\maskfactory_nodes\` + write `config.json` {packages_root, api_url 127.0.0.1:8765, format_version}
- [ ] MF-P6-01.03 Mode-A dependency audit: numpy/PIL/torch only — no cv2, no mmseg, no model loads (must never destabilize the ComfyUI env)
- [ ] MF-P6-01.04 `manifest.format_version` check: newer-major package → clear refusal error, never misread
- [ ] MF-P6-01.05 Mask semantics enforced: {0,255} → {0.0,1.0} exactly · inpaint feather ramps preserved · NO silent resize — dims mismatch = node error (Global Convention 2)
- [ ] MF-P6-01.06 `on_missing` toggle (error default / empty+warning) · Projected node UI purple-tagged NON-TRUTH · Browser filters by status (default human_approved_gold) and never silently loads rejected packages
- [ ] MF-P6-01.07 Author `maskfactory_nodes\workflows\wf_inpaint_gold_hand.json` · runs end-to-end in ComfyUI (gold left_hand d8f4 inpaint chain)

## MF-P6-02 — FastAPI inference service (spec: 13 §3)
- [ ] MF-P6-02.01 `serve\api.py`: GET /health (versions, loaded models, VRAM) · GET /models (registry roles + champions) · POST /predict (multipart image + labels/return/inpaint params → base64 PNGs + manifest-lite JSON with per-label visibility guess, areas, provenance) · POST /refine (image + label + clicks → SAM2 single-part refine)
- [ ] MF-P6-02.02 uvicorn bound 127.0.0.1:8765 inside WSL2 (localhost only) · `maskfactory serve --port 8765` command wired
- [ ] MF-P6-02.03 Model residency per doc 05 §5 schedule: champion body-part + hand specialist + clothing parser sequential slots · SAM2 loaded on demand for /refine
- [ ] MF-P6-02.04 `runs\gpu.lock` mutual exclusion with pipeline/training · refusal error names the lock holder · demonstrated both directions
- [ ] MF-P6-02.05 Latency measured: /predict warm ≤ 4 s all-labels · ≤ 2 s single-label · /refine ≤ 1.2 s/click · cold start ≤ 60 s
- [ ] MF-P6-02.06 Responses carry `status: draft_model_generated` · service has NO write path into `data\packages\`

## MF-P6-03 — Mode B node + shipped workflows (spec: 13 §2/§4)
- [ ] MF-P6-03.01 MF Predict Masks node: multipart POST to the API · base64 decode · MASK batch + label list + JSON out · API-down error prints the exact `maskfactory serve` command
- [ ] MF-P6-03.02 Author + verify `wf_bodypart_conditioned.json` (visible_body_skin − clothing_visible via Mask From Label Map → skin-only img2img)
- [ ] MF-P6-03.03 Author + verify `wf_live_predict_inpaint.json` on a NEVER-SEEN image (LoadImage → Predict left_forearm → inpaint) — this run is the **D8** demonstration
- [ ] MF-P6-03.04 File all three workflow JSONs in `maskfactory_nodes\workflows\`

## MF-P6-04 — Read-only enforcement audit (spec: 13 §5)
- [ ] MF-P6-04.01 Mutation-attempt fixture test: any write attempt from node code under `data\packages\` errors (QC-030 parity)
- [ ] MF-P6-04.02 Static audit: grep/CI check that no ComfyUI-side code path opens package files in write mode

## P6 Legacy Trained-Champion Lane Exit Gate
- [ ] MF-P6-EXIT **D8** demonstrated live for the optional legacy lane (Mode A + Mode B workflows) · doc 14 §7 checkboxes updated · This item does not define project-wide or `core_autonomous_runtime` completion; the required adopted bridge exit is `MF-P6-12.06`
