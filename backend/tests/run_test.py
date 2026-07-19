import asyncio
import os
import sys

# Add the backend source root to match the test suite's import layout.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from _pytest.monkeypatch import MonkeyPatch


async def main() -> None:
    from tests.test_monitoring import (
        test_orders_buy_triggers_monitoring_notification,
    )

    mp = MonkeyPatch()
    try:
        await test_orders_buy_triggers_monitoring_notification(mp)
        print("PASS")
    except Exception:
        import traceback

        traceback.print_exc()
    finally:
        mp.undo()


if __name__ == "__main__":
    asyncio.run(main())
