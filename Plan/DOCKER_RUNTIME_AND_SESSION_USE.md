# Local Docker/WSL Runtime Retirement And Reference Policy (MaskFactory)

This file supersedes the former automatic local Docker session runbook.
Historical Docker, CVAT, Nuclio, SAM2, Ollama, WSL, and GPU evidence remains in
`Plan/OPS_LOG.md`, `Plan/06_ENVIRONMENT_AND_INSTALLATION.md`, tracker evidence,
and `qa/live_verification/`; history must not be rewritten.

## 1. Hard execution boundary

RunPod is the production location for MaskFactory masking, provider inference,
strict visual review, repair, training, benchmarking, qualification, corpus
processing, champion promotion, and runtime verification. Production data,
models, panels, intermediate results, and released-package staging reside on
persistent RunPod storage. The selected pod executes directly; GPU/VRAM
coordinators, admission checks, reservations, checkouts, schedulers, sequencers,
capacity leases, and file-lock gates have no authority.

The laptop is limited to CPU-only source editing, unit/schema/contract tests,
tracker and queue bookkeeping, deterministic hash/package verification, and
explicitly requested read-only integration inspection.

Agents MUST NOT automatically:

- run `docker`, `docker compose`, `wsl`, local GPU, CVAT, Nuclio, SAM2, or
  local Ollama probes during bootstrap, doctor, next-action selection, or
  production work;
- start, restart, repair, update, install, pull, build, or migrate Docker
  Desktop, WSL distributions, containers, images, volumes, Ollama models, or
  local GPU runtimes;
- use local Docker, WSL, SAM2, Ollama, CVAT, Nuclio, or the laptop GPU as a
  substitute when RunPod is unavailable;
- write new MaskFactory models, corpora, archives, panels, or batch outputs to
  Docker volumes, WSL virtual disks, `.ollama`, `%TEMP%`, `.codex/visualizations`,
  or `C:\w`.

A state-changing local runtime operation is authorized only when Kevin asks for
that exact local operation in the current turn. An old tracker verify clause,
OPS-log note, historical doctor result, prior chat authorization, or the fact
that Docker/Ollama is already running is not authorization.

## 2. RunPod unavailable

RunPod service or workload failure blocks only the affected runtime item.
Continue CPU-only implementation, schemas, tests, tracker reconciliation,
package verification, and other independent work. Record the exact remote
blocker. Never fall back to local inference and never present local service
health as production progress.

## 3. Legacy local components

- Local CVAT is optional human review/integration tooling only.
- Local Nuclio and `pth-sam2` are optional CVAT assistance and legacy
  compatibility only.
- SAM2/SAM2.1 evidence may remain for comparison, benchmarks, or rollback; it
  is not current production mask authority.
- Local Ollama is legacy diagnostic tooling and has no strict-visual-review or
  certification authority.
- Local Docker/WSL images, volumes, VHDX files, and Ollama blobs are retirement
  candidates. Do not add new MaskFactory content to them.

Do not delete or relocate legacy state until unique CVAT projects, evidence,
configuration, and required assets have been inventoried, hash-verified against
their persistent RunPod/local governed copies, and Kevin has explicitly
authorized the cleanup. Never run destructive Docker or WSL cleanup implicitly.

## 4. Local storage guard

Before any explicitly authorized local write, check free space. Do not create or
download a single artifact larger than 256 MiB, or more than 1 GiB cumulative
temporary/runtime output, without all of:

1. a selected tracker item requiring the local artifact;
2. an explicit governed retention destination;
3. enough free space for the write plus rollback headroom; and
4. a cleanup/retention decision recorded before execution.

Remote archives, models, masks, panels, and batch outputs go directly to
persistent RunPod storage. Transport archives may be removed only after exact
destination path/size/SHA-256 verification and under a separately authorized
cleanup action.

## 5. Evidence and claim limits

- Local Docker/CVAT/Nuclio/SAM2/Ollama health proves only the exact optional
  integration named by Kevin's current-turn request.
- It never proves RunPod runtime health, provider qualification, strict visual
  authority, production masking progress, autonomous gold, or release readiness.
- Doctor and next-action selectors must not treat local service absence as a
  core blocker or local service presence as progress.
- Preserve historical evidence as historical; mark stale local-runtime
  requirements superseded instead of deleting their audit trail.

## 6. Manual recovery boundary

There is intentionally no automatic start/repair command sequence in this
policy. If Kevin requests a named local recovery or cleanup operation, first
perform a read-only inventory, state the exact retained data and risk, and use
the smallest reversible operation. This exception never changes the RunPod-only
production boundary.
