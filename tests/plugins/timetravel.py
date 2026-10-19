"""
Плагин pytest: прогнать весь набор так, будто сегодня другая дата.

Ловит тесты-«мины», которые сломаются, когда пройдёт захардкоженная дата,
и ошибки на границах (31.12, 01.01, 29.02, полночь по Москве):

    pip install time-machine
    TEST_NOW=2027-01-01 pytest -p tests.plugins.timetravel
    TEST_NOW="2027-01-01 00:20 +0300" pytest -p tests.plugins.timetravel

Без TEST_NOW плагин ничего не делает. time-machine нужен только для этой
проверки, поэтому его нет в requirements.txt.
"""

import os

_traveller = None


def pytest_configure(config):
    global _traveller
    target = os.environ.get("TEST_NOW")
    if not target:
        return
    import time_machine

    if ":" not in target:
        target += " 12:00 +0300"
    _traveller = time_machine.travel(target, tick=True)
    _traveller.start()


def pytest_unconfigure(config):
    if _traveller:
        _traveller.stop()
