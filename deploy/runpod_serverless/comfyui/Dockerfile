FROM runpod/worker-comfyui:5.8.6-base

USER root

RUN rm -rf \
      /comfyui/custom_nodes/was-node-suite-comfyui \
      /comfyui/custom_nodes/comfyui_controlnet_aux \
      /comfyui/custom_nodes/ComfyUI-PuLID-Flux \
    && git clone https://github.com/WASasquatch/was-node-suite-comfyui.git \
      /comfyui/custom_nodes/was-node-suite-comfyui \
    && git -C /comfyui/custom_nodes/was-node-suite-comfyui checkout \
      ea935d1044ae5a26efa54ebeb18fe9020af49a45 \
    && git clone https://github.com/Fannovel16/comfyui_controlnet_aux.git \
      /comfyui/custom_nodes/comfyui_controlnet_aux \
    && git -C /comfyui/custom_nodes/comfyui_controlnet_aux checkout \
      e8b689a513c3e6b63edc44066560ca5919c0576e \
    && git clone https://github.com/balazik/ComfyUI-PuLID-Flux.git \
      /comfyui/custom_nodes/ComfyUI-PuLID-Flux \
    && git -C /comfyui/custom_nodes/ComfyUI-PuLID-Flux checkout \
      a80912fc3435c358607bf4b43a58dbcbebdb09ff \
    && for requirements in /comfyui/custom_nodes/*/requirements.txt; do \
         [ -f "${requirements}" ] && uv pip install -r "${requirements}" || true; \
       done \
    && find /comfyui/custom_nodes -type d -name .git -prune -exec rm -rf {} +

COPY deploy/runpod_serverless/comfyui/extra_model_paths.yaml \
  /comfyui/extra_model_paths.yaml
COPY deploy/runpod_serverless/comfyui/runtime_bindings.json \
  /opt/maskfactory-overflow/runtime_bindings.json

# Import the complete node graph during the remote image build. Model loading is
# intentionally deferred to the worker because model bytes live on the volume.
RUN cd /comfyui && timeout 300 python main.py --quick-test-for-ci --cpu
