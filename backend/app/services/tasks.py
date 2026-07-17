"""通用异步任务管理（内存版，Hackathon 够用）。

慢操作（出题、评分、多 agent 流水线）在后台线程执行，
前端通过 task_id 轮询结果，避免 HTTP 长连接被中间层超时切断。
"""
from __future__ import annotations

import threading
import traceback
import uuid
from typing import Any, Callable

# task_id -> {"status": "pending"|"running"|"done"|"error", "result": ..., "error": ...}
_tasks: dict[str, dict[str, Any]] = {}
_lock = threading.Lock()


def _new_id() -> str:
    return uuid.uuid4().hex[:16]


def create_task(fn: Callable[[], Any]) -> str:
    """提交一个后台任务，立即返回 task_id。"""
    task_id = _new_id()
    with _lock:
        _tasks[task_id] = {"status": "pending", "result": None, "error": None}

    def _run():
        with _lock:
            _tasks[task_id]["status"] = "running"
        try:
            result = fn()
            with _lock:
                _tasks[task_id]["status"] = "done"
                _tasks[task_id]["result"] = result
        except Exception as e:  # noqa: BLE001
            tb = traceback.format_exc()
            with _lock:
                _tasks[task_id]["status"] = "error"
                _tasks[task_id]["error"] = f"{e}"
            print(f"[task {task_id}] failed:\n{tb}")

    threading.Thread(target=_run, daemon=True).start()
    return task_id


def get_task(task_id: str) -> dict[str, Any] | None:
    with _lock:
        t = _tasks.get(task_id)
        return dict(t) if t else None


def cleanup_task(task_id: str) -> None:
    """结果取走后清理，避免内存泄漏。"""
    with _lock:
        _tasks.pop(task_id, None)
