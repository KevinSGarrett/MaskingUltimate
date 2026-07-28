# MaskFactory — Agent instructions

**MUST read:** [`Plan/STANDING_ORDERS_AUTONOMOUS_BUILD.md`](Plan/STANDING_ORDERS_AUTONOMOUS_BUILD.md)

Binding standing orders for this repo’s continuous autonomous MaskFactory build. Full mandate lives only in that Plan file; keep this pointer short. **NO STOP** until E2E complete — see Standing Orders § CONTINUOUS UNTIL E2E COMPLETE (NO STOP).

Authorities: `Plan/Tracker/tracker.py` (live status), `Plan/` specs +
`maskfactory-full-completion_69d863cb.plan.md`, `Plan/DOCKER_RUNTIME_AND_SESSION_USE.md`. **NEVER EC2.**

Every RunPod local-GPU command must be launched through
`tools/run_with_shared_pod_gpu_lease.py`. The authoritative FIFO database is
`/workspace/.maskfactory/shared_pod_coordination/shared_gpu_leases_v1.sqlite`;
the MaskFactory owner token is
`/tmp/maskfactory-019f91d1-ea20-7d81-83ff-03d393eaa1f5-shared-gpu-owner.token`
and must remain mode `0600`. No lease means no local GPU launch: use the shared
brokered Serverless route, OpenRouter for an eligible bounded task, or another
CPU-safe lane. Never kill or preempt another session's process.
