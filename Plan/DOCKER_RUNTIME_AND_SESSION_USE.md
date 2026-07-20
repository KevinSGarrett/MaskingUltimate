# Docker Runtime And Session Use (MaskFactory)

**Binding for session `5d7ae789-d56a-433c-a5ab-ab04682a5a9b` and every parallel agent under it.**

Docker is a first-class local runtime for MaskFactory. Agents must not treat it as optional trivia, assume it is down from stale probes, or invent cloud/EC2 substitutes. Re-probe live before every Docker-dependent claim. Use Docker wherever the item, doctor check, smoke, CVAT bridge, Nuclio interactor, Ollama VLM, GPU container proof, or migration rehearsal requires it.

This file is the session operating manual. Supporting install history lives in `Plan/06_ENVIRONMENT_AND_INSTALLATION.md`, `Plan/OPS_LOG.md`, and tracker P0 evidence. Do not replace those; use this for day-to-day execution.

---

## 1. What Docker is in this project

| Piece | Role |
|-------|------|
| **Docker Desktop (Windows)** | Host engine. Linux containers via the `docker-desktop` WSL2 distro. CLI context is typically `docker-desktop`. |
| **Docker Engine / CLI** | `docker` / `docker compose` from PowerShell or WSL. Client/server were verified at **29.4.3**. |
| **Pinned CVAT v2.24.0** | Production annotation/API stack for MaskFactory bridge, project init, push/pull, residual/audit routes. UI/API: `http://localhost:8080` (loopback-bound). |
| **Nuclio + `pth-sam2`** | Serverless SAM2 interactor for CVAT click-refine / assistance. Dashboard: `127.0.0.1:8070`. |
| **Parallel CVAT v2.69 (`cvat269`)** | Isolated migration rehearsal only. Must not replace or break v2.24. Host UI typically `127.0.0.1:18080` with `CVAT_HOST=cvat269.localhost`. |
| **Ollama (Docker or loopback)** | Local VLM/LLM for visual QA (`http://127.0.0.1:11434`). Spec install is Docker GPU container; if a healthy loopback Ollama already answers, use it and record which process/container provided it. |
| **GPU passthrough** | `docker run --gpus all …` for CUDA container proofs and GPU-backed Ollama/Nuclio when configured. |

**Not Docker:** native Windows/WSL Python `maskfactory` pipeline code, pytest, tracker, bridge contract tests. Those run on the host/WSL Python env and *call* Docker services when needed.

---

## 2. Live baseline (re-verify; do not memorize forever)

As of 2026-07-19 local probe after Kevin started Docker Desktop:

- Docker Desktop **up**: server `29.4.3`, OS `Docker Desktop`, context `docker-desktop`.
- Production CVAT stack **up** (`cvat_server`, `traefik`, `nuclio`, workers, db/redis/…); `GET http://localhost:8080/api/server/about` → **version 2.24.0**.
- Parallel `cvat269_*` stack also present (migration rehearsal); keep it isolated.
- `nuclio-nuclio-pth-sam2` healthy.
- Ollama API answering at `127.0.0.1:11434` (record container vs native on each probe).
- WSL: `docker-desktop` **Running**; `Ubuntu-22.04` may be **Stopped**. Docker Desktop services work without Ubuntu running; **GPU/WSL pipeline/SAM paths that need Ubuntu still require starting that distro**.

If any later probe disagrees, trust the live probe and update `OPS_LOG` — never the stale snapshot above alone.

---

## 3. Mandatory preflight (every Docker-touching wave)

Run from `C:\Comfy_UI_Main_Masking` (PowerShell):

```powershell
docker info --format "Server={{.ServerVersion}}; Context={{.Name}}; OS={{.OperatingSystem}}"
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
wsl -l -v
curl.exe -s http://localhost:8080/api/server/about
curl.exe -s http://127.0.0.1:11434/api/version
python -m maskfactory doctor
```

Interpretation:

| Result | Action |
|--------|--------|
| `docker info` fails / daemon unreachable | Start Docker Desktop; wait until engine healthy; re-probe. Do not mark Docker-backed items complete. Continue host-only lanes. |
| Engine up, CVAT about ≠ 2.24.0 or unreachable | Bring up pinned stack via bootstrap (below). Do not point production bridge at `cvat269`. |
| Engine up, Nuclio/SAM2 fail doctor | Repair/redeploy interactor; run `tools/smoke_cvat_sam2.py`; keep typed FAIL evidence until green. |
| Ollama down | Start/restore Ollama (Docker recipe in §5 or native if already installed); run `tools/smoke_ollama_vlm.py` before visual-critic completion claims. |
| `Ubuntu-22.04` Stopped | OK for CVAT/API Docker work. Start WSL Ubuntu only when the item needs WSL GPU/pipeline round-trip. |

Never claim “all-green doctor” from a previous session’s log.

---

## 4. How to start / operate the pinned CVAT stack

Canonical bootstrap (Docker 29 + Traefik 3.6.1 shims already in-repo):

