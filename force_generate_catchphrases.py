import asyncio
import os
import sys

# 프로젝트 루트를 패스에 추가
sys.path.append(os.getcwd())

from backend.services.alarm_service import AlarmService

async def main():
    print("🚀 e스포츠 캐치프레이즈 즉시 생성을 시작합니다...")
    try:
        await AlarmService.generate_daily_catchphrases()
        print("✅ 생성이 완료되었습니다! backend/data/esports_catchphrases_v2.json 파일을 확인해보세요.")
    except Exception as e:
        print(f"❌ 오류 발생: {e}")

if __name__ == "__main__":
    asyncio.run(main())
