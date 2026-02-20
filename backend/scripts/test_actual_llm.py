import asyncio
import os
import sys

# 프로젝트 루트의 상위 디렉토리를 path에 추가하여 'backend'를 패키지로 인식하게 함
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

async def test_actual_call():
    from backend.core.config import settings
    from backend.services.llm.service import LLMService

    print(f"--- Actual Call Test ---")
    api_key = settings.open_api_key
    print(f"OPEN_API_KEY present: {bool(api_key)}")
    
    if not api_key:
        print("❌ Error: OPEN_API_KEY is missing in environment!")
        return

    llm_service = LLMService.get_instance()
    
    # 7시 브리핑에서 사용하는 것과 동일한 설정으로 호출
    print("\nCalling OpenRouter (openai/gpt-5.1-chat)...")
    try:
        response = await llm_service.generate_paid_chat(
            messages=[{"role": "user", "content": "안녕? 너는 누구니? 아주 짧게 한 문장으로 대답해줘."}],
            model="openai/gpt-5.1-chat",
            api_key=api_key,
            base_url="https://openrouter.ai/api/v1",
            max_tokens=50
        )
        print(f"\n--- Response from GPT-5.1 ---")
        print(response)
        print("\n--- End of Response ---")
        
        if response:
            print("✅ Success: Actual API response received!")
        else:
            print("❌ Failure: Response is empty.")
            print(f"Last Error: {llm_service.get_last_error()}")
            
    except Exception as e:
        print(f"❌ Exception during API call: {e}")

if __name__ == "__main__":
    asyncio.run(test_actual_call())
