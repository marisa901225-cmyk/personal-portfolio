#!/bin/bash
MODEL_PATH_DEFAULT=${LLM_MODEL_PATH:-/data/EXAONE-4.0-1.2B-BF16.gguf}
MODEL_PATH_FILE=${LLM_MODEL_PATH_FILE:-/data/llm_model_path.txt}
EXAONE_TEMPLATE_PATH=/data/chat_template_exaone.jinja
QWEN3_TEMPLATE_PATH=/data/chat_template_qwen3.jinja
QWEN3VL_TEMPLATE_PATH=/data/chat_template_qwen3vl.jinja
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

# 모델 이름에 따라 chat template 옵션 결정
get_template_args() {
    local model_path="$1"
    local model_name=$(basename "$model_path" | tr '[:upper:]' '[:lower:]')
    
    if [[ "$model_name" == *"exaone"* ]]; then
        # EXAONE 모델: 커스텀 jinja 템플릿 사용
        if [ -f "$EXAONE_TEMPLATE_PATH" ]; then
            echo "--chat-template-file $EXAONE_TEMPLATE_PATH"
        else
            echo "--chat-template exaone4"
        fi
    elif [[ "$model_name" == *"qwen3-vl"* ]] || [[ "$model_name" == *"qwen3vl"* ]]; then
        # Qwen3-VL 모델: 전용 jinja 템플릿 사용
        if [ -f "$QWEN3VL_TEMPLATE_PATH" ]; then
            echo "--chat-template-file $QWEN3VL_TEMPLATE_PATH"
        else
            echo "--chat-template chatml"
        fi
    elif [[ "$model_name" == *"qwen3"* ]]; then
        # Qwen3 모델: 커스텀 jinja 템플릿 사용 (CoT 제어 지원)
        # 내장된 Hermes 템플릿 오토감지를 막기 위해 chatml을 명시적으로 함께 지정 시도
        if [ -f "$QWEN3_TEMPLATE_PATH" ]; then
            echo "--chat-template chatml --chat-template-file $QWEN3_TEMPLATE_PATH"
        else
            echo "--chat-template chatml"
        fi
    elif [[ "$model_name" == *"qwen"* ]]; then
        # 일반 Qwen 모델: chatml 빌트인 템플릿 사용
        echo "--chat-template chatml"
    elif [[ "$model_name" == *"llama"* ]]; then
        # Llama 모델: llama3 템플릿 사용
        echo "--chat-template llama3"
    elif [[ "$model_name" == *"gemma"* ]]; then
        # Gemma 모델: gemma 빌트인 템플릿 사용
        echo "--chat-template gemma"
    elif [[ "$model_name" == *"deepseek"* ]]; then
        # DeepSeek 모델: deepseek 템플릿 사용
        echo "--chat-template deepseek"
    else
        # 기본: chatml (가장 범용적)
        echo "--chat-template chatml"
    fi
}

while true; do
    MODEL_PATH=$(resolve_model_path)
    TEMPLATE_ARGS=$(get_template_args "$MODEL_PATH")
    echo "Starting llama-server with model: $MODEL_PATH"
    echo "Using template args: $TEMPLATE_ARGS"
    /app/llama-server \
        --model "$MODEL_PATH" \
        --host 0.0.0.0 \
        --port 8080 \
        --threads "$THREADS" \
        --ctx-size 4096 \
        --n-gpu-layers 35 \
        --reasoning-budget 0 \
        --flash-attn on \
        --jinja \
        $TEMPLATE_ARGS &

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
