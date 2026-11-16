"""PDF квартальной презентации: один альбомный слайд 16:9 на каждый блок.

Верстка получает готовый словарь презентации и не обращается к БД.
Шрифты и загрузчик логотипов — общие с property_pdf.
"""

from io import BytesIO

from reportlab.lib import colors
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    PageTemplate,
    Spacer,
    Table,
    TableStyle,
    PageBreak,
)

from .property_pdf import _fonts, label, p

PAGE_SIZE = (960, 540)
MARGIN_X = 40
MARGIN_TOP = 36
MARGIN_BOTTOM = 32
BLACK = colors.HexColor("#111111")
ROW_GRAY = colors.HexColor("#f2f2f2")
TOTAL_GRAY = colors.HexColor("#e4e4e4")
INK = colors.HexColor("#1a1a1a")
MUTED = colors.HexColor("#555555")

# Внутренние отступы Frame обнулены, поэтому доступная область совпадает
# с полями страницы и расчёт высоты сходится с фактической вёрсткой.
SLIDE_WIDTH = PAGE_SIZE[0] - 2 * MARGIN_X
SLIDE_HEIGHT = PAGE_SIZE[1] - MARGIN_TOP - MARGIN_BOTTOM
NAME_COL_RATIO = 0.52
SUM_COL_RATIO = 0.31
LABEL_IMAGE_COL = 23
LABEL_INSET = 14

# Уровни сжатия: шрифт, вертикальные отступы, масштаб логотипа и предел
# строк названия. Первый помещающийся уровень сохраняет обычный вид.
FIT_LEVELS = (
    (11, 4, 1.8, 4),
    (10, 3.5, 1.8, 4),
    (10, 3.5, 1.6, 3),
    (9, 3, 1.6, 3),
    (9, 3, 1.4, 2),
    (8, 2.5, 1.4, 2),
    (8, 2.5, 1.2, 1),
    (7, 2, 1.2, 1),
    (7, 1.5, 1.0, 1),
)


def _wordmark(canvas, doc):
    canvas.saveState()
    canvas.setFont("PropertyInterBold", 13)
    canvas.setFillColor(BLACK)
    canvas.drawRightString(
        PAGE_SIZE[0] - MARGIN_X, PAGE_SIZE[1] - MARGIN_TOP + 2, "флоу//полисы"
    )
    canvas.restoreState()


def _fit_name(text, width, size, lines):
    """Обрезает отображаемое название до заданного числа строк с многоточием."""
    leading = size * 1.35
    limit = lines * leading + 0.1
    if p(text, size, color=INK).wrap(width, 10000)[1] <= limit:
        return text
    words = str(text).split()
    lo, hi, best = 0, len(words), "…"
    while lo <= hi:
        mid = (lo + hi) // 2
        candidate = " ".join(words[:mid]).rstrip() + "…"
        if p(candidate, size, color=INK).wrap(width, 10000)[1] <= limit:
            best, lo = candidate, mid + 1
        else:
            hi = mid - 1
    return best


def _insurer_table(slide, width, size, padding, logo_scale, lines):
    name_width = width * NAME_COL_RATIO
    sum_width = width * SUM_COL_RATIO
    share_width = width - name_width - sum_width
    inner_name_width = name_width - LABEL_INSET - LABEL_IMAGE_COL
    header = [
        p("Страховая компания", size, True, colors.white),
        p("Страховая сумма, ₽", size, True, colors.white, right=True),
        p("Доля", size, True, colors.white, right=True),
    ]
    body = [
        [
            label(
                {**row, "name": _fit_name(row["name"], inner_name_width, size, lines)},
                name_width - LABEL_INSET,
                color=INK,
                size=size,
                image_size=size * logo_scale,
            ),
            p(row["sum_display"], size, color=INK, right=True),
            p(row["share_display"], size, color=INK, right=True),
        ]
        for row in slide["rows"]
    ]
    total = [
        p("Итого", size, True, INK),
        p(slide["total_sum_display"], size, True, INK, right=True),
        p(slide["total_share_display"], size, True, INK, right=True),
    ]
    table = Table(
        [header] + body + [total],
        colWidths=[name_width, sum_width, share_width],
        hAlign="LEFT",
    )
    last = len(body) + 1
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), BLACK),
                ("ROWBACKGROUNDS", (0, 1), (-1, last - 1), [colors.white, ROW_GRAY]),
                ("BACKGROUND", (0, last), (-1, last), TOTAL_GRAY),
                ("LINEABOVE", (0, last), (-1, last), 1, BLACK),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), padding),
                ("BOTTOMPADDING", (0, 0), (-1, -1), padding),
            ]
        )
    )
    return table


