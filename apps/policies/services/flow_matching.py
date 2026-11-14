"""Подсказки по ДФА; исходный номер и строгая нормализация не меняются."""
import re

from .flow_import import normalize_dfa


def numeric_parts(value):
    text = normalize_dfa(value)
    text = re.sub(r"^[A-ZА-ЯЁ]+\s*[-/]?\s*", "", text)
    if not re.fullmatch(r"[0-9]+(?:\s*[-/]\s*[0-9]+)*", text):
        return ()
    return tuple(re.findall(r"[0-9]+", text))


def dfa_match(left, right):
    a, b = normalize_dfa(left), normalize_dfa(right)
    if a and a == b:
        return "exact"
    first, second = numeric_parts(left), numeric_parts(right)
    if first and first == second:
        return "structure"
    if (
        first
        and second
        and first[0] == second[0]
        and (len(first) == 1 or len(second) == 1)
    ):
        return "base"
    return ""
