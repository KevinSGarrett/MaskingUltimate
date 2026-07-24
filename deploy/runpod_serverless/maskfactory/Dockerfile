FROM pytorch/pytorch:2.11.0-cuda12.8-cudnn9-runtime@sha256:eee11b3b3872a8c838e35ef48f08b2d5def2080902c7f666831310ca1a0ef2be

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_INPUT=1
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN python -c "import torch; flags=torch._C._cuda_getArchFlags().split(); assert torch.version.cuda.startswith('12.8'), torch.version.cuda; assert 'sm_120' in flags, flags"

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg git libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/maskfactory
COPY pyproject.toml /opt/maskfactory/pyproject.toml
COPY src /opt/maskfactory/src
RUN python -m pip install --upgrade pip \
    && python -m pip install runpod \
    && python -m pip install /opt/maskfactory \
    && python -c "import torch; flags=torch._C._cuda_getArchFlags().split(); assert torch.version.cuda.startswith('12.8'), torch.version.cuda; assert 'sm_120' in flags, flags"

COPY deploy/runpod_serverless/maskfactory/handler.py /handler.py
COPY deploy/runpod_serverless/maskfactory/start.sh /start.sh
RUN chmod 0755 /start.sh

CMD ["/start.sh"]
