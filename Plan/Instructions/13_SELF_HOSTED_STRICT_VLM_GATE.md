# 13 — Self-Hosted STRICT VLM Gate (RunPod / loopback Ollama)

**Binding.** Supplements `Plan/STANDING_ORDERS_AUTONOMOUS_BUILD.md` § SELF-HOSTED STRICT VLM GATE.
Cloud LLMs are forbidden for MaskFactory VLM QA. **NEVER EC2.**

---

## 1. Purpose

MaskFactory autonomy must not blind-approve tournament winners, CAA samples, gold,
champions, or package-freeze panels. A **self-hosted high-end vision LLM** on
loopback Ollama (`127.0.0.1:11434`) performs STRICT visual review on real
**source / mask / overlay** panels, with fail-closed behavior when Ollama or
models are unavailable.

---

## 2. Models & determinism

| Role | Model | Notes |
|------|-------|-------|
| STRICT primary | `llava:13b` | Preferred high-end critic |
| STRICT alternate high-end | `llama3.2-vision:11b` | Allowed primary substitute when llava unavailable |
| Ensemble secondary | `qwen2.5vl:7b` | Must agree for pass; **never sole rubber stamp** |
| S11 calibrated (legacy) | `qwen2.5vl:7b` via `models.primary_vlm` | Production S11 fingerprint until recalibrated — **not** autonomy sole critic |

- `temperature=0`, `seed=1337`, structured JSON only.
- Config: `configs/vlm.yaml` → `strict_visual_gate`.
- Governance: `may_author_masks=false`, `may_approve_gold=false`, `may_clear_blocks=false`.

---

## 3. Rubric (FAIL fails closed)

Every review returns JSON with overall `verdict` plus per-dimension scores:

1. **anatomy** — correct body/part structure for the label
2. **boundary** — edge tightness vs visible silhouette
3. **leakage** — spill into background / clothing / neighbor parts
4. **emptiness** — blank when content visible, or flooded when sparse
5. **label_consistency** — mask matches claimed label / L-R / context
6. **overlay_contour_review** — overlay/contour tiles corroborate mask

Any dimension `fail` ⇒ overall fail ⇒ abstain/reject/repair — **not gold**.

---

## 4. Mandatory call sites

| Scope | Tool / hook |
|-------|-------------|
| Tournament MVC visual hard QA | `tools/run_tournament_mvc_visual_hard_qa.py` |
| Critic router (residual / burst) | `tools/run_tournament_ollama_critic_router.py` |
| CAA / autonomous gold admission | `configs/autonomy_autonomous_gold_profile.yaml` + `tools/build_autonomous_gold_admission.py` (`require_strict_visual_gate_pass`) |
| Live confirmation smoke | `tools/smoke_strict_vlm_gate.py` |
| Core library | `src/maskfactory/vlm/strict_gate.py` |

`--skip-vlm` and critic-disabled modes must record **`VISUAL_CRITIC_BLOCKED`**, never a pass.

---

## 5. Operating procedure (every visual wave)

1. Live-probe Ollama: `curl -s http://127.0.0.1:11434/api/tags` — confirm `llava:13b` and `qwen2.5vl:7b`.
2. Check GPU: `nvidia-smi`. If hand/clothing tournament workers own VRAM, **wait or serialize** — do not kill healthy hand PIDs unless brief serialize is required; then resume.
3. Render panels (source/mask/overlay). Do not claim visual QA from mask PNG decode alone.
4. Run STRICT critic burst; seal evidence under `qa/live_verification/` with model id, prompt hash, response, panel hashes.
5. Unload VLMs after burst (`strict_visual_gate.unload_after_burst` / `unload_model`).
6. Update tracker via `tracker.py` only; append OPS_LOG + DECISIONS_LOG.

### Example commands

```bash
source /workspace/paths.env
cd /workspace/maskfactory
python tools/smoke_strict_vlm_gate.py \
  --output qa/live_verification/strict_vlm_gate_confirmed_$(date -u +%Y%m%dT%H%M%SZ).json
python tools/run_tournament_ollama_critic_router.py \
  --machine-root runs/hand_tournament_full120 --label hand --limit 4 \
  --write-sidecars \
  --output qa/live_verification/tournament_ollama_critic_router_$(date -u +%Y%m%dT%H%M%SZ).json
python tools/run_tournament_mvc_visual_hard_qa.py \
  --machine-root runs/hand_tournament_full120 --limit 4 \
  --output qa/live_verification/tournament_mvc_visual_hard_qa_$(date -u +%Y%m%dT%H%M%SZ).json
```

---

## 6. Honesty boundaries

- Hard QC BLOCK is absolute; VLM cannot clear it.
- STRICT pass retains `machine_verified_candidate` toward CAA — **not gold by itself**.
- CAA / `autonomous_certified_gold` still requires Wilson / serious bounds + STRICT visual coverage.
- Prior qwen-only 24/24 Hard-QA seals are **insufficient** under this mandate until re-run on high-end primary + ensemble.
- Hand MVC emitted without `*.visual_hard_qa.json` / `*.strict_vlm_gate.json` sidecars are **not** CAA-ready.

---

## 7. Evidence seals

- Audit: `qa/live_verification/strict_vlm_gate_audit_latest.json`
- Confirmation: `qa/live_verification/strict_vlm_gate_confirmed_latest.json`
