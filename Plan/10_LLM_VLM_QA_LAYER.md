# Document 10: LLM / VLM QA Layer

Role (constitutional): the LLM/VLM layer is the **brain / QA / router — never the scalpel**.
It decides which masks are required, reads manifests, catches missing labels, compares overlay
panels, produces QA reports, routes hard cases, generates correction instructions, checks L/R
naming, and detects impossible claims. It never authors pixel masks.

---

## 1. Model Selection (decision made)

| Slot | Model | Runtime | Use |
|------|-------|---------|-----|
| Primary VLM | **Qwen2.5-VL 7B Q4** | Ollama (Docker, 127.0.0.1:11434) | All image-panel review — local, private, no content-block friction on body-part QA |
| Fallback VLM | llama3.2-vision 11B Q4 | Ollama | If Qwen unavailable/regresses on eval set |
| Text LLM (local) | qwen2.5:7b-instruct | Ollama | Manifest lint, correction-instruction drafting |
| Cloud LLM (optional) | Claude API | text-only | Non-sensitive reasoning: QA report summarization, ontology consistency review, roadmap/ops docs. **Never receives source images or overlays** (`vlm.cloud_enabled: false` default) |

VRAM: VLM runs in its own exclusive GPU slot (doc 05 §5). Batch S11 model-major.

## 2. Inputs Per Review

- Per hard part: the 5-tile zoom panel (doc 09 §6), downscaled to 1024 long side for the VLM.
- Whole image: source + all-parts color overlay + compact manifest digest (label:state:area% table).
- The relevant qa_report excerpts (which QCs warned/routed).

## 3. Prompt Suite (versioned in `src\maskfactory\vlm\prompts\`, version stamped in reports)

**P-PART (per-part panel):**
"You are auditing a body-part segmentation mask for label `<label>` (left/right is from the
CHARACTER's perspective). Panel tiles: source crop, mask, overlay, contour, protected-overlap
heat. Answer STRICT JSON only: {verdict: pass|fail|uncertain, confidence: 0-1, problems: [subset of
[wrong_part, wrong_side, boundary_too_loose, boundary_too_tight, includes_clothing_as_skin,
includes_background, includes_neighbor_part, missing_visible_area, mask_on_hidden_area,
finger_merge, hair_edge_bad, occlusion_error, other]], evidence: '<≤25 words pointing at panel
location>', correction_instruction: '<≤30 words imperative for the annotator>'}."

**P-IMAGE (whole-image sanity):**
"Given the overlay and this manifest digest, list: (a) labels marked visible whose mask appears
missing/misplaced, (b) visible body parts with no visible-state entry, (c) any left/right naming
that contradicts the character's orientation, (d) any mask claiming an area that is clearly
clothing-covered or out of frame. STRICT JSON: {missing:[], mislabeled:[], lr_suspect:[],
impossible_claims:[], notes: ''}."

**P-MANIFEST (text LLM):** lint manifest vs ontology (states complete, subsets consistent,
occlusion graph acyclic, notes quality) → JSON findings.

Parsing: responses must parse as JSON; one retry with "JSON only" reminder; still bad → verdict
`uncertain` (never guess).

## 4. Verdict Schema & Calibration

Verdicts append to `qa_report.vlm_review.verdicts[]`:
`{label, panel_file, model, prompt_version, verdict, confidence, problems[], evidence,
correction_instruction, latency_ms}`.
Calibration set: 40 panels with known ground truth (20 good / 20 seeded-defect) maintained under
`qa\vlm_eval\`; `maskfactory vlmqa eval` must show ≥ 0.90 recall on defects and ≥ 0.80 precision
before a model/prompt version is allowed in production (gate MF-P4-05). Re-run on every model or
prompt change.

## 5. Routing Logic (`vlm/router.py`)

| Auto-QA | VLM verdict | Route |
|---------|-------------|-------|
| all pass | pass ≥0.7 conf | **quick-pass queue** (human skim, expected <1 min/part group) |
| all pass | fail | careful queue + VLM correction_instruction attached to CVAT task |
| ROUTE flags | pass | careful queue (auto-QA wins for caution) |
| ROUTE flags | fail | careful queue, priority ↑, disagreement heatmap pinned |
| any | uncertain | careful queue, no annotation hints (avoid anchoring) |
VLM can NEVER approve gold, NEVER clear a BLOCK, NEVER edit a mask. Its correction instructions
are suggestions shown to the human, marked as machine-generated.

## 6. Cloud Boundary & Privacy Rules

Hard rules: source images, crops, overlays, panels never leave the machine. Cloud LLM (if
enabled) receives only: text manifests with image_id (hash-derived, no PII), QA statistics,
ontology text, code. Toggle + audit log at `logs\cloud_calls.jsonl` (payload hashes recorded).

## 7. Intake Safety Screen (referenced by S00 step 5)

Local VLM prompt (age-safety): whole-image classification "does this image depict a real or
apparent minor?" → yes/uncertain ⇒ quarantine + log; only clear adult/stylized-adult content
proceeds. Conservative by design; quarantine review is manual and the rule itself is
non-configurable (doc 01 §7).

## 8. Additional LLM Duties (batch jobs)

- Nightly: manifest lint sweep (P-MANIFEST) across new packages → findings report `qa\reports\`.
- Weekly: failure_queue clustering — text LLM groups failure_reason strings, proposes coverage
  targets (feeds doc 12 §7), drafts the weekly QA summary markdown.
- On ontology change: consistency review of ontology.yaml vs doc 02 tables (diff explanation).
