"""
H-19: `_check_memory_usage` учитывает не только RAM, но и swap — итоговый
статус худший из двух; при отсутствии swap проверка swap пропускается.
"""
from collections import namedtuple

import pytest

from apps.core.management.commands.system_health_check import Command

GB = 1024**3
MB = 1024**2

VMem = namedtuple("VMem", "total available used percent")
Swap = namedtuple("Swap", "total used percent")


@pytest.fixture
def memory(monkeypatch):
    def set_memory(ram_percent, swap_percent, swap_total=2048 * MB):
        monkeypatch.setattr(
            "psutil.virtual_memory",
            lambda: VMem(
                2 * GB,
                2 * GB * (100 - ram_percent) / 100,
                2 * GB * ram_percent / 100,
                ram_percent,
            ),
        )
        monkeypatch.setattr(
            "psutil.swap_memory",
            lambda: Swap(swap_total, swap_total * swap_percent / 100, swap_percent),
        )

    return set_memory


@pytest.mark.parametrize(
    "ram, swap, expected",
    [
        (40, 0, "healthy"),
        (40, 30, "healthy"),
        (40, 60, "warning"),
        (40, 85, "critical"),
        (85, 10, "warning"),
        (95, 60, "critical"),
        (85, 85, "critical"),
    ],
)
def test_status_is_worst_of_ram_and_swap(memory, ram, swap, expected):
    memory(ram, swap)

    result = Command()._check_memory_usage()

    assert result["status"] == expected
    assert "swap" in result["details"]


def test_swap_message_when_swap_is_the_problem(memory):
    memory(40, 60)

    result = Command()._check_memory_usage()

    assert result["message"].startswith("Swap usage high")


def test_no_swap_configured_is_ignored(memory):
    memory(40, 0, swap_total=0)

    result = Command()._check_memory_usage()

    assert result["status"] == "healthy"
    assert "swap" not in result["details"]
