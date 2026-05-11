import json
import threading
import time

from diet_bot.json_storage import json_storage_transaction


def test_json_storage_transaction_serializes_read_modify_write(tmp_path) -> None:
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"value": 0}), encoding="utf-8")

    def increment() -> None:
        for _ in range(10):
            with json_storage_transaction(path):
                payload = json.loads(path.read_text(encoding="utf-8"))
                time.sleep(0.001)
                payload["value"] += 1
                path.write_text(json.dumps(payload), encoding="utf-8")

    threads = [threading.Thread(target=increment) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert json.loads(path.read_text(encoding="utf-8")) == {"value": 40}
