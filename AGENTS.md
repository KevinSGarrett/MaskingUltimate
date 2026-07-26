# MaskFactory - Agent instructions

**MUST read:** [`Plan/STANDING_ORDERS_AUTONOMOUS_BUILD.md`](Plan/STANDING_ORDERS_AUTONOMOUS_BUILD.md)

Binding standing orders for this repo's continuous autonomous MaskFactory build.
Full mandate lives only in that Plan file; keep this pointer short. **NO STOP**
until E2E complete - see Standing Orders CONTINUOUS UNTIL E2E COMPLETE (NO STOP).

Authorities: `Plan/Tracker/tracker.py` (live status), `Plan/` specs +
`maskfactory-full-completion_69d863cb.plan.md`,
`Plan/DOCKER_RUNTIME_AND_SESSION_USE.md`. **NEVER EC2.**

RunPod execution is selected directly for the intended pod. No Windows-local
shared scheduler, lease token, capacity reservation, or cross-pod admission
check is required. MaskFactory internal locks remain local critical-section
evidence only and are not a veto on another pod.