```powershell
cd C:\Comfy_UI_Main_Masking
$env:CVAT_HOST = "localhost"
$env:MASKFACTORY_DATA_PATH = "C:\Comfy_UI_Main_Masking\data"
python tools/bootstrap_cvat.py
```

Equivalent compose (what bootstrap runs):

```text
docker compose
  -f cvat/docker-compose.yml
  -f cvat/components/serverless/docker-compose.serverless.yml
  -f configs/cvat-compose.maskfactory.yml
  up -d
```

Key override file: `configs/cvat-compose.maskfactory.yml`

- Loopback binds: `127.0.0.1:8080`, `8090`, Nuclio `8070`
- Shared data mount: `MASKFACTORY_DATA_PATH` → `/home/django/share` (read-only)
- Traefik 3.6.1 for Docker API negotiation

Credentials: root `.env` (gitignored) holds `CVAT_USERNAME`, `CVAT_PASSWORD`, `CVAT_EMAIL`, `CVAT_TOKEN`. Load for authenticated API calls; never print secrets into tracker/OPS_LOG/commits.

Useful tools:

- `tools/bootstrap_cvat_credentials.py` — idempotent admin/token bootstrap
- `tools/smoke_cvat_sam2.py` — Nuclio/SAM2 through CVAT
- `maskfactory cvat …` / bridge push-pull — use `localhost:8080` production stack
- `tools/verify_cvat_parallel_assistance.py` + `configs/cvat-compose.parallel-v269.yml` — parallel v2.69 only

---

## 5. Ollama (visual / VLM QA)

Spec Docker install (when container missing):

```powershell
docker run -d --name ollama --gpus all -v ollama:/root/.ollama -p 127.0.0.1:11434:11434 ollama/ollama
docker exec ollama ollama pull qwen2.5vl:7b
docker exec ollama ollama pull llama3.2-vision:11b
docker exec ollama ollama pull qwen2.5:7b-instruct
```

Smoke: `python tools/smoke_ollama_vlm.py` → `qa/reports/ollama_vlm_smoke.json`

Rules:

- Endpoint must be `http://127.0.0.1:11434` (cloud URLs rejected).
- VLM is advisory diagnosis only; never clears hard QA BLOCK or invents gold.
- If Ollama is down, mark visual-critic lane blocked with typed evidence and continue hard-QA / non-VLM paths.

---

## 6. GPU container proof

When an item or doctor path needs container GPU:

```powershell
docker run --rm --gpus all nvidia/cuda:12.8.0-base-ubuntu22.04 nvidia-smi
```

Expect driver-visible RTX 5060 Laptop GPU. Failure is typed infrastructure evidence, not a silent skip.

---

## 6b. Governed serve/train GPU images (`docker/compose.gpu.yml`)

These images run the CUDA `maskfactory serve` and `training-doctor` runtimes as host-NVIDIA containers, bypassing the corrupt WSL Ubuntu-22.04 ext4 VHD.

| Image | Dockerfile | Purpose |
|-------|-----------|---------|
| `maskfactory/serve:cu128` | `docker/Dockerfile.serve` | Mode-B `serve` `/health`,`/models` (torch cu128, no nvcc). |
| `maskfactory/train:cu128` | `docker/Dockerfile.train` | `training-doctor`; builds `mmcv._ext` from source for sm_120 (CUDA 12.8 **devel** base, nvcc present) per `env/openmmlab_training_stack.lock.json`. |

**Build-safety (READ FIRST):** the train image is a heavy from-source `nvcc` compile and the serve image pulls ~7 GiB of torch+CUDA wheels. A large install has crashed the Docker daemon on the constrained WSL2 backend before. **Do not** kick off these builds when disk is tight (<~30 GiB free) or a sibling build/reclaim is in flight. Build deliberately, out of band, with WSL2 memory/disk headroom:

```powershell
docker compose -f docker/compose.gpu.yml build maskfactory-train   # heavy sm_120 mmcv build
docker compose -f docker/compose.gpu.yml run --rm maskfactory-train # training-doctor
```

**STATIC contract (no build, no engine, always safe):** verify that `Dockerfile.train` + the `maskfactory-train` compose service stay coherent with the runtime lock (torch pin, mmcv locked commit + `mmcv._ext` build, sm_120 arch list, OpenMMLab pins, `shm_size`, `pull_policy: never`, loopback):

```powershell
python -m maskfactory verify-docker-train-contract --output qa/live_verification/docker_train_contract_static_<ts>.json
python tools/verify_docker_train_contract.py            # convenience wrapper
```

**LIVE train smoke (never builds):** `tools/smoke_docker_gpu_train.py` runs `training-doctor` inside the prebuilt image and **fails closed with `image_absent`** if `maskfactory/train:cu128` does not exist — it will never trigger the heavy build for you. `training-doctor` green in-container (`mmcv._ext` sm_120 + registered datasets/transforms/metric) is a live claim only that smoke may establish; the STATIC contract never asserts it.

---

## 7. When the session MUST use Docker

Use Docker (probe → start/repair → smoke → evidence) for any of:

