import sys, asyncio
sys.stdout.reconfigure(encoding='utf-8')
from datetime import datetime
from pathlib import Path

# Mock minimo do pipeline - goal so usa pipeline.memory e nada mais do real
class MockPipeline:
    class _MockMemory:
        _db = None
    memory = _MockMemory()
    cascade_adapter = None
    vlm_client = None
    web_searcher = None

from src.skills.promptograph.goal import PromptographDailyReportGoal

async def main():
    g = PromptographDailyReportGoal(MockPipeline)
    print(f"Goal name: {g.name}")
    print(f"Interval (s): {g.interval_seconds}")
    print(f"Channels: {g.channels}")
    print(f"Budget: {g.budget.max_daily_usd}")
    print()
    print("=== Relatorio completo ===")
    report = await g._build_report(datetime.now())
    print(report)

asyncio.run(main())