def _slide_head(slide):
    return [
        p(slide["title"], 22, True, INK),
        Spacer(1, 6),
        p(f'По состоянию на {slide["as_of"]:%d.%m.%Y}', 12.5, color=MUTED),
        Spacer(1, 16),
    ]


def _slide_note(slide):
    notes = []
    if slide["other_count"]:
        notes.append(
            f'«Иные» — {slide["other_count"]} страховщиков с меньшей страховой суммой.'
        )
    notes.append(
        "Страховая сумма текущего страхового года действующих полисов с активным "
        "ДФА; без ОСАГО и лимитов ответственности."
    )
    return p(" ".join(notes), 8.5, color=MUTED)


def _insurer_slide(slide):
    head = _slide_head(slide)
    if slide["empty"]:
        return head + [
            p(
                "На выбранную дату нет действующих полисов с активным ДФА — "
                "распределение по страховщикам пусто.",
                12,
                color=MUTED,
            )
        ]

    note = _slide_note(slide)
    gap = Spacer(1, 10)
    fixed = sum(f.wrap(SLIDE_WIDTH, 10000)[1] for f in head)
    fixed += gap.wrap(SLIDE_WIDTH, 10000)[1] + note.wrap(SLIDE_WIDTH, 10000)[1]
    budget = SLIDE_HEIGHT - fixed
    # Измеряем таблицу на той же ширине, на которой она будет отрисована,
    # и берём первый уровень сжатия, целиком помещающийся в остаток страницы.
    for size, padding, logo_scale, lines in FIT_LEVELS:
        table = _insurer_table(slide, SLIDE_WIDTH, size, padding, logo_scale, lines)
        if table.wrap(SLIDE_WIDTH, 10000)[1] <= budget:
            return head + [table, gap, note]
    # Последний уровень гарантированно помещает 12 строк + шапку + «Итого».
    size, padding, logo_scale, lines = FIT_LEVELS[-1]
    table = _insurer_table(slide, SLIDE_WIDTH, size, padding, logo_scale, lines)
    return head + [table, gap, note]


SLIDE_RENDERERS = {"insurers": _insurer_slide}


def build_quarterly_pdf(presentation):
    _fonts()
    output = BytesIO()
    doc = BaseDocTemplate(
        output,
        pagesize=PAGE_SIZE,
        leftMargin=MARGIN_X,
        rightMargin=MARGIN_X,
        topMargin=MARGIN_TOP,
        bottomMargin=MARGIN_BOTTOM,
        title=f'Квартальная презентация — {presentation["quarter_label"]}',
        author="InsFlow",
    )
    frame = Frame(
        MARGIN_X,
        MARGIN_BOTTOM,
        SLIDE_WIDTH,
        SLIDE_HEIGHT,
        id="slide",
        leftPadding=0,
        rightPadding=0,
        topPadding=0,
        bottomPadding=0,
    )
    doc.addPageTemplates(PageTemplate(id="slide", frames=[frame], onPage=_wordmark))
    story = []
    for index, slide in enumerate(presentation["slides"]):
        if index:
            story.append(PageBreak())
        story.extend(SLIDE_RENDERERS[slide["kind"]](slide))
    doc.build(story)
    return output.getvalue()
