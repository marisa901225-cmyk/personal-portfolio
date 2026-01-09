# Use Python 3.12 slim image
FROM python:3.12-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set work directory
WORKDIR /app

# 1. Install system dependencies for building packages (e.g. llama-cpp-python)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libstdc++6 \
    && rm -rf /var/lib/apt/lists/*

# 2. Install heavy/compiled dependencies first to cache them separately
# This prevents re-compiling everything when a minor requirement changes
RUN pip install --no-cache-dir \
    pandas==2.3.1 \
    scikit-learn \
    llama-cpp-python

# 3. Install runtime utilities (adding tools here won't trigger re-build of heavy layers)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install the rest of the light dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the backend code into /app/backend to maintain project structure
COPY . ./backend/

# Ensure necessary directories exist
RUN mkdir -p backend/storage/db backend/data/

# Default command (will be overridden in docker-compose)
# Using backend.main:app and running from /app allows relative imports to work
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
