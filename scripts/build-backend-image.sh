#!/usr/bin/env bash
set -Eeuo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "${script_dir}/.." && pwd)"

base_image="${BACKEND_BASE_IMAGE:-myasset-base:py312-v1}"
backend_image="${BACKEND_IMAGE:-personal-portfolio-backend:latest}"
refresh_base=false

if [[ "${1:-}" == "--refresh-base" ]]; then
  refresh_base=true
  shift
fi

if (( $# > 0 )); then
  echo "Usage: $0 [--refresh-base]" >&2
  exit 2
fi

if [[ "${refresh_base}" == true ]] || ! docker image inspect "${base_image}" >/dev/null 2>&1; then
  echo "Building shared Python base: ${base_image}"
  docker build \
    --file "${repo_root}/backend/Dockerfile.base" \
    --tag "${base_image}" \
    "${repo_root}/backend"
else
  echo "Reusing shared Python base: ${base_image}"
fi

echo "Building backend image: ${backend_image}"
docker build \
  --build-arg "BACKEND_BASE_IMAGE=${base_image}" \
  --file "${repo_root}/backend/Dockerfile" \
  --tag "${backend_image}" \
  "${repo_root}/backend"
