# ADR: Shared RunPod Serverless overflow for ComfyUI and MaskFactory

- Status: accepted for live smoke validation
- Date: 2026-07-24
- Decision owner: Codex, retaining RunPod and final acceptance authority

## Context

The US-WA-1 pod and `hyperreal-maskfactory-nv` network volume are shared by the
ComfyUI session `019f9200-4805-7632-83d3-ee9ae614c603` and Ultimate Masking
System session `019f91d1-ea20-7d81-83ff-03d393eaa1f5`. Either session needs a
GPU-safe overflow lane when the pod GPU is occupied. The user authorized at most
$15.60 per day and $0.65 per rolling hour of additional Serverless spend.

RunPod mounts this network volume at `/workspace` on Pods and
`/runpod-volume` on Serverless workers. Attaching it constrains Serverless
placement to US-WA-1. The selected 48 GB Pro Serverless tier costs more than
$0.54 for a continuously active hour, so the hourly authority is enforced as a
rolling spend window rather than an instantaneous GPU price ceiling.

## Decision

Use one durable broker and two workload-specific, scale-to-zero endpoints:

1. `comfyui` uses the official RunPod ComfyUI worker as a pinned base, with the
   live pod's custom-node revisions baked in and model paths pointed to
   `/runpod-volume/ComfyUI/models`.
2. `maskfactory` uses a pinned PyTorch worker with a no-shell, hash-bound command
   handler. It exposes the volume as `/workspace` inside the worker so existing
   RunPod manifests remain path-compatible.
3. Both endpoints attach only network volume `o9qv2ld91c` in US-WA-1, set
   `workersMin=0`, `workersMax=1`, one GPU per worker, a five-second idle timeout,
   and a 634-second execution timeout. GPU priority is RTX 6000 Ada followed by
   RTX PRO 6000 Blackwell Server Edition (shown as PRO 6000 MIG 48GB in the
   console). No 24 GB worker is admitted. The timeout is the largest
   conservative value that fits the
   rolling-hour admission band at the highest allowed GPU rate after cold-start
   and idle reserves.
4. A SQLite WAL ledger lives at
   `/workspace/.maskfactory/serverless_overflow/overflow.sqlite`. It permits one
   global in-flight overflow job across both endpoints and binds each session ID
   to exactly one profile.
5. Two independent budget windows apply. The UTC-day hard authority is $15.60
   and daily submissions stop at $14.10, retaining $1.50 for provider variance.
   The rolling 60-minute hard authority is $0.65 and hourly submissions stop at
   $0.60, retaining $0.05 for provider variance. Every request must fit both
   windows and reserves its requested runtime plus 300 cold-start seconds and
   five idle seconds at the configured maximum rate. Because the stock ComfyUI
   handler does not enforce a broker-supplied per-job timeout, every ComfyUI
   admission reserves the endpoint's full 634-second execution timeout.
6. Local GPU probing is read-only. Any compute process or queued ComfyUI work
   makes the local lane busy. The broker never kills, pauses, reprioritizes, or
   claims ownership of a process.
7. A CPU-only watchdog on the existing Pod reconciles submitted jobs every 15
   seconds. If a job remains `IN_QUEUE` for 300 seconds, the broker cancels it
   and releases the shared slot and local reservation. RunPod's provider TTL is
   the queue window plus the admitted execution window because its TTL also
   applies to running work.
8. Once a worker accepts a Serverless job, the job finishes there even if the
   pod GPU becomes free. This prevents duplicate writes and duplicate billing.

## Consequences and limitations

- The $15.60 cap is enforced for jobs admitted through the broker. RunPod does not
  provide a native per-account or per-endpoint daily dollar cap, so direct API/UI
  submissions can bypass it and are prohibited operationally.
- A single universal image was rejected because ComfyUI and MaskFactory have
  incompatible dependency and startup contracts. Two endpoints reduce cold-start
  size and dependency conflicts while the shared broker preserves one budget.
- Concurrent writes to identical volume paths remain forbidden. Outputs must be
  namespaced by session, campaign, and job.
- The ComfyUI endpoint completed provider job
  `8e4e57a2-d153-4a3a-80dd-fa907f714a20-u2`, returning the expected smoke PNG.
  MaskFactory provider job `46e12666-f333-41c4-9f8b-1648862171f9-u2`
  remained queued for 300 seconds and was automatically cancelled with no
  execution charge, proving the bounded queue-release path. Its hash-bound
  command worker remains subject to an independent completed-runtime smoke.

## Rollback

Set both endpoints to zero workers (already the minimum), stop broker submissions,
delete the two endpoints/templates, and remove only the broker deployment root.
The existing pod and network volume are not detached, migrated, reformatted, or
deleted. Source rollback is the isolated Git branch plus checkpoint
`C:\Users\kevin\.codex\backups\runpod-hybrid-overflow-20260724T160900Z`.
