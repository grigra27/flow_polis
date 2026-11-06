"""Pure text helpers shared by notification formatters and transports."""


def trim_with_middle_ellipsis(
    text: str,
    max_length: int,
    marker: str = " ... (truncated) ... ",
    tail_ratio: float = 0.7,
) -> str:
    """Keep the beginning and diagnostic tail when shortening long text."""
    if text is None:
        return ""
    text = str(text)
    if max_length is None or max_length <= 0 or len(text) <= max_length:
        return text
    marker = str(marker)
    if max_length <= len(marker) + 10:
        return text[-max_length:]
    available = max_length - len(marker)
    tail_len = int(available * tail_ratio)
    head_len = available - tail_len
    if head_len < 1:
        head_len = 1
        tail_len = available - head_len
    if tail_len < 1:
        tail_len = 1
        head_len = available - tail_len
    return text[:head_len] + marker + text[-tail_len:]
