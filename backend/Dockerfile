# Use pre-built base image with heavy dependencies
# If base image doesn't exist, build it first:
#   docker build -f Dockerfile.base -t myasset-base:latest .
FROM myasset-base:latest

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set work directory
WORKDIR /app

# Copy requirements and install the rest of the light dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the backend code into /app/backend to maintain project structure
COPY . ./backend/

# Ensure necessary directories exist
RUN mkdir -p backend/storage/db backend/data/

# Default command (will be overridden in docker-compose)
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
