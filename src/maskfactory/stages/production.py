"""Production file-contract runners for the implemented early pipeline stages."""

from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import yaml
from PIL import Image

from ..cvat_bridge.client import CvatClient
from ..cvat_bridge.push import push_images
from ..datasets.active_learning import run_active_learning
from ..datasets.builder import approved_package_count, build_dataset, next_dataset_version
from ..fs_atomic import replace_with_retry
from ..io.png_strict import read_mask, write_binary_mask, write_label_map
from ..lanes.hand import (
    apply_and_record_s07_hand_merges,
    apply_champion_hand_drafts,
    champion_hand_refresh_required,
)
from ..ontology import get_ontology
from ..orchestrator import (
    SemanticStageError,
    StageContext,
    StageExecution,
    StageRunner,
    append_review_route_once,
    run_pipeline,
)
from ..packager import verify_packages
from ..qa.multi_instance import MultiInstanceQcInputs
from ..qa.production import run_s10_production
from ..review_package import assemble_review_package
from ..review_resolution import (
    ReviewResolutionError,
    apply_s02_review_resolution,
    s02_review_refresh_required,
)
from ..state import persist_terminal_image_outcome
from ..vlm.production import run_s11_production
from .s01_person_detection import run_s01
from .s02_silhouette import run_s02
from .s03_parsing import (
    custom_bodypart_refresh_required,
    run_champion_bodypart_prediction,
    run_s03_production,
    suppress_co_subject_parsing,
)
from .s04_pose import run_s04_production
from .s05_geometry import run_s05_production
from .s06_openvocab import run_s06_production
from .s07_sam2 import WslSam2Provider, run_s07_production
from .s08_5_densepose import WslDensePoseProvider, run_densepose
from .s08_material import champion_clothing_refresh_required, run_s08_production
from .s09_5_instance_recon import ReconciliationInstance, reconcile_instances
from .s09_fusion import run_s09_production

ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class MultiPersonProductionResult:
    shared: tuple[StageExecution, ...]
    per_instance: dict[str, tuple[StageExecution, ...]]
    image_manifest_path: Path
    qc035_passed: bool
    draft_contract_paths: tuple[Path, ...] = ()
    terminal_outcome: str | None = None
    terminal_reason: str | None = None
    cvat_task_ids: tuple[int, ...] = ()


SINGLE_PERSON_REGRESSION_STAGES = (
    "s02",
    "s03",
    "s04",
    "s05",
    "s06",
    "s07",
    "s08",
    "s08_5",
    "s09",
)
P8_ONLY_SINGLE_PERSON_FILES = {"s02": {"other_person_protected.png"}}


def verify_single_person_regression(
    image_id: str, *, legacy_work_root: Path, p8_work_root: Path
) -> dict[str, Any]:
    """Prove P8's p0 stage artifacts are byte-identical to the pre-P8 layout."""
    stage_results = {}
    tree_digest = hashlib.sha256()
    total_files = 0
    added_files = {}
    for stage in SINGLE_PERSON_REGRESSION_STAGES:
        legacy = Path(legacy_work_root) / stage / image_id
        activated = Path(p8_work_root) / "instances" / "p0" / stage / image_id
        if not legacy.is_dir() or not activated.is_dir():
            raise SemanticStageError(f"single-person regression stage missing: {stage}")
        legacy_files = {
            path.relative_to(legacy).as_posix(): path
            for path in sorted(legacy.rglob("*"))
            if path.is_file()
        }
        activated_files = {
            path.relative_to(activated).as_posix(): path
            for path in sorted(activated.rglob("*"))
            if path.is_file()
        }
        allowed_additions = P8_ONLY_SINGLE_PERSON_FILES.get(stage, set())
        actual_additions = set(activated_files) - set(legacy_files)
        if (
            not legacy_files
            or set(legacy_files) - set(activated_files)
            or actual_additions - allowed_additions
        ):
            raise SemanticStageError(
                f"single-person regression file set differs for {stage}: "
                f"legacy={sorted(legacy_files)}, p8={sorted(activated_files)}"
            )
        if actual_additions:
            added_files[stage] = {
                relative: _sha256_file(activated_files[relative])
                for relative in sorted(actual_additions)
            }
        stage_digest = hashlib.sha256()
        for relative in sorted(legacy_files):
            legacy_bytes = legacy_files[relative].read_bytes()
            activated_bytes = activated_files[relative].read_bytes()
            if legacy_bytes != activated_bytes:
                raise SemanticStageError(
                    f"single-person regression bytes differ: {stage}/{relative}"
                )
            stage_digest.update(relative.encode("utf-8") + b"\0" + legacy_bytes)
            tree_digest.update(stage.encode("ascii") + b"\0")
            tree_digest.update(relative.encode("utf-8") + b"\0" + legacy_bytes)
            total_files += 1
        stage_results[stage] = {
            "file_count": len(legacy_files),
            "sha256": stage_digest.hexdigest(),
        }
    return {
        "image_id": image_id,
        "instance": "p0",
        "stages": stage_results,
        "file_count": total_files,
        "p8_only_files": added_files,
        "tree_sha256": tree_digest.hexdigest(),
        "byte_identical": True,
    }


