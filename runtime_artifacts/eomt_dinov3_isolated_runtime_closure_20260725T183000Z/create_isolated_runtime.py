from __future__ import annotations
import hashlib,json,os,subprocess,traceback
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path("/workspace/maskfactory");OUT=Path(__file__).resolve().parent;HELPER=ROOT/".train_cu128_ada/bin/python";REQ=ROOT/"env/eomt_dinov3_runtime.requirements_v1.lock.txt";CANDIDATE=ROOT/"runtime_artifacts/eomt_dinov3_runtime_closure_candidate_20260725T181500Z";WHEELS=CANDIDATE/"wheels";ENV=OUT/"venv"
def sha(p):
 h=hashlib.sha256()
 with p.open("rb") as f:
  for b in iter(lambda:f.read(4*1024*1024),b""):h.update(b)
 return h.hexdigest()
def canonical(d):return hashlib.sha256(json.dumps({k:v for k,v in d.items() if k!="self_sha256"},sort_keys=True,separators=(",", ":")).encode()).hexdigest()
def write(d):d["self_sha256"]=canonical(d);(OUT/"ISOLATED_RUNTIME_RECEIPT.json").write_text(json.dumps(d,sort_keys=True,indent=2)+"\n")
def cmd(args):
 r=subprocess.run(args,cwd=ROOT,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT);return {"argv":args,"returncode":r.returncode,"output":r.stdout[-20000:]}
def main():
 started=datetime.now(timezone.utc).isoformat();d={"artifact_type":"eomt_dinov3_isolated_runtime_closure_receipt.v1","started_at_utc":started,"status":None,"controls":{"network_install":False,"model_load":False,"gpu_execution":False,"provider_promotion":False,"gold_authority":False,"overwrite_allowed":False},"bindings":{"requirements_lock":"env/eomt_dinov3_runtime.requirements_v1.lock.txt","requirements_lock_sha256":sha(REQ),"candidate_receipt":"runtime_artifacts/eomt_dinov3_runtime_closure_candidate_20260725T181500Z/CANDIDATE_CLOSURE_RECEIPT.json","candidate_receipt_sha256":sha(CANDIDATE/"CANDIDATE_CLOSURE_RECEIPT.json")}}
 try:
  if ENV.exists() or (OUT/"ISOLATED_RUNTIME_RECEIPT.json").exists():raise RuntimeError("environment or receipt already exists; refusing duplicate")
  candidate=json.loads((CANDIDATE/"CANDIDATE_CLOSURE_RECEIPT.json").read_text())
  req_text=REQ.read_text();
  for w in candidate["wheels"]:
   p=WHEELS/w["filename"]
   if not p.is_file() or p.stat().st_size!=w["bytes"] or sha(p)!=w["sha256"]:raise RuntimeError("candidate wheel drift: "+w["filename"])
   if w["sha256"] not in req_text:raise RuntimeError("requirements lock omits candidate wheel hash: "+w["filename"])
  d["create_venv"]=cmd([str(HELPER),"-m","venv","--system-site-packages",str(ENV)])
  if d["create_venv"]["returncode"]:raise RuntimeError("venv creation failed")
  py=ENV/"bin/python"
  d["install"]=cmd([str(py),"-m","pip","install","--disable-pip-version-check","--no-index","--find-links",str(WHEELS),"--require-hashes","--ignore-installed","-r",str(REQ)])
  if d["install"]["returncode"]:raise RuntimeError("hash-bound local wheel installation failed")
  d["pip_check"]=cmd([str(py),"-m","pip","check"])
  if d["pip_check"]["returncode"]:raise RuntimeError("pip check failed")
  d["import_smoke"]=cmd([str(py),"-c","import json, torch, transformers, tokenizers, safetensors, huggingface_hub; from transformers import EomtDinov3ForUniversalSegmentation; print(json.dumps({'torch':torch.__version__,'transformers':transformers.__version__,'tokenizers':tokenizers.__version__,'safetensors':safetensors.__version__,'huggingface_hub':huggingface_hub.__version__,'eomt_class_imported':EomtDinov3ForUniversalSegmentation.__name__}))"])
  if d["import_smoke"]["returncode"]:raise RuntimeError("isolated import smoke failed")
  d["status"]="ISOLATED_RUNTIME_CLOSURE_IMPORT_PASS";d["environment"]={"path":str(ENV.relative_to(ROOT)),"python":str(py.relative_to(ROOT)),"python_sha256":sha(py)};d["next_safe_action"]="Create a new immutable 66-class shadow-only model-load/inference binding. This closure pass does not load weights, allocate CUDA, execute GPU work, or authorize provider promotion."
  d["ended_at_utc"]=datetime.now(timezone.utc).isoformat();write(d);print(json.dumps({"status":d["status"],"self_sha256":d["self_sha256"]},sort_keys=True));return 0
 except Exception as e:
  d["status"]="ISOLATED_RUNTIME_CLOSURE_FAIL";d["error"]={"type":type(e).__name__,"message":str(e),"traceback":traceback.format_exc()};d["environment_preserved"]=str(ENV.relative_to(ROOT)) if ENV.exists() else None;d["ended_at_utc"]=datetime.now(timezone.utc).isoformat();write(d);print(json.dumps({"status":d["status"],"self_sha256":d["self_sha256"]},sort_keys=True));raise
if __name__=="__main__":raise SystemExit(main())
