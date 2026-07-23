# MaskFactory - Agent instructions

**MUST read:** [`Plan/STANDING_ORDERS_AUTONOMOUS_BUILD.md`](Plan/STANDING_ORDERS_AUTONOMOUS_BUILD.md)

Binding standing orders for this repository's continuous autonomous MaskFactory
build live in that Plan file. Continue until genuine end-to-end completion; do
not substitute planning, tracker, or static-test evidence for runtime proof.

Authorities: `Plan/Tracker/tracker.py`, the specifications and accepted
amendments under `Plan/`, `maskfactory-full-completion_69d863cb.plan.md`, and
`Plan/DOCKER_RUNTIME_AND_SESSION_USE.md`. AWS is read-only inventory only;
**never run MaskFactory workloads on EC2 and never mutate AWS**.

RunPod execution targets the intended pod directly. GPU/VRAM admission,
reservation, checkout, capacity-lease, scheduler, and file-lock governance are
disabled. Durable mission/shard/record ownership leases remain required because
they protect queue integrity rather than GPU resources.
