#!/usr/bin/env bash
set -uo pipefail
ROOT='/workspace/maskfactory/runtime_artifacts/p4_groundingdino_cpu_reference_provider_shard0001_v2_full_closure_20260725T232446Z'
cd /workspace/maskfactory
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH='/workspace/source/GroundingDINO':'/workspace/maskfactory/runtime_artifacts/groundingdino_runtime_closure_v4_20260725T220957Z/site-packages'
set +e
.train_cu128_ada/bin/python tools/run_groundingdino_wsl.py --checkpoint models/gdino/groundingdino_swint_ogc.pth --nude-shard '/workspace/assets/MaskedWarehouse/Nude/_MASKFACTORY_INTAKE/batch_shards/runpod/reference_and_tournament_input.0001.json' --prompts-json '["person"]' --box-threshold 0.4 --text-threshold 0.25 --device cpu --checkpoint-path models/gdino/groundingdino_swint_ogc.pth > "$ROOT/groundingdino_report.json" 2> "$ROOT/groundingdino.stderr.log"
rc=$?
set -e
python3 - "$ROOT" "$rc" <<'PY2'
import hashlib,json,os,sys
root,rc=sys.argv[1],int(sys.argv[2])
sha=lambda p: hashlib.sha256(open(p,'rb').read()).hexdigest() if os.path.isfile(p) else None
def cself(d):
 q=dict(d); q.pop('self_sha256',None); return hashlib.sha256(json.dumps(q,sort_keys=True,separators=(',',':')).encode()).hexdigest()
b=json.load(open(os.path.join(root,'launch_binding.json')))
r={'schema_version':'maskfactory.p4_groundingdino_cpu_provider_receipt.v1','state':'completed' if rc==0 else 'failed','exit_code':rc,'authority_ceiling':'proposal_boxes_only','binding_self_sha256':b['self_sha256'],'report_sha256':sha(os.path.join(root,'groundingdino_report.json')),'stderr_sha256':sha(os.path.join(root,'groundingdino.stderr.log')),'claims':b['claims']}
r['self_sha256']=cself(r)
with open(os.path.join(root,'PROVIDER_RECEIPT.json'),'w') as f: json.dump(r,f,sort_keys=True,indent=2); f.write('\n')
PY2
exit "$rc"
