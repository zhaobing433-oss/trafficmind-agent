"""Workflow 运行时异常。"""

from __future__ import annotations


class DriverLeaseLost(Exception):
    """driver lease 丢失（stale worker）。

    RunDriver 执行期间，当前 owner/generation 不再持有 lease。
    收到此信号后 executor 必须立即停止：不得写 node terminal / stepsUsed /
    cursor / run status 等任何 control progression。
    """

    def __init__(self, run_id: str = "") -> None:
        self.run_id = run_id
        super().__init__(
            f"driver lease lost for run {run_id}" if run_id else "driver lease lost"
        )
