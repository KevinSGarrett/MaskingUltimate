# ITEMS — Phase P7: Scale & Continuous Operation

Goal: D5 (≥300 gold, coverage ≥80%) + D10 (every runbook operation executed at least once). Parent IDs from doc 14 §8.

## MF-P7-01 — Scale gold 300 → 500 (spec: 12 §2, 01 G6)
- [ ] MF-P7-01.01 Weekly acquisition driven by mining plans (top-10 coverage-deficit cells define what to generate/collect) until **300** approved gold packages exist
- [ ] MF-P7-01.02 Verify coverage matrix ≥ 80% of view×pose cells at target (≥8/cell) and every attribute ≥ 40 — together with 01.01 this closes **D5**
- [ ] MF-P7-01.03 Continue cadence toward the 500-package stretch target (G6)
- [ ] MF-P7-01.04 (If used) Synthetic bootstrapping for stubborn deficit cells: scripted/3D-rendered images per doc 12 §9 · `source_origin: synthetic` · ≤ 30% mix cap · train-only · same QA battery

## MF-P7-02 — Retrain cadence live (spec: 12 §7)
- [ ] MF-P7-02.01 Retrain triggers wired to auto-open a P5 task: +50 new approved gold since champion's dataset · any tracked class error ↑ > 5 pts for 2 weeks · ontology version change
- [ ] MF-P7-02.02 Execute ≥ 1 trigger-driven retrain end-to-end (build @vN+1 → train → leaderboard → promote/reject) · champion history visible in registry

## MF-P7-03 — Operations drills → D10 (spec: 15)
- [ ] MF-P7-03.01 Backup restore drill (15 §5): 3 random packages from B2 → temp restore → `verify-package --root` all pass → one pushed to CVAT usable → logged in OPS_LOG
- [ ] MF-P7-03.02 `maskfactory gc` dry-run reviewed, then `--apply` executed · post-checks (verify sample + reindex) clean
- [ ] MF-P7-03.03 Failure-mining drill: take one acquisition_plan item to full resolution (collect/re-annotate → gold → failure_queue item `resolved: true` with resolution_pkg_version)
- [ ] MF-P7-03.04 Incident drill IP-3: `reindex --rebuild` exercised on a COPY of state.db · diff report empty
- [ ] MF-P7-03.05 Disk headroom review vs 15 §4 thresholds · if tight, execute (or rehearse and document) the junction move procedure
- [ ] MF-P7-03.06 Sign the **D10** checklist with dates in OPS_LOG (backup, retrain, failure mining, gc, incident drill)

## MF-P7-04 — Ontology v2 evaluation (spec: 02 §9, 12 §8)
- [ ] MF-P7-04.01 Evidence review against the growth bar (≥10 distinct failures/30 d per missing boundary): per-toe splits · inner/outer thigh · shin_front · ears 54/55 enablement
- [ ] MF-P7-04.02 Write the go/no-go decision entry into `Plan\CHANGELOG_ONTOLOGY.md` (template §top) — if GO: full change procedure items spawn (ID assignment from reserved range, swap_partner, CVAT label push, back-annotation plan, dataset major bump)

## MF-P7-05 — v2 horizons (spec: 01 §5)
- [ ] MF-P7-05.01 Video segmentation go/no-go memo (SAM2 tracking prerequisites: temporal package schema, per-frame QA cost model)
- [ ] MF-P7-05.02 Multi-person promotion go/no-go memo (atomic masks for person 2+: ontology namespacing + throughput impact)

## Standing Weekly Rhythm (recurring — not one-time; from doc 14 §10 / 15 §2–3)
Mon mining review (30 min) → Tue–Thu build → Fri annotation block + backup verify → every session: `doctor` at start, `git push` + `dvc push` at end · nightly automation (B1/B5/integrity/lint) and weekly (B2, IAA, coverage, gc dry-run) keep running from P1-09/P4-03 setup.

## P7 / PROJECT Exit Gate
- [ ] MF-P7-EXIT All D1–D10 boxes in doc 00 §4 checked with evidence · **headline test passed:** 20 never-seen images → full pipeline → approved gold in ≤ 4 h operator time with zero format or L/R failures (doc 01 §10)
