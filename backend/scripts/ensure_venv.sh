#!/bin/bash
# ensure_venv.sh - .venv 존재 확인 및 생성

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(dirname "$SCRIPT_DIR")"
PROJECT_ROOT="$(dirname "$BACKEND_DIR")"
VENV_DIR="$PROJECT_ROOT/venv"

if [ ! -d "$VENV_DIR" ]; then
    echo "🔧 Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
    echo "📦 Installing dependencies..."
    "$VENV_DIR/bin/pip" install -r "$BACKEND_DIR/requirements.txt" --quiet
    echo "✅ Virtual environment ready!"
else
    echo "✅ Virtual environment exists"
fi
