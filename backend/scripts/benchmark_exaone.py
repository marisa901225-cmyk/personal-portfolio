import os
import sys
import time
import logging
import json

# Add backend to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

try:
    from backend.services.llm_service import LLMService
except ImportError as e:
    print(f"Error importing LLMService: {e}")
    sys.exit(1)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("benchmark_exaone")

def get_memory_usage():
    """Returns RSS memory usage in MiB."""
    with open('/proc/self/status', 'r') as f:
        for line in f:
            if line.startswith('VmRSS:'):
                return int(line.split()[1]) / 1024
    return 0

def benchmark():
    print("🚀 EXAONE 4.0 1.2B Benchmarking Tool")
    print("-" * 40)
    
    # Baseline
    mem_base = get_memory_usage()
    print(f"Baseline Memory: {mem_base:.2f} MiB")
    
    # Load Model
    start_load = time.time()
    llm = LLMService.get_instance()
    end_load = time.time()
    
    if not llm.is_loaded():
        print("❌ Model failed to load.")
        return

    mem_after_load = get_memory_usage()
    print(f"Load Time: {end_load - start_load:.2f}s")
    print(f"Memory after Load: {mem_after_load:.2f} MiB (Diff: {mem_after_load - mem_base:.2f} MiB)")
    print("-" * 40)

    # Inference Test
    messages = [
        {"role": "system", "content": "당신은 시스템 성능 분석 전문가이자 스팀 리포트 생성기입니다."},
        {"role": "user", "content": """현재 작동 중인 당신(EXAONE 4.0 1.2B)의 성능과 호스트 시스템의 원활함을 '스팀 리포트' 스타일로 맛깔나게 리포트해 주세요.
(참고: 본인은 gemma-3가 아닌 EXAONE임을 명시하세요.)

[벤치마크 데이터]
- 모델: EXAONE 4.0 1.2B GGUF
- CPU: Intel N150 (4 Threads)
- RAM: 8GB
- 현재 부하: 매우 쾌적함
"""}
    ]
    
    print("Generating Actual EXAONE Report via generate_chat...")
    start_inf = time.time()
    
    response = llm.generate_chat(
        messages=messages,
        max_tokens=1024, 
        temperature=0.7
    )
    
    end_inf = time.time()
    inf_time = end_inf - start_inf
    
    # Estimate tokens
    # Simple estimation: 1 word ~ 0.75 tokens for Korean, or just characters/4
    token_count = len(response) // 2 # Rough estimate for Korean
    tps = token_count / inf_time if inf_time > 0 else 0

    print("-" * 40)
    print(f"Inference Time: {inf_time:.2f}s")
    print(f"Estimated Throughput: {tps:.2f} tokens/sec")
    print(f"Peak Memory during Benchmark: {get_memory_usage():.2f} MiB")
    print("-" * 40)
    print("\n[EXAONE GENERATED REPORT]\n")
    print(response)
    print("\n" + "-" * 40)

if __name__ == "__main__":
    benchmark()