1. CVAT API/UI/project/init, push/pull, residual publication, migration/rollback.
2. Nuclio / `pth-sam2` interactor smokes and assistance verification.
3. Ollama VLM panel criticism when the runtime is Docker- or loopback-Ollama-backed.
4. Container GPU verification items.
5. Parallel CVAT v2.69 migration rehearsal (isolated project `cvat269` only).
6. Any `maskfactory doctor` check that depends on the above services.
7. Any tracker verify clause that names live CVAT, Nuclio, Ollama, or Docker.

Do **not** wait for Kevin to start containers if Docker Desktop is already running — agents start/repair stacks themselves via the tools above. Kevin is only needed for Desktop install/login, privileged host recovery, or credential/terms he alone can accept.

---

## 8. Safety and honesty rules

- **Loopback only** for published CVAT/Ollama ports; do not expose annotation stacks to the LAN.
- **Never** treat fixture/`FakeCvat` / `producer_partial` as production CVAT complete.
- **Never** collapse autonomous gold with CVAT human correction; CVAT is optional residual/audit, not certification authority for autonomous-gold core.
- **Never** destroy volumes, `docker system prune -a`, or wipe CVAT data without an explicit Kevin-authorized maintenance item and rollback evidence.
- **Never** point production bridge clients at `cvat269` ports/hostnames.
- Prefer additive compose overrides already in `configs/`; do not edit upstream `cvat/` pins casually.
- Record every live Docker probe that changes completion claims in `Plan/OPS_LOG.md` with commands and non-secret results.
- If Docker is down mid-wave: continue all host-only pytest/schema/bridge-contract work; leave Docker-dependent items `blocked`/`partially_complete` with typed reason.

---

## 8b. Removable F: USB — never host live `data/` or Docker VHDX

**Binding host fact:** `F:` is a USB external drive (Seagate BUP Slim; `Get-Disk` BusType=`USB`). `Get-Volume`/`DriveType=Fixed` is misleading for this enclosure — BusType wins. The drive disconnects; siblings have observed it physically absent mid-session.

| Asset | Allowed on F:? | Rule |
|-------|----------------|------|
| Live Docker `docker_data.vhdx` | **No** | Engine store stays on C:; relocating onto USB reproduces daemon crash-loops. |
| Repo `data/` junction (sole live target) | **No** | Keep on fixed local (current durable target: `data_c_backup_relocated` on C:). Unplug leaves `MASKFACTORY_DATA_PATH` / CVAT share dangling. |
| Cold offload / read-when-present corpora (DAZ, archival mirrors, non-engine WSL VHDs) | **Yes, when present** | Graceful typed FAIL/SKIP if F: absent — never silent crash, never force-retarget live runtime onto F:. |

**Doctor guard:** `maskfactory doctor` runs `check_data_junction_not_removable_usb` — **FAIL** if `data/` resolves onto policy drive `F:` or `GetDriveTypeW=DRIVE_REMOVABLE`. **PASS** when the junction/directory resolves to a fixed local volume.

**Move guard:** `tools/move_data_to_junction.ps1` refuses targets on policy letter `F:` or `BusType=USB` (rehearsal and apply).

Evidence / policy seals: `qa/live_verification/f_drive_usb_policy_20260720.json`, `docker_migrate_abort_usb_removable_f_20260720T1437Z.json`, `data_junction_abort_f_keep_c_20260720T1438Z.json`.

---

## 9. Quick command cheat sheet

| Goal | Command |
|------|---------|
| Engine health | `docker info` |
| What’s running | `docker ps` |
| Start CVAT+Nuclio | `python tools/bootstrap_cvat.py` |
| CVAT about | `curl.exe -s http://localhost:8080/api/server/about` |
| Nuclio dashboard | browse/curl `http://127.0.0.1:8070` |
| SAM2 smoke | `python tools/smoke_cvat_sam2.py` |
| Ollama version | `curl.exe -s http://127.0.0.1:11434/api/version` |
| VLM smoke | `python tools/smoke_ollama_vlm.py` |
| Full runtime gate | `python -m maskfactory doctor` |
| data/ not on USB F: | doctor check `data_junction_not_removable_usb` (see §8b) |
| WSL distros | `wsl -l -v` |
| Start Ubuntu WSL | `wsl -d Ubuntu-22.04` (only when needed) |
| GPU in container | `docker run --rm --gpus all nvidia/cuda:12.8.0-base-ubuntu22.04 nvidia-smi` |
| Train image STATIC contract (safe) | `python -m maskfactory verify-docker-train-contract` |
| Train image LIVE smoke (never builds) | `python tools/smoke_docker_gpu_train.py --output qa/live_verification/smoke_docker_gpu_train_<ts>.json` |

---

## 10. Session obligation

On every restart or before any runtime-dependent milestone, the active MaskFactory session must:

1. Re-read this file and the Docker section of the active completion plan.
2. Run the §3 preflight (or prove services still healthy from a probe seconds earlier in the same wave).
3. Use Docker freely for all in-scope start/smoke/repair/evidence work without pausing for permission.
4. Keep tracker status honest when a Docker dependency is the real blocker.
