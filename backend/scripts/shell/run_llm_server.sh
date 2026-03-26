#!/bin/bash
MODEL_PATH_DEFAULT=${LLM_MODEL_PATH:-/data/EXAONE-4.0-1.2B-BF16.gguf}
MODEL_PATH_FILE=${LLM_MODEL_PATH_FILE:-/data/llm_model_path.txt}
EXAONE_TEMPLATE_PATH=/data/chat_template_exaone.jinja
QWEN3_TEMPLATE_PATH=/data/chat_template_qwen3.jinja
QWEN35_TEMPLATE_PATH=/data/chat_template_qwen3.5-9b-null-space-abliterated.jinja
QWEN3VL_TEMPLATE_PATH=/data/chat_template_qwen3vl.jinja
THREADS=${LLM_THREADS:-6}
N_GPU_LAYERS=${LLM_N_GPU_LAYERS:-37}
USE_MODEL_BUILTIN_TEMPLATE=${LLM_USE_MODEL_BUILTIN_TEMPLATE:-0}
PORT=${LLM_SERVER_PORT:-8080}
CTX_SIZE=${LLM_CTX_SIZE:-8192}
PARALLEL=${LLM_PARALLEL:-1}
DEVICE=${LLM_DEVICE:-}
EXTRA_ARGS=${LLM_EXTRA_ARGS:-}

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
    elif [[ "$model_name" == *"qwen3.5"* ]]; then
        # Qwen3.5 null-space 계열: 전용 jinja 템플릿 우선
        if [[ "$USE_MODEL_BUILTIN_TEMPLATE" == "1" ]]; then
            # 모델 GGUF 내부 tokenizer.chat_template 사용
            echo ""
        elif [ -f "$QWEN35_TEMPLATE_PATH" ]; then
            echo "--chat-template chatml --chat-template-file $QWEN35_TEMPLATE_PATH"
        elif [ -f "$QWEN3_TEMPLATE_PATH" ]; then
            echo "--chat-template chatml --chat-template-file $QWEN3_TEMPLATE_PATH"
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
    DEVICE_ARGS=""
    if [ -n "$DEVICE" ]; then
        DEVICE_ARGS="--device $DEVICE"
    fi
    echo "Starting llama-server with model: $MODEL_PATH"
    echo "Using template args: $TEMPLATE_ARGS"
    echo "Using n-gpu-layers: $N_GPU_LAYERS"
    if [ -n "$DEVICE_ARGS" ]; then
        echo "Using device args: $DEVICE_ARGS"
    fi
    /app/llama-server \
        --model "$MODEL_PATH" \
        --host 0.0.0.0 \
        --port "$PORT" \
        --threads "$THREADS" \
        --ctx-size "$CTX_SIZE" \
        --n-gpu-layers "$N_GPU_LAYERS" \
        --parallel "$PARALLEL" \
        --reasoning-budget 0 \
        --flash-attn off \
        --no-mmap \
        --jinja \
        $DEVICE_ARGS \
        $EXTRA_ARGS \
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
