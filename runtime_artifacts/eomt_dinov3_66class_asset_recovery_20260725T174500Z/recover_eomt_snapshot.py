from __future__ import annotations
import hashlib,json,os,shutil,traceback
from datetime import datetime,timezone
from pathlib import Path
from huggingface_hub import hf_hub_download
ROOT=Path("/workspace/maskfactory")
OUT=Path(__file__).resolve().parent
TARGET=ROOT/"models/runtime_cache/eomt_dinov3_small_602edaa"
REPO="tue-mps/eomt-dinov3-coco-panoptic-small-640"
REVISION="602edaa2839daf6cb3de3ad46c176098c3be9090"
ASSETS=json.loads((OUT/"recovery_binding.json").read_text())["snapshot"]["assets"]
def sha(p):
 h=hashlib.sha256()
 with p.open("rb") as f:
  for b in iter(lambda:f.read(4*1024*1024),b""):h.update(b)
 return h.hexdigest()
def canonical(d):return hashlib.sha256(json.dumps({k:v for k,v in d.items() if k!="self_sha256"},sort_keys=True,separators=(",", ":")).encode()).hexdigest()
def write(d):
 d["self_sha256"]=canonical(d);(OUT/"ASSET_RECOVERY_RECEIPT.json").write_text(json.dumps(d,sort_keys=True,indent=2)+"\n")
def main():
 started=datetime.now(timezone.utc).isoformat();stage=OUT/"staging";disk=shutil.disk_usage(ROOT)
 d={"artifact_type":"eomt_dinov3_66class_asset_recovery_receipt.v1","started_at_utc":started,"status":None,"snapshot":{"repository":REPO,"revision":REVISION,"assets":ASSETS,"target":str(TARGET.relative_to(ROOT))},"preflight":{"target_exists":TARGET.exists(),"stage_exists":stage.exists(),"free_bytes":disk.free,"minimum_free_bytes":sum(x["size_bytes"] for x in ASSETS)*2},"authority":{"gpu_execution":False,"runtime_installation":False,"provider_promotion":False,"gold_authority":False,"overwrite_allowed":False,"substitution_allowed":False}}
 try:
  if TARGET.exists() or stage.exists():raise RuntimeError("target or staging exists; refusing duplicate/overwrite")
  if disk.free<d["preflight"]["minimum_free_bytes"]:raise RuntimeError("insufficient durable free space for staged recovery")
  stage.mkdir(parents=True)
  actual=[]
  for asset in ASSETS:
   hf_hub_download(repo_id=REPO,repo_type="model",revision=REVISION,filename=asset["filename"],local_dir=stage)
   p=stage/asset["filename"]
   if not p.is_file():raise RuntimeError("missing locked asset after download: "+asset["filename"])
   got={"filename":asset["filename"],"size_bytes":p.stat().st_size,"sha256":sha(p)}
   if got["size_bytes"]!=asset["size_bytes"] or got["sha256"]!=asset["sha256"]:raise RuntimeError("locked asset mismatch: "+asset["filename"])
   actual.append(got)
  TARGET.parent.mkdir(parents=True,exist_ok=True)
  if TARGET.exists():raise RuntimeError("target appeared during recovery; refusing overwrite")
  os.rename(stage,TARGET)
  d["status"]="ASSET_RECOVERY_PASS_EXACT_BOUND_BYTES";d["result"]={"assets":actual,"target":str(TARGET.relative_to(ROOT))};d["next_safe_action"]="Run 66-class static contract tests; EoMT runtime remains uninstalled and no inference/promotion is authorized."
  d["ended_at_utc"]=datetime.now(timezone.utc).isoformat();write(d);print(json.dumps({"status":d["status"],"self_sha256":d["self_sha256"]},sort_keys=True));return 0
 except Exception as exc:
  d["status"]="ASSET_RECOVERY_FAIL";d["error"]={"type":type(exc).__name__,"message":str(exc),"traceback":traceback.format_exc()};d["staging_preserved"]=str(stage.relative_to(ROOT)) if stage.exists() else None;d["ended_at_utc"]=datetime.now(timezone.utc).isoformat();write(d);print(json.dumps({"status":d["status"],"self_sha256":d["self_sha256"]},sort_keys=True));raise
if __name__=="__main__":raise SystemExit(main())
