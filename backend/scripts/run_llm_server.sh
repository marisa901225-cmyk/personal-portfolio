#!/bin/bash

# EXAONE-4.0-1.2B-GGUF 실행 스크립트 예시 (llama-server)
# 사용법: ./run_llm_server.sh [MODEL_PATH] [PORT]

MODEL_PATH=${1:-"backend/data/EXAONE-4.0-1.2B-BF16.gguf"}
PORT=${2:-8820}
TEMPLATE_FILE="backend/data/chat_template_exaone.jinja"

if [ ! -f "$MODEL_PATH" ]; then
    echo "Error: Model file not found at $MODEL_PATH"
    exit 1
fi

if [ ! -f "$TEMPLATE_FILE" ]; then
    echo "Error: Template file not found at $TEMPLATE_FILE"
    exit 1
fi

echo "Starting llama-server with EXAONE model and official template..."
echo "Model: $MODEL_PATH"
echo "Port: $PORT"
echo "Template: $TEMPLATE_FILE"

# LG 공식 가이드에 따른 실행 방식
llama-server -m "$MODEL_PATH" \
  -c 8192 -fa -ngl 999 \
  --jinja --chat-template-file "$TEMPLATE_FILE" \
  --host 0.0.0.0 --port "$PORT"
