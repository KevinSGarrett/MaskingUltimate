"""Analyze MVC vs corpus-envelope eligibility for CAA admission path."""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from maskfactory.autonomy.corpus import scan_lifecycle_pool  # noqa: E402

ROOT = REPO / "runs"
TARGET_FP = "multiprovider-local-cuda-tournament-20260720-v1"


def main() -> int:
    pool = scan_lifecycle_pool(ROOT)
    envs = list(ROOT.rglob("*.corpus_record.json"))
    labels: Counter[str] = Counter()
    contexts: Counter[str] = Counter()
    fps: Counter[str] = Counter()
    fams: Counter[int | str] = Counter()
    accepted: Counter[str] = Counter()
    target_torso_solo = 0
    for path in envs:
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        labels[str(doc.get("label"))] += 1
        contexts[str(doc.get("context"))] += 1
        fps[str(doc.get("pipeline_fingerprint"))] += 1
        fams[doc.get("independent_family_count", "?")] += 1
        accepted[str(doc.get("machine_accepted"))] += 1
        if (
            doc.get("label") == "torso"
            and doc.get("context") == "solo"
            and doc.get("pipeline_fingerprint") == TARGET_FP
            and doc.get("machine_accepted") is True
            and int(doc.get("independent_family_count") or 0) >= 3
        ):
            target_torso_solo += 1

    lifecycles = list(ROOT.rglob("autonomy/*.json"))
    life_status: Counter[str] = Counter()
    life_fp: Counter[str] = Counter()
    life_label: Counter[str] = Counter()
    mvc_with_envelope = 0
    mvc_without_envelope = 0
    for path in lifecycles:
        if path.name.endswith(".corpus_record.json"):
            continue
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        status = str(doc.get("status"))
        life_status[status] += 1
        life_fp[str(doc.get("pipeline_fingerprint"))] += 1
        life_label[str(doc.get("label"))] += 1
        if status == "machine_verified_candidate":
            env = path.with_name(path.stem + ".corpus_record.json")
            if env.is_file():
                mvc_with_envelope += 1
            else:
                mvc_without_envelope += 1

    report = {
        "pool": pool,
        "envelope_count": len(envs),
        "envelope_labels": labels.most_common(30),
        "envelope_contexts": contexts.most_common(10),
        "envelope_family_counts": dict(fams),
        "envelope_accepted": dict(accepted),
        "envelope_fps_top": fps.most_common(15),
        "target_torso_solo_ge3_family_envelopes": target_torso_solo,
        "lifecycle_status": dict(life_status),
        "lifecycle_fps_top": life_fp.most_common(15),
        "lifecycle_labels_top": life_label.most_common(20),
        "mvc_with_envelope": mvc_with_envelope,
        "mvc_without_envelope": mvc_without_envelope,
        "target_pipeline_fingerprint": TARGET_FP,
    }
    out = REPO / "qa/live_verification/mvc_envelope_caa_analysis_20260720T171638Z.json"
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
