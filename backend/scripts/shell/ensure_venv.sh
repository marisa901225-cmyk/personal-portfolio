#!/bin/bash
set -e

# Base directory (where this script is located: backend/scripts/)
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
BACKEND_DIR="$( dirname "$SCRIPT_DIR" )"
VENV_PATH="$BACKEND_DIR/.venv"

echo "Checking backend virtualenv at $VENV_PATH..."

# 1. Create venv if missing
if [ ! -d "$VENV_PATH" ]; then
    echo "Creating new virtualenv..."
    python3 -m venv "$VENV_PATH"
fi

# 2. Install dependencies
echo "Installing/Updating dependencies from requirements.txt..."
"$VENV_PATH/bin/pip" install --upgrade pip
"$VENV_PATH/bin/pip" install -r "$BACKEND_DIR/requirements.txt"

# 3. Verify pydantic_settings
echo "Verifying pydantic_settings import..."
"$VENV_PATH/bin/python" -c "import pydantic_settings; print('pydantic_settings OK')"

echo "Backend virtualenv is ready."
