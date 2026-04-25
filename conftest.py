"""
Корневой conftest.py для pytest.

Сейчас пустой — все ранее xfail-помеченные тесты починены (см. PLAN.md, 1.1).
При появлении нового технического долга в тестах добавляйте nodeid в
KNOWN_FAILURES и помечайте через pytest_collection_modifyitems —
шаблон сохраняется в истории git (commit 7b7a750).
"""