def build_production_runners(
    config: Mapping[str, Any],
    *,
    images_root: Path = ROOT / "data" / "images",
    person_index: int = 0,
    shared_work_root: Path | None = None,
) -> dict[str, StageRunner]:
    """Return production runners scoped to one promoted person (p0 by default)."""
    if person_index < 0:
        raise ValueError("person_index must be non-negative")
    images_root = Path(images_root)
    instance_name = f"p{person_index}"
    parsing_map = config.get("parsing_map", {})
    pose_rules = config.get("pose_tags_rules", {})
    prompting = yaml.safe_load((ROOT / "configs" / "prompting.yaml").read_text(encoding="utf-8"))

    def prior(context: StageContext, stage_name: str) -> Path:
        if shared_work_root is not None and stage_name in {"S01", "S09.5"}:
            return Path(shared_work_root) / stage_name.lower().replace(".", "_") / context.image_id
        return context.prior_stage_dir(stage_name)

    def selected_person(document: Mapping[str, Any]) -> Mapping[str, Any]:
        person = next(
            (item for item in document["persons"] if item["person_index"] == person_index),
            None,
        )
        if person is None:
            raise SemanticStageError(f"promoted person_index={person_index} unavailable")
        return person

    def s00(context: StageContext) -> Mapping[str, Any]:
        manifest, source_path = _source(context.image_id, images_root)
        if manifest.get("status") != "ingested":
            raise SemanticStageError(
                f"S00 requires ingested source, got {manifest.get('status')!r}"
            )
        return {
            "source_file": str(source_path),
            "source_sha256": manifest["source"]["source_sha256"],
            "source_width": manifest["source"]["source_width"],
            "source_height": manifest["source"]["source_height"],
        }

    def s01(context: StageContext) -> Mapping[str, Any]:
        _, source_path = _source(context.image_id, images_root)
        settings = context.config["stage"]
        result = run_s01(
            source_path,
            context.output_dir,
            checkpoint=ROOT / "models" / "detect" / "yolo11m.pt",
            confidence_min=float(settings.get("confidence", 0.5)),
            device="cpu",
            instance_min_area_pct=float(settings.get("instance_min_area_pct", 0.04)),
            max_instances_per_image=int(settings.get("max_instances_per_image", 4)),
            crowd_scene_threshold=int(settings.get("crowd_scene_threshold", 8)),
            context_scale=float(settings.get("context_scale", 1.25)),
        )
        if result.outcome != "promoted":
            return {
                "outcome": result.outcome,
                "reason": result.reason,
                "promoted_instances": 0,
                "background_people": 0,
                "_terminal": {"outcome": result.outcome, "reason": result.reason},
                "_telemetry": {"model_keys": ["yolo11m"]},
            }
        return {
            "outcome": result.outcome,
            "promoted_instances": sum(person.promoted for person in result.persons),
            "background_people": sum(person.protected_as_part_50 for person in result.persons),
            "_telemetry": {"model_keys": ["yolo11m"]},
        }

    def s02(context: StageContext) -> Mapping[str, Any]:
        s01_dir = prior(context, "S01")
        document = json.loads((s01_dir / "person_bbox.json").read_text(encoding="utf-8"))
        person = selected_person(document)
        manifest, _ = _source(context.image_id, images_root)
        settings = context.config["stage"]
        if settings.get("model", "birefnet_general") != "birefnet_general":
            raise SemanticStageError(
                "S02 production supports only the governed birefnet_general model"
            )
        if settings.get("precision", "fp16") != "fp16":
            raise SemanticStageError("S02 production requires governed fp16 inference")
        ratio_range = settings.get("silhouette_bbox_ratio", [0.35, 0.95])
        if not isinstance(ratio_range, (list, tuple)) or len(ratio_range) != 2:
            raise SemanticStageError("S02 silhouette_bbox_ratio must contain [minimum, maximum]")
        result = run_s02(
            s01_dir / instance_name / "person_ctx.png",
            context_bbox_xyxy=tuple(person["context_bbox_xyxy"]),
            person_bbox_xyxy=tuple(person["bbox_xyxy"]),
            full_size=(manifest["source"]["source_width"], manifest["source"]["source_height"]),
            output_dir=context.output_dir,
            checkpoint=ROOT / "models" / "silhouette" / "BiRefNet-general.safetensors",
            tile_size=int(settings.get("long_side", 2048)),
            tile_overlap=int(settings.get("tile_overlap", 128)),
            threshold=float(settings.get("threshold", 0.5)),
            connected_min_person_pct=float(settings.get("connected_min_person_pct", 0.01)),
            ratio_range=(float(ratio_range[0]), float(ratio_range[1])),
            local_cuda_python=(
                Path(settings["local_cuda_python"]) if settings.get("local_cuda_python") else None
            ),
            hf_home=Path(settings["hf_home"]) if settings.get("hf_home") else None,
        )
        resolution_root = (
            Path(shared_work_root) if shared_work_root is not None else context.work_root
        )
        try:
            review = apply_s02_review_resolution(
                work_root=resolution_root,
                image_id=context.image_id,
                instance_id=instance_name,
                output_dir=context.output_dir,
                config_hash=context.config_hash,
                person_bbox_xyxy=tuple(person["bbox_xyxy"]),
                full_size=(
                    manifest["source"]["source_width"],
                    manifest["source"]["source_height"],
                ),
            )
        except ReviewResolutionError as exc:
            raise SemanticStageError(f"S02 review resolution refused: {exc}") from exc
        if review is not None:
            return {
                "silhouette_bbox_ratio": review["silhouette_bbox_ratio"],
                "qc_passed": True,
                "human_review_passed": True,
                "review_decision": review["decision"],
                "reviewer": review["reviewer"],
                "resolution_sha256": review["resolution_sha256"],
                "_telemetry": {"model_keys": ["birefnet_general"]},
            }
        if not result.qc_passed:
            reason = (
                f"silhouette_bbox_ratio={result.silhouette_bbox_ratio:.6f} outside "
                f"[{float(ratio_range[0]):.2f},{float(ratio_range[1]):.2f}]"
            )
            return {
                "silhouette_bbox_ratio": result.silhouette_bbox_ratio,
                "qc_passed": False,
                "reason": reason,
                "_terminal": {"outcome": "needs_review", "reason": reason},
                "_telemetry": {"model_keys": ["birefnet_general"]},
            }
        return {
            "silhouette_bbox_ratio": result.silhouette_bbox_ratio,
            "qc_passed": True,
            "_telemetry": {"model_keys": ["birefnet_general"]},
        }

    def s03(context: StageContext) -> Mapping[str, Any]:
        crop = prior(context, "S01") / instance_name / "person_ctx.png"
        settings = context.config["stage"]
        required = {
            "model": "sapiens_0_6b_seg",
            "precision": "bf16",
            "oom_half_res_retry": True,
            "fallback": "schp_atr",
        }
        drift = {
            key: (settings.get(key), expected)
            for key, expected in required.items()
            if settings.get(key) != expected
        }
        if drift:
            raise SemanticStageError(f"S03 settings violate governed contract: {drift}")
        result = run_s03_production(
            crop,
            sapiens_checkpoint=ROOT / "models" / "parsing" / "sapiens_0.6b_seg.pt2",
            schp_checkpoint=ROOT / "models" / "parsing_fallback" / "exp-schp-201908301523-atr.pth",
            sapiens_map=parsing_map["sapiens_28"],
            schp_map=parsing_map["schp_atr"],
            output_dir=context.output_dir,
            sapiens_long_side=int(settings.get("long_side", 1024)),
            tile_size=int(settings.get("tile_size", 1536)),
            tile_overlap=int(settings.get("tile_overlap", 128)),
            local_cuda_python=(
                Path(settings["local_cuda_python"]) if settings.get("local_cuda_python") else None
            ),
            schp_cache=Path(settings["schp_cache"]) if settings.get("schp_cache") else None,
        )
        custom = run_champion_bodypart_prediction(crop, context.output_dir)
        protection_path = context.prior_stage_dir("S02") / "other_person_protected.png"
        suppression = {"suppressed_px": 0, "ambiguous_px": 0, "careful_review": False}
        if protection_path.is_file():
            suppression = suppress_co_subject_parsing(
                context.output_dir,
                other_person_protected_full=np.asarray(Image.open(protection_path).convert("L")),
                target_silhouette_full=np.asarray(
                    Image.open(context.prior_stage_dir("S02") / "person_full_visible.png").convert(
                        "L"
                    )
                ),
                context_bbox_xyxy=tuple(
                    selected_person(
                        json.loads(
                            (prior(context, "S01") / "person_bbox.json").read_text(encoding="utf-8")
                        )
                    )["context_bbox_xyxy"]
                ),
            )
        model_keys = ["sapiens_0_6b_seg", "schp_atr"]
        if custom is not None:
            model_keys.append(custom.model_key)
        return {
            "parsing_degraded": result.parsing_degraded or suppression["careful_review"],
            "sapiens_scale": result.sapiens_scale,
            "co_subject_suppressed_px": suppression["suppressed_px"],
            "co_subject_ambiguous_px": suppression["ambiguous_px"],
            "careful_review": suppression["careful_review"],
            "custom_bodypart": custom is not None,
            "_telemetry": {"model_keys": model_keys},
        }

    def s04(context: StageContext) -> Mapping[str, Any]:
        settings = context.config["stage"]
        if settings.get("model") != "dwpose_133":
            raise SemanticStageError("S04 production requires governed dwpose_133 model")
        _, source_path = _source(context.image_id, images_root)
        people = json.loads(
            (prior(context, "S01") / "person_bbox.json").read_text(encoding="utf-8")
        )
        person = selected_person(people)
        promoted_bboxes = {
            int(item["person_index"]): tuple(item["bbox_xyxy"])
            for item in people["persons"]
            if item.get("promoted") and item.get("person_index") is not None
        }
        result = run_s04_production(
            source_path,
            instance_bbox_xyxy=tuple(person["bbox_xyxy"]),
            detector_checkpoint=ROOT / "models" / "pose" / "yolox_l.onnx",
            pose_checkpoint=ROOT / "models" / "pose" / "dw-ll_ucoco_384.onnx",
            output_dir=context.output_dir,
            pose_tag_rules=pose_rules,
            require_cuda=True,
            promoted_instance_bboxes=promoted_bboxes,
            person_index=person_index,
            confidence_min=float(settings.get("keypoint_confidence", 0.3)),
            degraded_body_fraction=float(settings.get("degraded_body_keypoint_fraction", 0.6)),
            use_wsl=True,
            local_cuda_python=(
                Path(settings["local_cuda_python"]) if settings.get("local_cuda_python") else None
            ),
            ort_gpu_site=Path(settings["ort_gpu_site"]) if settings.get("ort_gpu_site") else None,
        )
        return {
            "view": result.view,
            "pose_tags": list(result.pose_tags),
            "pose_degraded": result.pose_degraded,
            "_telemetry": {"model_keys": ["dwpose_yolox_l", "dwpose_133"]},
        }

    def s05(context: StageContext) -> Mapping[str, Any]:
        s01_dir = prior(context, "S01")
        people = json.loads((s01_dir / "person_bbox.json").read_text(encoding="utf-8"))
        person = selected_person(people)
        s03_dir = context.prior_stage_dir("S03")
        parsing_path = s03_dir / "sapiens_28.png"
        parser_map = parsing_map["sapiens_28"]
        if not parsing_path.is_file():
            parsing_path = s03_dir / "schp_atr.png"
            parser_map = parsing_map["schp_atr"]
        priors, plans, crops = run_s05_production(
            parsing_path=parsing_path,
            silhouette_path=context.prior_stage_dir("S02") / "person_full_visible.png",
            pose_path=context.prior_stage_dir("S04") / "pose133.json",
            context_bbox_xyxy=tuple(person["context_bbox_xyxy"]),
            parsing_map=parser_map,
            output_dir=context.output_dir,
        )
        if not priors:
            raise SemanticStageError("S05 produced no non-empty geometry priors")
        return {
            "prior_count": len(priors),
            "prompt_count": len(plans),
            "crop_request_count": len(crops),
        }

    def s06(context: StageContext) -> Mapping[str, Any]:
        gdino = prompting["grounding_dino"]
        settings = context.config["stage"]
        if gdino.get("role") != "proposal_boxes_only" or gdino.get("may_write_final_masks"):
            raise SemanticStageError("S06 prompting authority must remain proposal boxes only")
        configured_thresholds = (
            float(gdino["box_threshold"]),
            float(gdino["text_threshold"]),
        )
        stage_thresholds = (
            float(settings.get("box_threshold", 0.30)),
            float(settings.get("text_threshold", 0.25)),
        )
        if configured_thresholds != stage_thresholds:
            raise SemanticStageError("S06 pipeline/prompt threshold configuration drift")
        path = run_s06_production(
            prior(context, "S01") / instance_name / "person_ctx.png",
            context.output_dir,
            checkpoint=ROOT / "models" / "gdino" / "groundingdino_swint_ogc.pth",
            prompts=tuple(gdino["prompts"]),
            box_threshold=stage_thresholds[0],
            text_threshold=stage_thresholds[1],
            local_python=(Path(settings["local_python"]) if settings.get("local_python") else None),
            source_path=Path(settings["source_path"]) if settings.get("source_path") else None,
            dependency_site=(
                Path(settings["dependency_site"]) if settings.get("dependency_site") else None
            ),
            hf_home=Path(settings["hf_home"]) if settings.get("hf_home") else None,
        )
        document = json.loads(path.read_text(encoding="utf-8"))
        if document["authority"] != "proposal_boxes_only" or document["may_write_final_masks"]:
            raise SemanticStageError("S06 proposal-only authority boundary violated")
        return {
            "proposal_count": len(document["proposals"]),
            "authority": document["authority"],
            "_telemetry": {"model_keys": ["groundingdino_swint_ogc"]},
        }

    def s07(context: StageContext) -> Mapping[str, Any]:
        settings = context.config["stage"]
        model_aliases = {
            "sam2_1_large": "sam2.1_hiera_large",
            "sam2_1_base_plus": "sam2.1_hiera_base_plus",
        }
        try:
            primary = model_aliases[settings["primary_model"]]
            fallback = model_aliases[settings["oom_fallback"]]
        except KeyError as exc:
            raise SemanticStageError(f"S07 model configuration is not governed: {exc}") from exc
        if primary == fallback:
            raise SemanticStageError("S07 primary and OOM fallback must differ")
        provider = WslSam2Provider(
            checkpoints={
                "sam2.1_hiera_large": ROOT / "models/sam2/sam2.1_hiera_large.pt",
                "sam2.1_hiera_base_plus": ROOT / "models/sam2/sam2.1_hiera_base_plus.pt",
            },
            configs={
                "sam2.1_hiera_large": "configs/sam2.1/sam2.1_hiera_l.yaml",
                "sam2.1_hiera_base_plus": "configs/sam2.1/sam2.1_hiera_b+.yaml",
            },
            work_dir=context.output_dir / "provider_work",
            local_cuda_python=(
                Path(settings["local_cuda_python"]) if settings.get("local_cuda_python") else None
            ),
            source_path=Path(settings["source_path"]) if settings.get("source_path") else None,
            dependency_site=(
                Path(settings["dependency_site"]) if settings.get("dependency_site") else None
            ),
        )
        results, model = run_s07_production(
            prior(context, "S01") / instance_name / "person_ctx.png",
            context.prior_stage_dir("S05") / "prompts.json",
            context.prior_stage_dir("S05"),
            context.output_dir,
            provider=provider,
            primary_model=primary,
            fallback_model=fallback,
        )
        people = json.loads(
            (prior(context, "S01") / "person_bbox.json").read_text(encoding="utf-8")
        )
        person = selected_person(people)
        lane_audit = apply_champion_hand_drafts(
            results,
            source_path=prior(context, "S01") / instance_name / "person_ctx.png",
            pose_path=context.prior_stage_dir("S04") / "pose133.json",
            context_bbox_xyxy=tuple(person["context_bbox_xyxy"]),
            output_dir=context.output_dir,
        )
        hand_audit = apply_and_record_s07_hand_merges(
            results,
            pose_path=context.prior_stage_dir("S04") / "pose133.json",
            output_dir=context.output_dir,
            image_id=context.image_id,
            instance_id=instance_name,
            model=model,
            failure_queue_path=ROOT / "qa/failure_queue.jsonl",
        )
        model_keys = [model]
        if lane_audit["model_key"]:
            model_keys.append(str(lane_audit["model_key"]))
        return {
            "refined_part_count": len(results),
            "low_confidence_count": sum(result.sam2_low_conf for result in results.values()),
            "embedding_count": 1,
            "model": model,
            "hand_merge_failure_count": hand_audit["failure_record_count"],
            "champion_hand_sides": list(lane_audit["sides"]),
            "_telemetry": {"model_keys": model_keys},
        }

    def s08(context: StageContext) -> Mapping[str, Any]:
        s01_dir = prior(context, "S01")
        people = json.loads((s01_dir / "person_bbox.json").read_text(encoding="utf-8"))
        person = selected_person(people)
        s03_dir = context.prior_stage_dir("S03")
        sapiens_path = s03_dir / "sapiens_28.png"
        sam_settings = config["stages"]["S07"]
        provider = WslSam2Provider(
            checkpoints={
                "sam2.1_hiera_large": ROOT / "models/sam2/sam2.1_hiera_large.pt",
                "sam2.1_hiera_base_plus": ROOT / "models/sam2/sam2.1_hiera_base_plus.pt",
            },
            configs={
                "sam2.1_hiera_large": "configs/sam2.1/sam2.1_hiera_l.yaml",
                "sam2.1_hiera_base_plus": "configs/sam2.1/sam2.1_hiera_b+.yaml",
            },
            work_dir=context.output_dir / "provider_work",
            local_cuda_python=(
                Path(sam_settings["local_cuda_python"])
                if sam_settings.get("local_cuda_python")
                else None
            ),
            source_path=(
                Path(sam_settings["source_path"]) if sam_settings.get("source_path") else None
            ),
            dependency_site=(
                Path(sam_settings["dependency_site"])
                if sam_settings.get("dependency_site")
                else None
            ),
        )
        draft = run_s08_production(
            source_path=s01_dir / instance_name / "person_ctx.png",
            sapiens_path=sapiens_path if sapiens_path.is_file() else None,
            schp_path=s03_dir / "schp_atr.png",
            silhouette_path=context.prior_stage_dir("S02") / "person_full_visible.png",
            pose_path=context.prior_stage_dir("S04") / "pose133.json",
            gdino_path=context.prior_stage_dir("S06") / "gdino_boxes.json",
            context_bbox_xyxy=tuple(person["context_bbox_xyxy"]),
            sapiens_map=parsing_map["sapiens_28"],
            schp_map=parsing_map["schp_atr"],
            output_dir=context.output_dir,
            provider=provider,
        )
        evidence = json.loads((context.output_dir / "material_evidence.json").read_text())
        model_keys = (
            [str(evidence["model_key"])]
            if evidence.get("primary") == "champion_clothing"
            else ["sam2.1_hiera_large"]
        )
        return {
            "material_region_count": int(sum(bool(mask.any()) for mask in draft.regions.values())),
            "assigned_pixel_count": int((draft.material_map > 0).sum()),
            "_telemetry": {"model_keys": model_keys},
        }

    def s08_5(context: StageContext) -> Mapping[str, Any]:
        settings = context.config["stage"]
        s01_dir = prior(context, "S01")
        crop_path = s01_dir / instance_name / "person_ctx.png"
        people = json.loads((s01_dir / "person_bbox.json").read_text(encoding="utf-8"))
        person = selected_person(people)
        context_box = person["context_bbox_xyxy"]
        box = person["bbox_xyxy"]
        crop_box = (
            box[0] - context_box[0],
            box[1] - context_box[1],
            box[2] - context_box[0],
            box[3] - context_box[1],
        )
        provider = WslDensePoseProvider(
            checkpoint=ROOT / "models/densepose/densepose_rcnn_R_50_FPN_s1x.pkl",
            config_path=(
                "/home/kevin/mfwork/source/detectron2/projects/DensePose/configs/"
                "densepose_rcnn_R_50_FPN_s1x.yaml"
            ),
            image_path=crop_path,
            target_bbox_xyxy=crop_box,
            work_dir=context.output_dir / "provider_work",
            local_cuda_python=(
                Path(settings["local_cuda_python"]) if settings.get("local_cuda_python") else None
            ),
            source_path=Path(settings["source_path"]) if settings.get("source_path") else None,
            dependency_site=(
                Path(settings["dependency_site"]) if settings.get("dependency_site") else None
            ),
        )
        image = np.asarray(Image.open(crop_path).convert("RGB"))
        path = run_densepose(provider, image, context.output_dir)
        with Image.open(path) as opened:
            iuv = np.asarray(opened).copy()
        return {
            "densepose_surface_pixel_count": int((iuv[:, :, 0] > 0).sum()),
            "iuv_shape": list(iuv.shape[:2]),
            "_telemetry": {"model_keys": ["densepose_rcnn_R_50_FPN_s1x"]},
        }

    def s09(context: StageContext) -> Mapping[str, Any]:
        s01_dir = prior(context, "S01")
        people = json.loads((s01_dir / "person_bbox.json").read_text(encoding="utf-8"))
        person = selected_person(people)
        fusion = config["fusion"]
        result = run_s09_production(
            s03_dir=context.prior_stage_dir("S03"),
            s05_dir=context.prior_stage_dir("S05"),
            s07_dir=context.prior_stage_dir("S07"),
            s08_material_path=context.prior_stage_dir("S08") / "material_draft.png",
            s08_5_iuv_path=context.prior_stage_dir("S08.5") / "densepose_iuv.png",
            silhouette_path=context.prior_stage_dir("S02") / "person_full_visible.png",
            pose_path=context.prior_stage_dir("S04") / "pose133.json",
            context_bbox_xyxy=tuple(person["context_bbox_xyxy"]),
            parsing_maps=parsing_map,
            weights=fusion["weights"],
            output_dir=context.output_dir,
            other_person_protected_path=(
                context.prior_stage_dir("S02") / "other_person_protected.png"
            ),
        )
        return {
            "part_count": len(result.consensus_scores),
            "review_route_counts": {
                route: list(result.review_routes.values()).count(route)
                for route in sorted(set(result.review_routes.values()))
            },
            "occlusion_count": len(result.occlusions),
            "artifact_sha256": result.artifact_sha256,
        }

    def s09_5(context: StageContext) -> Mapping[str, Any]:
        s01_dir = prior(context, "S01")
        people = json.loads((s01_dir / "person_bbox.json").read_text(encoding="utf-8"))
        promoted = [item for item in people["persons"] if item["promoted"]]
        if len(promoted) != 1:
            raise SemanticStageError(
                "S09.5 requires the per-instance outer loop before reconciling multiple promoted people"
            )
        manifest, _ = _source(context.image_id, images_root)
        person = promoted[0]
        silhouette = (
            np.asarray(
                Image.open(context.prior_stage_dir("S02") / "person_full_visible.png").convert("L")
            )
            > 0
        )
        result = reconcile_instances(
            image_id=context.image_id,
            source_file=manifest["source"]["source_file"],
            instances=(
                ReconciliationInstance(
                    instance_name,
                    silhouette,
                    tuple(person["context_bbox_xyxy"]),
                    context.prior_stage_dir("S09"),
                ),
            ),
            output_dir=context.output_dir,
            background_person_count=sum(item["protected_as_part_50"] for item in people["persons"]),
            crowd_scene=False,
        )
        return {
            "promoted_instance_count": 1,
            "maximum_pair_iou": result.maximum_pair_iou,
            "qc035_passed": result.qc035_passed,
            "relationship_count": len(result.relationships),
        }

    def s10(context: StageContext) -> Mapping[str, Any]:
        s01_dir = prior(context, "S01")
        people = json.loads((s01_dir / "person_bbox.json").read_text(encoding="utf-8"))
        person = selected_person(people)
        s09_dir = context.prior_stage_dir("S09")
        report = run_s10_production(
            image_id=context.image_id,
            part_map_path=s09_dir / "label_map_part.png",
            material_map_path=s09_dir / "label_map_material.png",
            disagreement_path=s09_dir / "work/s09/disagreement.png",
            silhouette_path=context.prior_stage_dir("S02") / "person_full_visible.png",
            pose_path=context.prior_stage_dir("S04") / "pose133.json",
            parsing_metrics_path=context.prior_stage_dir("S03") / "parsing_metrics.json",
            sam2_metrics_path=context.prior_stage_dir("S07") / "sam2_metrics.json",
            densepose_path=context.prior_stage_dir("S08.5") / "densepose_iuv.png",
            image_manifest_path=prior(context, "S09.5") / "image_manifest.json",
            context_bbox_xyxy=tuple(person["context_bbox_xyxy"]),
            person_bbox_xyxy=tuple(person["bbox_xyxy"]),
            source_crop_path=s01_dir / instance_name / "person_ctx.png",
            output_dir=context.output_dir,
            multi_instance_inputs=(
                build_multi_instance_qc_inputs(
                    context.image_id,
                    people=people["persons"],
                    work_root=Path(shared_work_root),
                    image_manifest_path=prior(context, "S09.5") / "image_manifest.json",
                    configured_cap=int(config["stages"]["S01"]["max_instances_per_image"]),
                )
                if shared_work_root is not None
                else None
            ),
            failure_queue_path=ROOT / "qa/failure_queue.jsonl",
            failure_instance_id=instance_name,
        )
        return {
            "overall": report["overall"],
            "score": report["score"],
            "failed_block_count": sum(
                check["result"] == "fail" and check.get("severity") == "BLOCK"
                for check in report["checks"]
            ),
            "route_count": sum(check["result"] == "route" for check in report["checks"]),
        }

    def s11(context: StageContext) -> Mapping[str, Any]:
        pose = json.loads((context.prior_stage_dir("S04") / "pose133.json").read_text())
        status = run_s11_production(
            source_crop_path=prior(context, "S01") / instance_name / "person_ctx.png",
            part_map_path=context.prior_stage_dir("S09") / "label_map_part.png",
            s10_report_path=context.prior_stage_dir("S10") / "qa_report.json",
            output_dir=context.output_dir,
            gate_path=ROOT / "qa/vlm_eval/results/production_gate.json",
            failure_queue_path=ROOT / "qa/failure_queue.jsonl",
            pose_angle=str(pose["view"]),
            failure_instance_id=instance_name,
        )
        return {
            "vlm_enabled": status["enabled"],
            "reviewed_part_count": len(status["routes"]),
            "careful_route_count": sum(
                route["queue"] == "careful" for route in status["routes"].values()
            ),
            "whole_image_review": status["whole_image_review"],
        }

    def s12(context: StageContext) -> Mapping[str, Any]:
        manifest, _ = _source(context.image_id, images_root)
        s01_dir = prior(context, "S01")
        people = json.loads((s01_dir / "person_bbox.json").read_text(encoding="utf-8"))
        promoted = [item for item in people["persons"] if item["promoted"]]
        if len(promoted) != 1:
            raise SemanticStageError(
                "S12 multi-person package push requires the per-instance outer loop"
            )
        person = selected_person(people)
        package_root = ROOT / "data/packages" / context.image_id / "instances" / instance_name
        assemble_review_package(
            image_id=context.image_id,
            instance_index=person_index,
            source_crop_path=s01_dir / instance_name / "person_ctx.png",
            part_map_path=context.prior_stage_dir("S09") / "label_map_part.png",
            material_map_path=context.prior_stage_dir("S09") / "label_map_material.png",
            s09_dir=context.prior_stage_dir("S09"),
            s11_dir=context.prior_stage_dir("S11"),
            pose_path=context.prior_stage_dir("S04") / "pose133.json",
            person_bbox_xyxy=tuple(person["bbox_xyxy"]),
            context_bbox_xyxy=tuple(person["context_bbox_xyxy"]),
            person_count=len(people["persons"]),
            intake_source=manifest["source"],
            package_root=package_root,
            ambiguity_path=context.prior_stage_dir("S03") / "ambiguous_do_not_use.png",
        )
        task_ids = push_images(
            CvatClient.from_config(ROOT / "configs/cvat.yaml"),
            (context.image_id,),
            config_path=ROOT / "configs/cvat.yaml",
            packages_root=ROOT / "data/packages",
            task_records=ROOT / "data/cvat/tasks",
        )
        return {
            "package_root": str(package_root),
            "cvat_task_ids": list(task_ids),
            "manual_review_status": "pending_kevin_correction_and_approval",
            "human_approved": False,
        }

    def s13(context: StageContext) -> Mapping[str, Any]:
        package_root = ROOT / "data/packages" / context.image_id / "instances" / instance_name
        manifest_path = package_root / "manifest.json"
        if not manifest_path.is_file():
            raise SemanticStageError("S13 draft package is missing; S12 handoff did not complete")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        frozen = (package_root / ".maskfactory_frozen.json").is_file()
        statuses = {
            entry.get("status")
            for entry in manifest["parts"].values()
            if entry.get("status") != "n/a"
        }
        if not frozen:
            handoff = {
                "status": "needs_kevin_approval",
                "reason": "S13 requires explicit human confirmation after CVAT correction",
                "command": (
                    f"maskfactory package {context.image_id} --reviewer kevin --minutes <minutes>"
                ),
                "current_part_statuses": sorted(statuses),
            }
            context.output_dir.mkdir(parents=True, exist_ok=True)
            (context.output_dir / "approval_handoff.json").write_text(
                json.dumps(handoff, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            return {
                "gold_exported": False,
                "status": "needs_kevin_approval",
                "package_root": str(package_root),
            }
        verification = verify_packages(package_root)[0]
        if not verification.passed or statuses != {"human_approved_gold"}:
            raise SemanticStageError(
                "S13 frozen package failed verification or contains non-gold visible parts"
            )
        return {
            "gold_exported": True,
            "status": "approved_gold",
            "package_root": str(package_root),
            "verified_check_count": len(verification.results),
        }

    def s14(context: StageContext) -> Mapping[str, Any]:
        packages_root = ROOT / "data/packages"
        count = approved_package_count(packages_root)
        if count < 200:
            gate = {
                "status": "entry_gate_not_met",
                "approved_gold_instances": count,
                "required_approved_gold_instances": 200,
                "dataset_built": False,
            }
            context.output_dir.mkdir(parents=True, exist_ok=True)
            (context.output_dir / "dataset_gate.json").write_text(
                json.dumps(gate, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            return gate
        version = next_dataset_version(ROOT / "datasets")
        path = build_dataset(
            packages_root=packages_root,
            output_root=ROOT / "datasets",
            version=version,
            hard_case_file=ROOT / "datasets/hard_case_holdout.txt",
        )
        shutil.copy2(path / "coverage_matrix.json", ROOT / "qa/coverage_matrix.json")
        return {
            "status": "dataset_built_pending_dvc_publish",
            "approved_gold_instances": count,
            "dataset_built": True,
            "dataset_ref": path.name,
        }

    def s15(context: StageContext) -> Mapping[str, Any]:
        count = approved_package_count(ROOT / "data/packages")
        result = run_active_learning(
            failure_queue_path=ROOT / "qa/failure_queue.jsonl",
            coverage_matrix_path=ROOT / "qa/coverage_matrix.json",
            output_dir=ROOT / "qa/reports",
            approved_gold_count=count,
            packages_root=ROOT / "data/packages",
            use_weights_path=ROOT / "configs/training/use_weights.yaml",
        )
        return {
            "unresolved_failure_count": result["unresolved_failure_count"],
            "coverage_deficit_count": result["coverage_deficit_count"],
            "retrain_requested": result["retrain_requested"],
            "acquisition_plan": result["acquisition_plan"],
            "human_edit_harvest": result["human_edit_harvest"],
        }

    return {
        "S00": s00,
        "S01": s01,
        "S02": s02,
        "S03": s03,
        "S04": s04,
        "S05": s05,
        "S06": s06,
        "S07": s07,
        "S08": s08,
        "S08.5": s08_5,
        "S09": s09,
        "S09.5": s09_5,
        "S10": s10,
        "S11": s11,
        "S12": s12,
        "S13": s13,
        "S14": s14,
        "S15": s15,
    }


def _existing_cvat_handoff_task_ids(
    image_id: str,
    promoted_names: tuple[str, ...],
    *,
    task_records: Path,
) -> tuple[int, ...]:
    """Reuse an exact durable handoff and fail closed on partial local task state."""
    expected_instances = {f"{image_id}_{name}" for name in promoted_names}
    instances: dict[str, int] = {}
    overviews: list[tuple[int, set[str]]] = []
    for path in sorted(Path(task_records).glob("task_*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise SemanticStageError(f"invalid CVAT task record {path}: {exc}") from exc
        frames = record.get("frames", [])
        if not any(frame.get("image_id") == image_id for frame in frames):
            continue
        task_id = int(record["task_id"])
        if record.get("job_type") == "instance_review":
            matching = [
                frame.get("instance_id") for frame in frames if frame.get("image_id") == image_id
            ]
            if len(matching) != 1 or matching[0] in instances:
                raise SemanticStageError(
                    f"duplicate or malformed CVAT instance task for {image_id}"
                )
            instances[str(matching[0])] = task_id
        elif record.get("job_type") == "image_overview":
            matching = [frame for frame in frames if frame.get("image_id") == image_id]
            if len(matching) != 1:
                raise SemanticStageError(f"malformed CVAT overview task for {image_id}")
            overviews.append((task_id, set(matching[0].get("instance_ids", []))))
    if not instances and not overviews:
        return ()
    expected_overviews = 1 if len(promoted_names) > 1 else 0
    if set(instances) != expected_instances or len(overviews) != expected_overviews:
        raise SemanticStageError(
            f"partial CVAT handoff records exist for {image_id}; reconcile them before retrying"
        )
    if overviews and overviews[0][1] != expected_instances:
        raise SemanticStageError(f"CVAT overview instance set differs for {image_id}")
    ordered = [instances[f"{image_id}_{name}"] for name in promoted_names]
    ordered.extend(task_id for task_id, _ in overviews)
    return tuple(ordered)


def run_multi_person_production(
    image_id: str,
    *,
    config: Mapping[str, Any],
    images_root: Path = ROOT / "data/images",
    work_root: Path = ROOT / "work",
    gpu_lock_path: Path | None = None,
    pipeline_runner=run_pipeline,
    runner_factory=build_production_runners,
    through_autoqa: bool = False,
    force_autoqa: bool = False,
    through_vlmqa: bool = False,
    force_vlmqa: bool = False,
    through_review_handoff: bool = False,
    database: Path | None = None,
    silhouettes_only: bool = False,
    parsing_only: bool = False,
    pose_only: bool = False,
    openvocab_only: bool = False,
    sam2_only: bool = False,
    densepose_only: bool = False,
    package_assembler=assemble_review_package,
    cvat_pusher=push_images,
    cvat_client_factory=None,
    cvat_task_records: Path = ROOT / "data/cvat/tasks",
) -> MultiPersonProductionResult:
    """Run shared detection and every promoted instance through drafts or S10 auto-QA."""
    work_root = Path(work_root)
    shared_runners = runner_factory(config, images_root=images_root)
    shared = pipeline_runner(
        image_id,
        selected=("S00", "S01"),
        config=config,
        work_root=work_root,
        runners=shared_runners,
        gpu_lock_path=gpu_lock_path,
    )
    s01_dir = work_root / "s01" / image_id
    terminal = next((execution for execution in shared if execution.status == "terminal"), None)
    if terminal is not None:
        if database is not None:
            persist_terminal_image_outcome(
                database,
                image_id,
                str(terminal.terminal_outcome),
                reason=str(terminal.terminal_reason),
                current_stage="S01",
            )
        return MultiPersonProductionResult(
            tuple(shared),
            {},
            s01_dir / "person_bbox.json",
            False,
            (),
            terminal.terminal_outcome,
            terminal.terminal_reason,
        )
    people = json.loads((s01_dir / "person_bbox.json").read_text(encoding="utf-8"))
    promoted = sorted(
        (item for item in people["persons"] if item["promoted"]),
        key=lambda item: item["person_index"],
    )
    if not promoted or [item["person_index"] for item in promoted] != list(range(len(promoted))):
        raise SemanticStageError("S01 promoted person indices must be contiguous from p0")
    per_instance: dict[str, tuple[StageExecution, ...]] = {}
    scoped_runners = {}
    for person in promoted:
        index = int(person["person_index"])
        name = f"p{index}"
        instance_root = work_root / "instances" / name
        runners = runner_factory(
            config,
            images_root=images_root,
            person_index=index,
            shared_work_root=work_root,
        )
        scoped_runners[name] = runners
        per_instance[name] = tuple(
            pipeline_runner(
                image_id,
                selected=("S02",),
                config=config,
                work_root=instance_root,
                runners=runners,
                gpu_lock_path=gpu_lock_path,
                force=(
                    ("S02",)
                    if s02_review_refresh_required(
                        work_root,
                        image_id,
                        name,
                        instance_root / "s02" / image_id,
                    )
                    else ()
                ),
            )
        )
    routed = {
        name: execution
        for name, executions in per_instance.items()
        for execution in executions
        if execution.status == "terminal"
    }
    if routed:
        for name, execution in sorted(routed.items()):
            append_review_route_once(
                work_root / "queues" / "review_queue.jsonl",
                image_id=image_id,
                instance_id=name,
                stage=execution.stage,
                config_hash=execution.config_hash,
                error=str(execution.terminal_reason or ""),
            )
        reason = "; ".join(
            f"{name}:{execution.terminal_reason}" for name, execution in sorted(routed.items())
        )
        return MultiPersonProductionResult(
            tuple(shared),
            per_instance,
            s01_dir / "person_bbox.json",
            False,
            (),
            "needs_review",
            reason,
        )
    if silhouettes_only:
        return MultiPersonProductionResult(
            tuple(shared),
            per_instance,
            s01_dir / "person_bbox.json",
            False,
        )
    _inject_other_person_protection(image_id, promoted, people["persons"], work_root)

    def s03_force(instance_root: Path) -> tuple[str, ...]:
        cached = instance_root / "s03" / image_id
        return ("S03",) if custom_bodypart_refresh_required(cached) else ()

    def runtime_forces(instance_root: Path, selected: tuple[str, ...]) -> tuple[str, ...]:
        forces = list(s03_force(instance_root))
        if "S07" in selected:
            cached = instance_root / "s07" / image_id
            if champion_hand_refresh_required(cached):
                forces.append("S07")
        if "S08" in selected:
            cached = instance_root / "s08" / image_id
            if champion_clothing_refresh_required(cached):
                forces.append("S08")
        return tuple(forces)

    if parsing_only or pose_only or openvocab_only or sam2_only or densepose_only:
        if parsing_only:
            selected = ("S03",)
        elif pose_only:
            selected = ("S03", "S04")
        elif openvocab_only:
            selected = ("S03", "S04", "S05", "S06")
        elif sam2_only:
            selected = ("S03", "S04", "S05", "S06", "S07")
        else:
            selected = ("S03", "S04", "S05", "S06", "S07", "S08", "S08.5")
        for person in promoted:
            name = f"p{person['person_index']}"
            instance_root = work_root / "instances" / name
            partial = pipeline_runner(
                image_id,
                selected=selected,
                config=config,
                work_root=instance_root,
                runners=scoped_runners[name],
                gpu_lock_path=gpu_lock_path,
                force=runtime_forces(instance_root, selected),
            )
            per_instance[name] = (*per_instance[name], *tuple(partial))
        return MultiPersonProductionResult(
            tuple(shared),
            per_instance,
            s01_dir / "person_bbox.json",
            False,
        )
    downstream = ("S03", "S04", "S05", "S06", "S07", "S08", "S08.5", "S09")
    for person in promoted:
        name = f"p{person['person_index']}"
        instance_root = work_root / "instances" / name
        remainder = pipeline_runner(
            image_id,
            selected=downstream,
            config=config,
            work_root=instance_root,
            runners=scoped_runners[name],
            gpu_lock_path=gpu_lock_path,
            force=runtime_forces(instance_root, downstream),
        )
        per_instance[name] = (*per_instance[name], *tuple(remainder))
    manifest, _ = _source(image_id, Path(images_root))
    recon_inputs = tuple(
        ReconciliationInstance(
            f"p{person['person_index']}",
            np.asarray(
                Image.open(
                    work_root
                    / "instances"
                    / f"p{person['person_index']}"
                    / "s02"
                    / image_id
                    / "person_full_visible.png"
                ).convert("L")
            )
            > 0,
            tuple(person["context_bbox_xyxy"]),
            work_root / "instances" / f"p{person['person_index']}" / "s09" / image_id,
        )
        for person in promoted
    )
    recon_dir = work_root / "s09_5" / image_id
    reconciliation = reconcile_instances(
        image_id=image_id,
        source_file=manifest["source"]["source_file"],
        instances=recon_inputs,
        output_dir=recon_dir,
        background_person_count=sum(item["protected_as_part_50"] for item in people["persons"]),
        crowd_scene=False,
    )
    draft_contract_paths = materialize_d1_atomic_drafts(
        image_id,
        promoted=promoted,
        manifest=manifest,
        work_root=work_root,
    )
    if through_autoqa or through_vlmqa or through_review_handoff:
        for person in promoted:
            name = f"p{person['person_index']}"
            instance_root = work_root / "instances" / name
            autoqa = pipeline_runner(
                image_id,
                selected=("S10",),
                force=("S10",) if force_autoqa else (),
                config=config,
                work_root=instance_root,
                runners=scoped_runners[name],
                gpu_lock_path=gpu_lock_path,
            )
            per_instance[name] = (*per_instance[name], *tuple(autoqa))
    cvat_task_ids: tuple[int, ...] = ()
    if through_vlmqa or through_review_handoff:
        for person in promoted:
            name = f"p{person['person_index']}"
            instance_root = work_root / "instances" / name
            vlmqa = pipeline_runner(
                image_id,
                selected=("S11",),
                force=("S11",) if force_vlmqa else (),
                config=config,
                work_root=instance_root,
                runners=scoped_runners[name],
                gpu_lock_path=gpu_lock_path,
            )
            per_instance[name] = (*per_instance[name], *tuple(vlmqa))
        if through_vlmqa and not through_review_handoff:
            return MultiPersonProductionResult(
                tuple(shared),
                per_instance,
                reconciliation.image_manifest_path,
                reconciliation.qc035_passed,
                draft_contract_paths,
            )
        manifest, _ = _source(image_id, Path(images_root))
        promoted_names = tuple(f"p{person['person_index']}" for person in promoted)
        cvat_task_ids = _existing_cvat_handoff_task_ids(
            image_id,
            promoted_names,
            task_records=cvat_task_records,
        )
        package_roots = {
            name: ROOT / "data/packages" / image_id / "instances" / name for name in promoted_names
        }
        if not cvat_task_ids:
            for person in promoted:
                index = int(person["person_index"])
                name = f"p{index}"
                instance_root = work_root / "instances" / name
                package_assembler(
                    image_id=image_id,
                    instance_index=index,
                    source_crop_path=work_root / "s01" / image_id / name / "person_ctx.png",
                    part_map_path=instance_root / "s09" / image_id / "label_map_part.png",
                    material_map_path=instance_root / "s09" / image_id / "label_map_material.png",
                    s09_dir=instance_root / "s09" / image_id,
                    s11_dir=instance_root / "s11" / image_id,
                    pose_path=instance_root / "s04" / image_id / "pose133.json",
                    person_bbox_xyxy=tuple(person["bbox_xyxy"]),
                    context_bbox_xyxy=tuple(person["context_bbox_xyxy"]),
                    person_count=len(people["persons"]),
                    intake_source=manifest["source"],
                    package_root=package_roots[name],
                    ambiguity_path=instance_root / "s03" / image_id / "ambiguous_do_not_use.png",
                )
            client = (
                cvat_client_factory()
                if cvat_client_factory is not None
                else CvatClient.from_config(ROOT / "configs/cvat.yaml")
            )
            cvat_task_ids = tuple(
                cvat_pusher(
                    client,
                    (image_id,),
                    config_path=ROOT / "configs/cvat.yaml",
                    packages_root=ROOT / "data/packages",
                    task_records=cvat_task_records,
                )
            )
        if len(cvat_task_ids) != len(promoted) + (1 if len(promoted) > 1 else 0):
            raise SemanticStageError("S12 CVAT task fan-out differs from promoted instance count")
        for person in promoted:
            name = f"p{person['person_index']}"
            instance_root = work_root / "instances" / name

            def completed_s12(_context, *, _name=name):
                return {
                    "package_root": str(package_roots[_name]),
                    "cvat_task_ids": list(cvat_task_ids),
                    "manual_review_status": "pending_kevin_correction_and_approval",
                    "human_approved": False,
                }

            runners = dict(scoped_runners[name])
            runners["S12"] = completed_s12
            handoff = pipeline_runner(
                image_id,
                selected=("S12",),
                force=("S12",),
                config=config,
                work_root=instance_root,
                runners=runners,
                gpu_lock_path=gpu_lock_path,
            )
            per_instance[name] = (*per_instance[name], *tuple(handoff))
    return MultiPersonProductionResult(
        tuple(shared),
        per_instance,
        reconciliation.image_manifest_path,
        reconciliation.qc035_passed,
        draft_contract_paths,
        cvat_task_ids=cvat_task_ids,
    )


def build_multi_instance_qc_inputs(
    image_id: str,
    *,
    people: list[Mapping[str, Any]],
    work_root: Path,
    image_manifest_path: Path,
    configured_cap: int,
) -> MultiInstanceQcInputs:
    """Project every instance's S02/S09/contact evidence to one full source canvas."""
    promoted = sorted(
        (item for item in people if item.get("promoted")),
        key=lambda item: int(item["person_index"]),
    )
    names = [f"p{int(item['person_index'])}" for item in promoted]
    if not promoted or names != [f"p{index}" for index in range(len(promoted))]:
        raise SemanticStageError("S10 multi-instance evidence requires contiguous promoted pN")
    if configured_cap < 1:
        raise SemanticStageError("S10 configured instance cap must be positive")
    work_root = Path(work_root)
    silhouettes: dict[str, np.ndarray] = {}
    atomics: dict[str, np.ndarray] = {}
    band_by_instance: dict[str, np.ndarray] = {}
    shape: tuple[int, int] | None = None
    other_person_id = int(get_ontology().label("other_person").id)
    for person, name in zip(promoted, names, strict=True):
        silhouette = (
            read_mask(work_root / "instances" / name / "s02" / image_id / "person_full_visible.png")
            > 0
        )
        if shape is None:
            shape = silhouette.shape
        if silhouette.shape != shape:
            raise SemanticStageError("S10 instance silhouettes do not share full-canvas geometry")
        silhouettes[name] = silhouette
        x1, y1, x2, y2 = (int(value) for value in person["context_bbox_xyxy"])
        if not (0 <= x1 < x2 <= shape[1] and 0 <= y1 < y2 <= shape[0]):
            raise SemanticStageError(f"S10 invalid context bbox for {name}")
        part = read_mask(work_root / "instances" / name / "s09" / image_id / "label_map_part.png")
        if part.shape != (y2 - y1, x2 - x1):
            raise SemanticStageError(f"S10 {name} PART map differs from context geometry")
        full_union = np.zeros(shape, dtype=bool)
        full_union[y1:y2, x1:x2] = (part != 0) & (part != other_person_id)
        atomics[name] = full_union
        band_path = (
            work_root
            / "instances"
            / name
            / "s09"
            / image_id
            / "masks_regions/interperson_contact_boundary.png"
        )
        if band_path.is_file():
            band = read_mask(band_path) > 0
            if band.shape != part.shape:
                raise SemanticStageError(f"S10 {name} contact band differs from context geometry")
            full_band = np.zeros(shape, dtype=bool)
            full_band[y1:y2, x1:x2] = band
            band_by_instance[name] = full_band
    image_manifest = json.loads(Path(image_manifest_path).read_text(encoding="utf-8"))
    if image_manifest.get("promoted_instances") != names:
        raise SemanticStageError("S10 image_manifest promoted instances disagree with S01")
    relationships = {name: set() for name in names}
    contact_bands = {}
    for relationship in image_manifest.get("interperson_relationships", ()):
        a, b = str(relationship.get("a")), str(relationship.get("b"))
        if a not in relationships or b not in relationships or a == b:
            raise SemanticStageError("S10 image_manifest contains an invalid relationship")
        relationships[a].add(b)
        relationships[b].add(a)
        if a not in band_by_instance or b not in band_by_instance:
            raise SemanticStageError("S10 reciprocal relationship is missing a contact band")
        contact_bands[(a, b)] = band_by_instance[a]
        contact_bands[(b, a)] = band_by_instance[b]
    return MultiInstanceQcInputs(
        silhouettes=silhouettes,
        atomic_unions=atomics,
        contact_bands=contact_bands,
        recorded_relationships={name: frozenset(values) for name, values in relationships.items()},
        expected_promoted_count=len(names),
        configured_cap=configured_cap,
    )


def materialize_d1_atomic_drafts(
    image_id: str,
    *,
    promoted: list[Mapping[str, Any]],
    manifest: Mapping[str, Any],
    work_root: Path,
) -> tuple[Path, ...]:
    """Project S09 context maps to source geometry and atomically emit all 56 PART masks."""
    authority = get_ontology()
    labels = tuple(sorted(authority.labels_for_map("part"), key=lambda label: int(label.id)))
    if len(labels) != 56 or [label.id for label in labels] != list(range(56)):
        raise SemanticStageError("D1 requires the authoritative contiguous PART IDs 0..55")
    enabled_ids = {int(label.id) for label in labels if label.enabled}
    material_ids = {
        int(label.id) for label in authority.labels_for_map("material", enabled_only=True)
    }
    try:
        width = int(manifest["source"]["source_width"])
        height = int(manifest["source"]["source_height"])
    except (KeyError, TypeError, ValueError) as exc:
        raise SemanticStageError(f"D1 source geometry unavailable: {exc}") from exc
    if width <= 0 or height <= 0:
        raise SemanticStageError("D1 source geometry must be positive")
    outputs = []
    for person in promoted:
        index = int(person["person_index"])
        instance = f"p{index}"
        left, top, right, bottom = (int(value) for value in person["context_bbox_xyxy"])
        if not (0 <= left < right <= width and 0 <= top < bottom <= height):
            raise SemanticStageError(f"D1 {instance} context bbox is outside source geometry")
        s09_dir = Path(work_root) / "instances" / instance / "s09" / image_id
        part = read_mask(s09_dir / "label_map_part.png").astype(np.uint16)
        material = read_mask(s09_dir / "label_map_material.png").astype(np.uint8)
        expected_shape = (bottom - top, right - left)
        if part.shape != expected_shape or material.shape != expected_shape:
            raise SemanticStageError(f"D1 {instance} S09 maps differ from context geometry")
        unknown = set(np.unique(part).tolist()) - enabled_ids
        if unknown:
            raise SemanticStageError(
                f"D1 {instance} part map has disabled/unknown IDs: {sorted(unknown)}"
            )
        unknown_material = set(np.unique(material).tolist()) - material_ids
        if unknown_material:
            raise SemanticStageError(
                f"D1 {instance} material map has disabled/unknown IDs: {sorted(unknown_material)}"
            )
        destination = Path(work_root) / "drafts" / image_id / "instances" / instance
        destination.parent.mkdir(parents=True, exist_ok=True)
        staging = destination.parent / f".{instance}.tmp-{uuid.uuid4().hex}"
        backup = destination.parent / f".{instance}.backup-{uuid.uuid4().hex}"
        try:
            staging.mkdir()
            full_part = np.zeros((height, width), dtype=np.uint16)
            full_material = np.zeros((height, width), dtype=np.uint8)
            full_part[top:bottom, left:right] = part
            full_material[top:bottom, left:right] = material
            write_label_map(staging / "label_map_part.png", full_part, bits=16)
            write_label_map(staging / "label_map_material.png", full_material, bits=8)
            records = []
            for label in labels:
                label_id = int(label.id)
                mask = full_part == label_id
                directory = (
                    "protected" if label_id == 0 or label.mask_type == "protected_qa" else "masks"
                )
                path = write_binary_mask(
                    staging / directory / f"{label.name}.png",
                    mask,
                    source_size=(width, height),
                )
                records.append(
                    {
                        "id": label_id,
                        "name": label.name,
                        "enabled": label.enabled,
                        "pixel_count": int(mask.sum()),
                        "path": path.relative_to(staging).as_posix(),
                        "sha256": _sha256_file(path),
                    }
                )
            document = {
                "schema_version": "1.0.0",
                "contract": "D1_all_56_atomic_parts",
                "image_id": image_id,
                "instance": instance,
                "source_size": [width, height],
                "context_bbox_xyxy": [left, top, right, bottom],
                "atomic_count": len(records),
                "enabled_atomic_count": sum(record["enabled"] for record in records),
                "disabled_atomic_ids": [
                    record["id"] for record in records if not record["enabled"]
                ],
                "part_map_sha256": _sha256_file(staging / "label_map_part.png"),
                "material_map_sha256": _sha256_file(staging / "label_map_material.png"),
                "atomics": records,
            }
            contract_path = staging / "draft_contract.json"
            contract_path.write_text(
                json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            _verify_d1_draft_directory(staging, document, full_part)
            if destination.exists():
                replace_with_retry(destination, backup)
            try:
                replace_with_retry(staging, destination)
            except Exception:
                if backup.exists():
                    replace_with_retry(backup, destination)
                raise
            shutil.rmtree(backup, ignore_errors=True)
            outputs.append(destination / "draft_contract.json")
        finally:
            shutil.rmtree(staging, ignore_errors=True)
    return tuple(outputs)


def _verify_d1_draft_directory(
    directory: Path, document: Mapping[str, Any], full_part: np.ndarray
) -> None:
    if document.get("atomic_count") != 56 or len(document.get("atomics", ())) != 56:
        raise SemanticStageError("D1 draft contract must enumerate exactly 56 atomic masks")
    claimed = np.zeros(full_part.shape, dtype=np.uint16)
    seen = np.zeros(full_part.shape, dtype=np.uint8)
    for record in document["atomics"]:
        path = directory / record["path"]
        mask = read_mask(path)
        if mask.shape != full_part.shape or set(np.unique(mask).tolist()) - {0, 255}:
            raise SemanticStageError(f"D1 atomic mask is not strict/full-size: {path}")
        foreground = mask == 255
        if np.any(seen[foreground]):
            raise SemanticStageError(f"D1 atomic masks overlap: {path}")
        claimed[foreground] = int(record["id"])
        seen[foreground] = 1
        if _sha256_file(path) != record["sha256"]:
            raise SemanticStageError(f"D1 atomic hash mismatch: {path}")
    if not np.all(seen == 1) or not np.array_equal(claimed, full_part):
        raise SemanticStageError("D1 atomic masks do not reproduce the full-resolution PART map")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _inject_other_person_protection(
    image_id: str,
    promoted: list[Mapping[str, Any]],
    all_people: list[Mapping[str, Any]],
    work_root: Path,
) -> None:
    silhouettes = {
        int(person["person_index"]): np.asarray(
            Image.open(
                work_root
                / "instances"
                / f"p{person['person_index']}"
                / "s02"
                / image_id
                / "person_full_visible.png"
            ).convert("L")
        )
        > 0
        for person in promoted
    }
    shape = next(iter(silhouettes.values())).shape
    for target in promoted:
        target_index = int(target["person_index"])
        protected = np.zeros(shape, dtype=bool)
        for other_index, silhouette in silhouettes.items():
            if other_index != target_index:
                protected |= silhouette
        for person in all_people:
            if person.get("promoted"):
                continue
            left, top, right, bottom = person["bbox_xyxy"]
            protected[max(0, top) : min(shape[0], bottom), max(0, left) : min(shape[1], right)] = (
                True
            )
        path = (
            work_root
            / "instances"
            / f"p{target_index}"
            / "s02"
            / image_id
            / "other_person_protected.png"
        )
        write_binary_mask(path, protected, source_size=(shape[1], shape[0]))


def _source(image_id: str, images_root: Path) -> tuple[dict[str, Any], Path]:
    directory = images_root / image_id
    manifest_path = directory / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        source_path = directory / manifest["source"]["source_file"]
    except (OSError, KeyError, json.JSONDecodeError) as exc:
        raise SemanticStageError(
            f"ingested source manifest unavailable for {image_id}: {exc}"
        ) from exc
    if manifest.get("image_id") != image_id or not source_path.is_file():
        raise SemanticStageError(f"ingested source identity/file invalid for {image_id}")
    return manifest, source_path
