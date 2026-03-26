FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    software-properties-common \
    ca-certificates \
    && add-apt-repository -y ppa:kobuk-team/intel-graphics \
    && rm -rf /var/lib/apt/lists/*

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-venv \
    python3-dev \
    curl \
    ca-certificates \
    libstdc++6 \
    ocl-icd-libopencl1 \
    clinfo \
    intel-opencl-icd \
    libze1 \
    libze-intel-gpu1 \
    && rm -rf /var/lib/apt/lists/*

RUN ln -sf /usr/bin/python3 /usr/bin/python && ln -sf /usr/bin/pip3 /usr/bin/pip

COPY requirements.txt /app/requirements.txt
RUN pip install --break-system-packages --index-url https://download.pytorch.org/whl/xpu \
        torch==2.6.0+xpu torchvision==0.21.0+xpu torchaudio==2.6.0+xpu \
    && pip install --break-system-packages -r /app/requirements.txt

COPY app.py /app/app.py

EXPOSE 8082

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8082"]
