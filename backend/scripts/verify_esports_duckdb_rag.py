import asyncio
import logging
import os
import sys

# 프로젝트 루트를 패스에 추가
sys.path.append(os.getcwd())

from backend.services.news_collector import NewsCollector
from backend.services.llm_service import LLMService

async def test_duckdb_rag():
    print("--- E-sports Schedule DuckDB RAG Test ---")
    
    query = "이번달 롤 경기 일정 알려줘"
    print(f"User Query: {query}")
    
    # 1. Retrieval & Refinement (DuckDB)
    context_text = NewsCollector.refine_schedules_with_duckdb(query)
    print(f"Refined Context via DuckDB:\n{context_text}\n")
    
    # 2. Generation
    llm = LLMService.get_instance()
    prompt = f"""<start_of_turn>user
당신은 e스포츠 전문가이자 사용자의 개인 비서입니다. 
사용자의 질문과 아래 제공된 경기 일정 데이터(DuckDB로 정제됨)를 바탕으로 친절하고 명확하게 답변해 주세요.

[제공된 경기 일정 데이터]
{context_text}

[사용자의 질문]
{query}

[답변 규칙]
- 한국어로 답변하세요.
- 데이터에 있는 내용을 기반으로 정확하게 안내하세요.
- 친절하고 위트 있는 말투를 사용하세요.

답변:<end_of_turn>
<start_of_turn>model
"""
    response = llm.generate(prompt, max_tokens=1024)
    print(f"Response:\n{response}")

if __name__ == "__main__":
    asyncio.run(test_duckdb_rag())
