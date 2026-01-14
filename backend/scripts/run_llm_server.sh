#!/bin/bash
MODEL_PATH_DEFAULT=${LLM_MODEL_PATH:-/data/EXAONE-4.0-1.2B-BF16.gguf}
MODEL_PATH_FILE=${LLM_MODEL_PATH_FILE:-/data/llm_model_path.txt}
TEMPLATE_PATH=/data/chat_template_exaone.jinja
THREADS=${LLM_THREADS:-4}

resolve_model_path() {
    if [ -f "$MODEL_PATH_FILE" ]; then
        local raw
        raw=$(tr -d '\r\n' < "$MODEL_PATH_FILE")
        if [ -n "$raw" ]; then
            if [[ "$raw" == backend/data/* ]]; then
                echo "/data/$(basename "$raw")"
                return
            fi
            if [[ "$raw" == /app/backend/data/* ]]; then
                echo "/data/$(basename "$raw")"
                return
            fi
            if [[ "$raw" == /* ]]; then
                echo "$raw"
                return
            fi
            echo "/data/$raw"
            return
        fi
    fi
    echo "$MODEL_PATH_DEFAULT"
}

while true; do
    MODEL_PATH=$(resolve_model_path)
    echo "Starting llama-server with model: $MODEL_PATH"
    /app/llama-server \
        --model "$MODEL_PATH" \
        --host 0.0.0.0 \
        --port 8080 \
        --threads "$THREADS" \
        --ctx-size 2048 \
        --reasoning-budget 0 \
        --jinja \
        --chat-template-file "$TEMPLATE_PATH" &

    SERVER_PID=$!

    while kill -0 "$SERVER_PID" 2>/dev/null; do
        NEXT_MODEL_PATH=$(resolve_model_path)
        if [ "$NEXT_MODEL_PATH" != "$MODEL_PATH" ]; then
            echo "Model change detected: $MODEL_PATH -> $NEXT_MODEL_PATH"
            kill "$SERVER_PID"
            wait "$SERVER_PID"
            break
        fi
        sleep 2
    done
done
