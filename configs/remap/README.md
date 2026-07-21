# External Dataset Remap Plans

These files are intake plans, not permission to write source annotations into
MaskFactory gold packages. Every conversion must preserve source provenance,
apply the deterministic mapping declared here, write outside `data/packages`,
and pass visual QA before fixture or training admission.

Actions have strict meanings:

- `direct`: source pixels can enter the named target layer after format conversion.
- `merge`: a finer source component merges into a coarser MaskFactory label.
- `split_required`: the source class is too coarse; pose/geometry/fusion must split it.
- `ambiguous_do_not_use`: no target pixels may be emitted until the stated blocker is resolved.

All five sources remain non-gold and training-disabled pending their recorded
license/provenance gates.
