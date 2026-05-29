# Base stage with pre-compiled heavy dependencies. Keeping this in the
# Dockerfile lets CI build from a clean runner without a local base image.
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install build dependencies + backup utilities
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libstdc++6 \
    curl \
    ca-certificates \
    sqlite3 \
    zip \
    && rm -rf /var/lib/apt/lists/*

# Pre-install heavy/compiled dependencies (cached in the base stage)
RUN pip install --no-cache-dir \
    pandas==2.3.1 \
    scikit-learn \
    llama-cpp-python==0.3.16 \
    sentence-transformers==2.2.2 \
    faiss-cpu

FROM base

# Install runtime utilities. xpu-smi is used to check Intel GPU VRAM before upscaling.
RUN printf 'deb [trusted=yes] https://ppa.launchpadcontent.net/kobuk-team/intel-graphics/ubuntu noble main\n' \
    > /etc/apt/sources.list.d/kobuk-intel-graphics.list \
    && apt-get update && apt-get install -y --no-install-recommends \
    iputils-ping \
    libgomp1 \
    libvulkan1 \
    mesa-vulkan-drivers \
    sqlite3 \
    xpu-smi \
    zip \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install the rest of the light dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the backend code into /app/backend to maintain project structure
COPY . ./backend/

# Ensure necessary directories exist
RUN mkdir -p backend/storage/db backend/data/

# Default command (will be overridden in docker-compose)
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
