"""Append-only OPS_LOG: data/ on-C confirmed; USB data junction FORBIDDEN."""

ENTRY = """
## 2026-07-20 15:00 UTC - data/ junction on-C confirmed; USB data junction FORBIDDEN
**Item:** data_junction_on_c_confirmed / needs_agent_actions usb_data_junction_policy
**Command:** `fsutil reparsepoint query data`; `python runtime_artifacts/_seal_data_junction_on_c_confirmed_20260720.py`; `python runtime_artifacts/_update_needs_agent_actions_forbid_usb_data_junction_20260720.py`
**Result:** CONFIRMED. Live probe: `data/` Print Name / realpath = `C:\\Comfy_UI_Main_Masking\\data_c_backup_relocated` (not F:). Packages via junction: 8, readable. Mutation: none.

`needs_agent_actions_20260720.json` now carries binding `usb_data_junction_policy.status=FORBIDDEN` plus action_id=`forbid_usb_data_junction` (BINDING_POLICY_FORBIDDEN). Stale dual-anchor language implying live `data/` still targets F: corrected. Agents must not re-junction `data/` onto USB F:; F: remains cold offload / read-when-present only.

Honest non-claims: no docker_vhdx_relocated_to_f, no doctor-green, no gold/champions>0.

Evidence: qa/live_verification/data_junction_on_c_confirmed_20260720T1500Z.json (self_sha256 3e7cf00c64a8369b...); queue self_sha256 926486d807c0d010....
"""

with open("Plan/OPS_LOG.md", "a", encoding="utf-8", newline="\n") as f:
    f.write(ENTRY)
print("APPENDED", len(ENTRY), "chars")
