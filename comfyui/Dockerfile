FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Seoul

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        git \
        libgl1 \
        libglib2.0-0 \
        libgomp1 \
        python3 \
        python3-pip \
        python3-venv \
        software-properties-common \
    && rm -rf /var/lib/apt/lists/*

RUN add-apt-repository -y ppa:kobuk-team/intel-graphics \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        intel-opencl-icd \
        libigdgmm12 \
        libze-intel-gpu1 \
        libze1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt

ARG COMFYUI_REF=master
RUN git clone https://github.com/comfyanonymous/ComfyUI.git \
    && cd ComfyUI \
    && git checkout "${COMFYUI_REF}" \
    && git clone --depth 1 https://github.com/city96/ComfyUI-GGUF.git custom_nodes/ComfyUI-GGUF

WORKDIR /opt/ComfyUI

RUN python3 -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH

RUN python -m pip install --upgrade pip wheel setuptools \
    && python -m pip install --pre torch torchvision torchaudio --index-url https://download.pytorch.org/whl/nightly/xpu \
    && python -m pip install -r requirements.txt \
    && python -m pip install -r custom_nodes/ComfyUI-GGUF/requirements.txt

EXPOSE 8188

CMD ["python", "main.py", "--listen", "0.0.0.0", "--port", "8188"]
