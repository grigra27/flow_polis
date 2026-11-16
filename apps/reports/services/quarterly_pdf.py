"""PDF квартальной презентации: один альбомный слайд 16:9 на каждый блок.

Верстка получает готовый словарь презентации и не обращается к БД.
Шрифты и загрузчик логотипов — общие с property_pdf.
"""

from io import BytesIO

from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate,
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


def _wordmark(canvas, doc):
    canvas.saveState()
    canvas.setFont("PropertyInterBold", 13)
    canvas.setFillColor(BLACK)
    canvas.drawRightString(
        PAGE_SIZE[0] - MARGIN_X, PAGE_SIZE[1] - MARGIN_TOP + 2, "флоу//полисы"
    )
    canvas.restoreState()


def _insurer_table(slide, width, size, padding):
    name_width = width * 0.52
    sum_width = width * 0.31
    share_width = width - name_width - sum_width
    header = [
        p("Страховая компания", size, True, colors.white),
        p("Страховая сумма, ₽", size, True, colors.white, right=True),
        p("Доля", size, True, colors.white, right=True),
    ]
    body = [
        [
            label(
                row,
                name_width - 14,
                color=INK,
                size=size,
                image_size=size * 1.8,
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


def _insurer_slide(slide):
    width = PAGE_SIZE[0] - 2 * MARGIN_X
    story = [
        p(slide["title"], 22, True, INK),
        Spacer(1, 6),
        p(f'По состоянию на {slide["as_of"]:%d.%m.%Y}', 12.5, color=MUTED),
        Spacer(1, 16),
    ]
    if slide["empty"]:
        story.append(
            p(
                "На выбранную дату нет действующих полисов с активным ДФА — "
                "распределение по страховщикам пусто.",
                12,
                color=MUTED,
            )
        )
        return story

    notes = []
    if slide["other_count"]:
        notes.append(
            f'«Иные» — {slide["other_count"]} страховщиков с меньшей страховой суммой.'
        )
    notes.append(
        "Страховая сумма текущего страхового года действующих полисов с активным "
        "ДФА; без ОСАГО и лимитов ответственности."
    )
    note = p(" ".join(notes), 8.5, color=MUTED)
    # Шапка и примечание фиксированы; таблице отдаём остаток страницы.
    head_height = sum(f.wrap(width, 10000)[1] for f in story)
    note_height = note.wrap(width, 10000)[1] + 10
    budget = PAGE_SIZE[1] - MARGIN_TOP - MARGIN_BOTTOM - head_height - note_height
    # Длинные названия переносятся; размер снижаем, пока все 12 строк
    # не поместятся на одном слайде.
    for size, padding in ((11, 4), (10, 3.5), (9, 3), (8, 2.5), (7, 2)):
        table = _insurer_table(slide, width, size, padding)
        if table.wrap(width, 10000)[1] <= budget:
            break
    story.append(table)
    story.append(Spacer(1, 10))
    story.append(note)
    return story


SLIDE_RENDERERS = {"insurers": _insurer_slide}


def build_quarterly_pdf(presentation):
    _fonts()
    output = BytesIO()
    doc = SimpleDocTemplate(
        output,
        pagesize=PAGE_SIZE,
        leftMargin=MARGIN_X,
        rightMargin=MARGIN_X,
        topMargin=MARGIN_TOP,
        bottomMargin=MARGIN_BOTTOM,
        title=f'Квартальная презентация — {presentation["quarter_label"]}',
        author="InsFlow",
    )
    story = []
    for index, slide in enumerate(presentation["slides"]):
        if index:
            story.append(PageBreak())
        story.extend(SLIDE_RENDERERS[slide["kind"]](slide))
    doc.build(story, onFirstPage=_wordmark, onLaterPages=_wordmark)
    return output.getvalue()
