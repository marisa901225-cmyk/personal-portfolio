
import asyncio
import sys
import logging
from unittest.mock import MagicMock, patch

# Add backend to path
import os
sys.path.append(os.path.abspath("/home/dlckdgn/personal-portfolio"))

# Mock dependencies to avoid loading heavy modules or connecting to DB
logging.basicConfig(level=logging.INFO)

# Mock llm_service
# Actual path seems to be backend.services.llm.service based on previous logs references
# or maybe backend.llm_service if it was moved?
# Checking file structure...
# Based on llm_logic.py: from ..llm_service import LLMService -> backend.services.llm_service
# But thels command will confirm.
# Let's try mocking the import in llm_logic.py directly since we are testing that file.
with patch("backend.services.alarm.llm_logic.LLMService") as MockLLM:
    instance = MockLLM.get_instance.return_value
    instance.is_loaded.return_value = True
    
    # Import logic
    from backend.services.alarm.llm_logic import summarize_with_llm
    
    async def test_empty_list():
        print("Testing with empty list...")
        result = await summarize_with_llm([])
        print(f"Result for empty list: {result}")
        if result is None:
             print("SUCCESS: Returned None for empty list associated with random message skip logic (if intended) or processed logic.")
        else:
             print("CHECK: Logic varies based on 10-min interval.")

    async def test_filtered_list():
        print("\nTesting with duplicate list (simulated)...")
        # Creating duplicates
        duplicate_item = {"text": "중복 메시지", "sender": "Testing", "app_title": "App"}
        items = [duplicate_item, duplicate_item] # Same content
        
        # We need to make sure the logic actually de-duplicates.
        # The logic in llm_logic.py uses (source, text) to dedupe.
        
        # This test relies on the internal implementation of summarize_with_llm
        result = await summarize_with_llm(items)
        print(f"Result for duplicate list: {result}")
        
    if __name__ == "__main__":
        asyncio.run(test_empty_list())
        asyncio.run(test_filtered_list())
