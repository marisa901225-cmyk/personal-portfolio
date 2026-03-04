import asyncio
from unittest.mock import MagicMock, patch
import logging

# 로깅 설정
logging.basicConfig(level=logging.INFO)

async def test_signature():
    print("Testing generate_with_main_llm_async signature...")
    
    # 의존성 모킹
    with patch("backend.services.llm_service.LLMService") as mock_service:
        from backend.services.alarm.llm_refiner import generate_with_main_llm_async
        
        mock_instance = mock_service.get_instance.return_value
        mock_instance.is_loaded.return_value = True
        mock_instance.generate_chat.return_value = "Success"
        
        # model 인자를 포함하여 호출
        try:
            result = await generate_with_main_llm_async(
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=10,
                model="test-model"
            )
            print(f"Result: {result}")
            
            # generate_chat 호출 시 model이 전달되었는지 확인
            args, kwargs = mock_instance.generate_chat.call_args
            print(f"Called with kwargs: {kwargs}")
            
            if kwargs.get("model") == "test-model":
                print("✅ Signature test passed! 'model' argument handled correctly.")
            else:
                print("❌ Signature test failed! 'model' argument not found in kwargs.")
                
        except TypeError as e:
            print(f"❌ Signature test failed with TypeError: {e}")
        except Exception as e:
            print(f"❌ Unexpected error: {e}")

if __name__ == "__main__":
    # 이 스크립트는 backend 디렉토리의 상위 디렉토리에서 PYTHONPATH=. 으로 실행해야 함
    asyncio.run(test_signature())
