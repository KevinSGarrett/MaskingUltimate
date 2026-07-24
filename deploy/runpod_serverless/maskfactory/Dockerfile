FROM runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_INPUT=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg git libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/maskfactory
COPY pyproject.toml /opt/maskfactory/pyproject.toml
COPY src /opt/maskfactory/src
RUN python -m pip install --upgrade pip \
    && python -m pip install runpod \
    && python -m pip install /opt/maskfactory

COPY deploy/runpod_serverless/maskfactory/handler.py /handler.py
COPY deploy/runpod_serverless/maskfactory/start.sh /start.sh
RUN chmod 0755 /start.sh

CMD ["/start.sh"]
