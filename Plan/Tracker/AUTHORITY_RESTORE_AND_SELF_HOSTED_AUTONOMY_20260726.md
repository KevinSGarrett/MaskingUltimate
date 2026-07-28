# Authority restoration and self-hosted autonomy tracker receipt

- Restored at: 2026-07-26 UTC
- Active branch at backup: `codex/maskfactory-runtime-implementation`
- Active HEAD at backup: `1240fbf0d6ac89cae6c588ab84fb354c75197ee7`
- Source authority commit: `966b95a3c36fb0ed9d6c236c97d97cc4fd6a352d`
- Missing authority files restored: 84
- Source/local Git-blob mismatches immediately after restore: 0
- Locally present instruction files preserved without overwrite: 4
- Tracker baseline: 866 items, structurally valid
- Tracker after Plan-27 rebuild: 894 items, 28 new, 866 preserved, 0 orphaned
- Tracker validation after rebuild: no structural problems
- Current autonomy state: `SELF_HOSTED_AUTONOMOUS_LLM_THROUGHPUT_INCOMPLETE`

The complete path list and per-path verification result are recorded in:

`.codex-ops/backups/self_hosted_llm_authority_restore_20260726T053052Z/authority_restore_receipt.json`

Receipt SHA-256:

`fd6b179b98a30fcb1c986a5dce34e3d6b1b9f709e86b0ea7c1cdfdec1166abbc`

The verified rollback manifest is:

`.codex-ops/backups/self_hosted_llm_authority_restore_20260726T053052Z/SHA256SUMS.txt`

Manifest SHA-256:

`7117bc98ba9c37e81a4980b5ba3b9a7117dbe0caa9829757ed8895ddbc4a8952`

The final manifest contains 173 entries, including the preserved prior
`.codex-ops/CURRENT_TASK.md`, the source archive, and the
extracted source pack, and verifies with zero integrity errors.

The exact authority source archive SHA-256 is:

`9be1b7be1415cf308bd2aee95716b6aa0fdce73888dbfabb48f06780f8570465`

New authority hashes at initial tracker rebuild:

| Authority | SHA-256 |
|---|---|
| `Plan/27_SELF_HOSTED_AUTONOMOUS_LLM_CONTINUOUS_OPERATIONS_SPEC.md` | `5814f70fff5f0fe507ad1ab3f3cbaf350ef24cf7ab4887e80eebe723dde2d4e3` |
| `Plan/Items/23_ITEMS_P6_SELF_HOSTED_AUTONOMOUS_LLM_OPERATIONS.md` | `c9d78c364a973e7e694cec3bb1f45cb1eb4d7548d91428e423642ec8d48a87c6` |
| `Plan/Instructions/16_SELF_HOSTED_AUTONOMOUS_LLM_CONTINUOUS_OPERATIONS.md` | `57ca082243719040ba54413318c9bbbea7076c5fdf22f51ef08971e8e128a88a` |
| `Plan/SELF_HOSTED_AUTONOMOUS_LLM_PURSUING_GOAL_MESSAGE.md` | `47d6c29943ef96c15d6e6b334b819248634c52bf3c7e55f1a7c7bffac513159d` |

This receipt proves authority restoration and Plan-27 registration only. It
does not claim that the CPU supervisor, campaign router, autonomous mask work
cell, micro-handoff reduction, or sustained throughput acceptance is complete.
