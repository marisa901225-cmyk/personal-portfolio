# Reuse the named heavy Python base built from Dockerfile.base. This keeps
# compiled ML dependencies available even after BuildKit cache pruning.
ARG BACKEND_BASE_IMAGE=myasset-base:py312-v1
FROM ${BACKEND_BASE_IMAGE}

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
