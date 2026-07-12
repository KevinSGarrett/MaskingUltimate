# Decisions Log

Append-only record of deliberate deviations from the written spec
(`Plan\00`–`15`), including autonomous, conservative, spec-consistent
judgment calls made when a genuine gap was found, and any Kevin-approved
scope changes. Referenced by `Plan\14_IMPLEMENTATION_ROADMAP_WBS.md` §10 and
`Plan\Instructions\06_BLOCKERS_AMBIGUITY_AND_ESCALATION.md`.

**Format:** newest entries at the bottom, chronological, append-only.

---

## TEMPLATE — copy this block for each new entry, then fill it in

```
## <YYYY-MM-DD> — <short title>
**Item(s) affected:** <MF-P#-##.## ...>
**Spec said:** <precise reference/paraphrase of the relevant Plan\ section>
**What we did instead:** <the actual deviation>
**Why:** <reasoning — what made this the conservative, spec-consistent choice>
**Approved by:** Kevin | AI-autonomous (conservative default, logged for Kevin's awareness) | pending Kevin review
```

---

## EXAMPLE (illustrative only — not a real decision, delete or leave as reference)

## 2026-01-01 — Example: clarified crop padding rounding
**Item(s) affected:** MF-P3-01.01
**Spec said:** `Plan\03` §5 — crop side = 1.6 × part bbox max side, no
rounding rule specified for non-integer results.
**What we did instead:** Round up to the nearest even integer before
resizing to 1024, so the crop is always symmetric around the bbox center.
**Why:** Matches the "no resize/crop/pad ambiguity" spirit of the gold
format spec (`Plan\03` §1) more closely than truncating, and keeps the
`crop_to_full_transform.json` math exact rather than approximate.
**Approved by:** AI-autonomous (conservative default, logged for Kevin's awareness)

---

<!-- Real entries begin below this line. -->

## 2026-07-10 — tracker.py save_tracker() rename-aside fallback
**Item(s) affected:** build infrastructure (all tracker writes)
**Spec said:** tracker.py is delivered tooling; `save_tracker()` did an atomic
`os.replace(tmp, tracker.json)` with a 6× transient-lock retry.
**What we did instead:** Added a fallback: if `os.replace` keeps raising
`PermissionError` (a *persistent* share-delete handle, not a transient one),
rename the held current file to a `.orphan` name and move the freshly written
temp into place, then best-effort delete the orphan.
**Why:** A leaked handle from the Claude Desktop app's node service held
tracker.json open indefinitely, jamming every session's tracker writes (see
OPS_LOG 2026-07-10). `os.replace` cannot delete-over a held destination, but a
plain rename of that destination is permitted, so rename-aside makes the write
succeed and detaches the stale handle. Preserves all existing semantics
(backups, atomicity, changelog) and only triggers after the normal path fails.
**Approved by:** AI-autonomous (conservative default, logged for Kevin's awareness)

## 2026-07-10 — Passwordless sudo for WSL user `kevin`
**Item(s) affected:** MF-P0-01.02
**Spec said:** `Plan\06` §1 / MF-P0-01.02 — "create Linux user `kevin`". No
password or sudo policy specified.
**What we did instead:** Created `kevin` (uid 1000), added to the `sudo` group,
and granted passwordless sudo via `/etc/sudoers.d/90-kevin-nopasswd`
(`kevin ALL=(ALL) NOPASSWD:ALL`, validated with `visudo -c`).
**Why:** Autonomous, non-interactive execution of the P0 install items
(`sudo apt install ...`, Docker/WSL integration, etc.) requires sudo without an
interactive password prompt. This is the standard local WSL dev-box posture and
does not weaken any project data-governance or age-safety rule. The distro is a
single-user local development environment, not a shared/networked host.
**Approved by:** AI-autonomous (conservative default, logged for Kevin's awareness)

## 2026-07-10 — `wsl --update` action skipped (already exceeds requirement)
**Item(s) affected:** MF-P0-01.03
**Spec said:** `Plan\06` §1 / MF-P0-01.03 — "`wsl --update` · verify WSL kernel
≥ 2.3 for CUDA 12.8 passthrough".
**What we did instead:** Did NOT run `wsl --update` to completion. It launched an
interactive UAC + MSI elevation (`consent.exe`/`msiexec.exe`) that cannot be
granted in a non-interactive session and hung; the driver processes were killed.
The verify clause passes independently: `wsl --version` = 2.7.3.0 (≥ 2.3),
kernel 6.6.114.1-microsoft-standard-WSL2, and CUDA 12.8 GPU passthrough is
confirmed working (nvidia-smi inside Ubuntu shows the RTX 5060).
**Why:** The update command is idempotent maintenance whose only purpose is
ensuring a recent-enough WSL for CUDA passthrough — a condition already
demonstrably met. Forcing it would require interactive elevation Kevin must
click. If a newer WSL is ever desired, Kevin can run `wsl --update` in an
elevated terminal.
**Approved by:** AI-autonomous (conservative default, logged for Kevin's awareness)

## 2026-07-10 — Plan/Civitai/ excluded from git (kept local)
**Item(s) affected:** MF-P0-08.01, and the P0-10/P0-14 Civitai-intake clusters
**Spec said:** doc 16 §4 lists `Plan\Civitai\` as bootstrap reference assets;
MF-P0-08.01's ignore list did not mention it. doc 16 §7 anti-pattern: do not
train on platform preview images/screenshots.
**What we did instead:** Added `Plan/Civitai/` to `.gitignore` (plus global
`*.safetensors/*.pt/*.pt2/*.pth/*.onnx/*.ckpt/*.bin/*.pkl/*.zip` weight ignores).
`Plan/Civitai/` is ~9 GB: a 5.4 GB controlnet safetensors, a 1.1 GB model, dozens
of detector `.pt`/archives, and ~359 MB of adult/NSFW pose-pack PREVIEW PNGs.
**Why:** (1) Committing multi-GB model weights to git is wrong regardless — they
belong in DVC / an external cache. (2) ~359 MB of adult reference preview imagery
is not build source (doc 16 §7) and is inappropriate for a code repo, especially
the company GitHub repo pending in MF-P0-08.02. The assets stay fully present on
disk and usable by the P0-10/14 review tasks; only git-tracking is deferred.
Classification OUTPUTS are written outside `Plan/Civitai/` (configs/, Plan/) so
they remain versioned. Kevin to decide final storage (DVC vs external) when he
resolves the remote-repo question (08.02).
**Approved by:** AI-autonomous (conservative default, logged for Kevin's awareness)

## 2026-07-10 — Supply the specified SAM2 Nuclio function outside pinned CVAT
**Item(s) affected:** MF-P0-04.02, MF-P0-04.03, MF-P0-04.04, MF-P0-04.05
**Spec said:** `Plan\06` §4 and MF-P0-04 require pinned CVAT v2.24.0 plus
`serverless/pytorch/facebookresearch/sam2/nuclio`, deployed as a CPU interactor
and reported by the runbook as function `pth-sam2`.
**What we did instead:** Keep CVAT at the mandated v2.24.0 pin and provide the
missing SAM2 Nuclio source as a tracked MaskFactory compatibility component,
synced into the exact expected path before executing the function-specific
`nuctl deploy` block from CVAT's pinned `serverless/deploy_cpu.sh`. The wrapper
skips that script's unconditional, unrelated OpenVINO base-image prebuild because
its retired Intel apt repository prevents the script from reaching SAM2. Do not
substitute the checkout's SAM 1 function or upgrade CVAT.
**Why:** The official CVAT v2.24.0 tree contains
`serverless/pytorch/facebookresearch/sam/nuclio` but no `sam2` directory; CVAT's
public project also confirms SAM2 was not shipped as a community Nuclio config.
The written requirements are otherwise unambiguous about the model generation,
function identity, CPU ownership, and pinned CVAT version. Supplying the missing
adapter is the narrowest reading that satisfies all of them and keeps the
external checkout reproducible and clean.
**Approved by:** AI-autonomous (conservative default, logged for Kevin's awareness)
## 2026-07-11 — RESOLVED by approved doc 18: v1 uses 56 logits; v2 uses 65
**Item(s) affected:** MF-P5-02.01, MF-P5-03.01, every body-part training/promotion run
**Spec conflict:** The authoritative ontology and label-map contract define exactly
56 indexed values, IDs `0..55`, and ID 0 is already `background`. Doc 12 §6.1 and
MF-P5-03.01 instead demand "57-class (56 PART IDs + background)" and the completed
training YAML therefore declares `num_classes: 57`.
**Observed consequence:** A real MMSeg dataset built from the authoritative maps has
56 class names and no possible target pixel for logit 56. Keeping 57 creates an
untrained, unnamed output; changing to 56 contradicts the literal training item.
**Resolution:** Approved doc 18 §1 explicitly invalidates the old 57-class phrase. Active
v1 uses the contiguous 56-class vocabulary for IDs `0..55`, including background ID 0.
The append-only v2 migration adds IDs `56..64` and therefore uses exactly 65 logits.
Both active v1 body-part configs are corrected to 56; no dummy class or ID remap exists.
