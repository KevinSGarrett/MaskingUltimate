from __future__ import annotations
import hashlib,json,os,subprocess,traceback
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path("/workspace/maskfactory");OUT=Path(__file__).resolve().parent;HELPER=ROOT/".train_cu128_ada/bin/python";WHEELS=OUT/"wheels"
def sha(p):
 h=hashlib.sha256()
 with p.open("rb") as f:
  for b in iter(lambda:f.read(4*1024*1024),b""):h.update(b)
 return h.hexdigest()
def canonical(d):return hashlib.sha256(json.dumps({k:v for k,v in d.items() if k!="self_sha256"},sort_keys=True,separators=(",", ":")).encode()).hexdigest()
def write(d):d["self_sha256"]=canonical(d);(OUT/"CANDIDATE_CLOSURE_RECEIPT.json").write_text(json.dumps(d,sort_keys=True,indent=2)+"\n")
def main():
 started=datetime.now(timezone.utc).isoformat();d={"artifact_type":"eomt_dinov3_runtime_closure_candidate_receipt.v1","started_at_utc":started,"status":None,"request":{"top_level_requirement":"transformers==5.13.0","python_abi":"cp311","platform":"current_pod_linux","wheel_only":True},"controls":{"installation_performed":False,"environment_created":False,"model_imported":False,"gpu_execution":False,"provider_promotion":False,"gold_authority":False,"cache_outside_named_output":False}}
 try:
  if WHEELS.exists() or (OUT/"CANDIDATE_CLOSURE_RECEIPT.json").exists():raise RuntimeError("candidate output already exists; refusing duplicate")
  WHEELS.mkdir(parents=True)
  cmd=[str(HELPER),"-m","pip","download","--disable-pip-version-check","--no-cache-dir","--only-binary=:all:","--dest",str(WHEELS),"transformers==5.13.0"]
  r=subprocess.run(cmd,cwd=ROOT,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
  d["download"]={"command":".train_cu128_ada/bin/python -m pip download --disable-pip-version-check --no-cache-dir --only-binary=:all: --dest <named-output>/wheels transformers==5.13.0","returncode":r.returncode,"output":r.stdout}
  if r.returncode:raise RuntimeError("pip wheel resolver failed")
  wheels=[]
  for p in sorted(WHEELS.glob("*.whl")):
   wheels.append({"filename":p.name,"bytes":p.stat().st_size,"sha256":sha(p)})
  if not wheels:raise RuntimeError("resolver produced no wheels")
  d["wheels"]=wheels;d["status"]="CANDIDATE_CLOSURE_WHEELS_DOWNLOADED";d["next_safe_action"]="Create a new immutable requirements lock from this exact wheel manifest before creating an isolated environment. This receipt does not authorize installation, model import, inference, training, promotion, or gold."
  d["ended_at_utc"]=datetime.now(timezone.utc).isoformat();write(d);print(json.dumps({"status":d["status"],"self_sha256":d["self_sha256"],"wheel_count":len(wheels)},sort_keys=True));return 0
 except Exception as e:
  d["status"]="CANDIDATE_CLOSURE_FAIL";d["error"]={"type":type(e).__name__,"message":str(e),"traceback":traceback.format_exc()};d["partial_wheels_preserved"]=str(WHEELS.relative_to(ROOT)) if WHEELS.exists() else None;d["ended_at_utc"]=datetime.now(timezone.utc).isoformat();write(d);print(json.dumps({"status":d["status"],"self_sha256":d["self_sha256"]},sort_keys=True));raise
if __name__=="__main__":raise SystemExit(main())
