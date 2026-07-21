# 04 — Item Execution Guide

How to go from a single checklist line to a verified, tracker-recorded piece
of work. Read the notation guide once, then use the three worked examples
as templates for the type of item you're facing.

---

## 1. How To Read An Item

Every item line follows the same shorthand, carried over from
`Plan\Items\*.md`:

- **`·` (middle dot)** separates distinct sub-clauses within one item — treat
  each clause as its own mini-requirement, all of which must hold.
- **Backtick-quoted text** (`` `configs\ontology.yaml` ``, `` `dvc push` ``)
  is a literal path, filename, command, or exact string — use it verbatim,
  don't paraphrase or "improve" it.
- **`→`** indicates an expected result or outcome ("`nvidia-smi` → 592.01"
  means: run that command, the version shown should be 592.01 or higher).
- **`**GATE**` / `**D#**` / `**HARD BLOCKER**`** marks a threshold that is
  the actual pass/fail criterion for a hard blocker or Definition-of-Done
  item — these need a real measured number compared against a real
  threshold, not a judgment call.
- The **cluster header** above a group of items (`## MF-P#-## — <title>
  (spec: <ref>)`) is where the authoritative spec reference lives. It
  applies to every item underneath it until the next cluster header.

Before implementing, always open the actual spec section named there —
don't work from what you remember it probably says.

## 2. Clusters Are Usually One Coherent Task

A cluster (e.g. `MF-P2-05` — GDINO assist + SAM2 refinement, 8 items) is
almost always a single real implementation effort that's been split into
checkable sub-steps for tracking granularity, not eight independent tasks
to attack in isolation. Read the whole cluster and its full spec section
first, implement it as one coherent piece of work, then verify and record
each sub-item individually once you can point to real evidence for that
specific sub-step. Don't context-switch line-by-line within a cluster —
you'll re-read the same spec section repeatedly and likely miss how the
sub-steps depend on each other.

## 3. Worked Example — Simple Verification Item

**Item:** `MF-P0-01.01` — "Confirm NVIDIA driver ≥ 591 on Windows host
(`nvidia-smi` → 592.01) · record in `Plan\OPS_LOG.md` (create the file)"

1. Read spec: the cluster's `(spec: 06 §1)` — open `Plan\06_...md` §1 to
   confirm the full context (Layer 0 — Windows Host requirements).
2. Execute: run `nvidia-smi` via your tool access.
3. Verify: confirm the printed driver version is ≥ 591.
4. Record: append a dated entry to `Plan\OPS_LOG.md` in the format shown in
   that file's template, with the actual command and actual output.
5. Update tracker:
   ```
   python tracker.py set MF-P0-01.01 --status complete \
     --evidence "nvidia-smi reports driver 592.01; logged in OPS_LOG 2026-07-10 14:02 UTC"
   ```

## 4. Worked Example — Multi-Check Enforcement Item

**Item:** `MF-P1-07.08` — "Seeded-defect fixture per QC-001…010 · pytest:
each trips exactly its QC · human approval CANNOT override a BLOCK
(enforcement test)"

1. Read spec in full: the format QC definitions (`Plan\09` §1), the
   auto-fix policy (`Plan\09` §7), and this cluster's own spec reference as
   printed in `Plan\Items\02_ITEMS_P1_GOLD_FACTORY_MVP.md` — confirm the
   exact citation there rather than trusting a paraphrase here.
2. Build one fixture package per QC (10 fixtures), each deliberately
   broken in exactly the way that QC detects (wrong dims, non-binary
   values, wrong PNG mode, etc.) and nothing else.
3. Write pytest cases asserting: (a) each fixture trips *only* its intended
   QC, not a different one by accident; (b) attempting to force-approve a
   BLOCKed fixture through the packager fails — there is no code path that
   lets a human "override" a BLOCK.
4. Run the suite. All pass, genuinely, before recording anything.
5. Record, e.g.:
   ```
   python tracker.py set MF-P1-07.08 --status complete \
     --evidence "pytest tests/test_qc_enforcement.py: 10/10 fixtures pass, override-attempt test passes; see runs/test_logs/2026-07-xx.txt"
   ```

## 5. Worked Example — Hard-Blocker Gate Item

**Item:** `MF-P5-05.04` — "GATE (**D7**): finger-class mean IoU ≥ 0.70 AND
merged-finger false-split rate < 2%"

This is a hard blocker (`MF-P5-05.04` is in the hard-blocker list) and it
drives Definition-of-Done item D7 directly — treat it with maximum rigor.

1. Read `Plan\12` §6.3 in full for exactly how this evaluation must be run
   (which holdout, which metric definition, which model).
2. Actually run the trained hand-crop specialist against the frozen
   hand-crop test holdout. Get a real number for finger-class mean IoU and
   a real number for the merged-finger false-split rate on the seeded
   ambiguous-hand audit set.
3. Compare against the thresholds, honestly:
   - **If it passes** (IoU ≥ 0.70 AND false-split < 2%): record complete
     with the actual measured numbers as evidence, and also record the
     corresponding Goal measurement:
     ```
     python tracker.py set MF-P5-05.04 --status complete \
       --evidence "finger mIoU 0.73, false-split 1.4% on hand-crop test_holdout, run_id r_20260101_handseg_v3"
     python tracker.py goal G2 --measured "0.73 fingers (hand specialist)" --status met
     ```
   - **If it fails**: do *not* lower the bar, cherry-pick a friendlier
     eval subset, or mark it `blocked`. Record the honest result as
     `failed`, then go back to the earlier items in the same cluster
     (more training data, different hyperparameters, a different crop
     strategy) to actually improve the model:
     ```
     python tracker.py set MF-P5-05.04 --status failed \
       --evidence "finger mIoU 0.61 on hand-crop test_holdout, run_id r_20260101_handseg_v2 — below 0.70 target"
     ```
     Then continue working `MF-P5-05.01`–`.03` (more/better training) before
     re-attempting `.04`. Because D6/D7 are auto-computed from these items'
     status in the tracker, they will correctly show `open` until this
     genuinely passes — there is no way to make the DoD table lie other
     than lying to the tracker yourself, which you never do (rule 3 in
     `02`).

## 6. When An Item's Description References Something Not Yet Built

Some items depend on infrastructure earlier items create (e.g. a P3 lane
item assumes S05's geometry engine from P2 already exists). If you reach an
item and its prerequisite genuinely isn't built yet, that's not an
ambiguity — it's a sequencing issue. Check `python tracker.py list --phase
<earlier phase> --status open` for the missing prerequisite, go build that
first, then return. Don't stub or fake the missing piece to "unblock"
forward progress.
