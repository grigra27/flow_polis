"""PDF квартальной презентации: один альбомный слайд 16:9 на каждый блок.

Верстка получает готовый словарь презентации и не обращается к БД.
Методические примечания остаются в HTML-предпросмотре; в PDF — только
то, без чего слайд читается сам: даты, единицы, легенды, выводы.
Шрифты и загрузчик логотипов — общие с property_pdf.
"""

from io import BytesIO
from pathlib import Path

from django.conf import settings
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.platypus import (
    BaseDocTemplate,
    Flowable,
    Frame,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    PageBreak,
)

from .property_pdf import NAVY, _fonts, label, p
from .quarterly_presentation import HEAT_COLORS

PAGE_SIZE = (960, 540)
MARGIN_X = 40
MARGIN_TOP = 36
MARGIN_BOTTOM = 32
BLACK = colors.HexColor("#111111")
ROW_GRAY = colors.HexColor("#f2f2f2")
TOTAL_GRAY = colors.HexColor("#e4e4e4")
INK = colors.HexColor("#1a1a1a")
MUTED = colors.HexColor("#555555")
TRACK_GRAY = colors.HexColor("#e9eef4")
BAR_COLOR = NAVY
HEAT_FILL = tuple(colors.HexColor(c) for c in HEAT_COLORS)

# Логотип ООО «ОН-ЛАЙН БРОКЕР» — статический ассет без лишних пустых полей;
# пропорции берутся из самого файла. Один размер и отступы на всех страницах.
BRAND_PATH = Path(settings.BASE_DIR) / "static" / "images" / "onlayn-broker.png"
BRAND_WIDTH = 80
# Место в шапке слева от логотипа, чтобы заголовок и дата не заходили под него.
BRAND_HEAD_RESERVE = BRAND_WIDTH + 12

# Внутренние отступы Frame обнулены, поэтому доступная область совпадает
# с полями страницы и расчёт высоты сходится с фактической вёрсткой.
SLIDE_WIDTH = PAGE_SIZE[0] - 2 * MARGIN_X
SLIDE_HEIGHT = PAGE_SIZE[1] - MARGIN_TOP - MARGIN_BOTTOM
NAME_COL_RATIO = 0.42
BAR_COL_RATIO = 0.16
SUM_COL_RATIO = 0.25
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

# Матрица филиал × страховщик: шрифт, отступы, предел строк шапки и названий
# филиалов. До 10 строк филиалов + шапка + «Итого» помещаются на слайд.
# Узкие колонки филиала и итогов отдают ширину страховщикам: «Росгосстрах»
# и «страховщики» должны помещаться в столбец целиком на обычном уровне.
MATRIX_NAME_RATIO = 0.17
MATRIX_TOTAL_RATIO = 0.10
MATRIX_FIT_LEVELS = (
    (10, 4, 3, 2),
    (9.5, 3.5, 3, 2),
    (9, 3, 3, 2),
    (9, 3, 2, 1),
    (8, 2.5, 2, 1),
    (8, 2, 2, 1),
    (7, 1.5, 2, 1),
    (7, 1.2, 1, 1),
)

# Слайд 3: таблица из трёх строк и четырёх блоков месяцев/квартала.
# 11 pt — предел, при котором «брокера,» и «Доля без» ещё целые в колонке.
BROKER_FIT_LEVELS = (
    (11, 6),
    (10, 5),
    (9, 4),
    (8, 3),
    (7, 2),
)
BROKER_LABEL_RATIO = 0.16


def _brand_size():
    img = ImageReader(str(BRAND_PATH))
    image_width, image_height = img.getSize()
    return BRAND_WIDTH, BRAND_WIDTH * image_height / image_width


def _wordmark(canvas, doc):
    canvas.saveState()
    width, height = _brand_size()
    canvas.drawImage(
        str(BRAND_PATH),
        PAGE_SIZE[0] - MARGIN_X - width,
        PAGE_SIZE[1] - MARGIN_TOP - height + 10,
        width=width,
        height=height,
        mask="auto",
        preserveAspectRatio=True,
    )
    canvas.restoreState()


def _clip_word(word, width, size, font):
    if pdfmetrics.stringWidth(word, font, size) <= width:
        return word
    lo, hi, best = 0, len(word), "…"
    while lo <= hi:
        mid = (lo + hi) // 2
        candidate = word[:mid] + "…"
        if pdfmetrics.stringWidth(candidate, font, size) <= width:
            best, lo = candidate, mid + 1
        else:
            hi = mid - 1
    return best


def _fit_name(text, width, size, lines, bold=False):
    """Пакует название по словам; длинные слова и обрезанный хвост — с многоточием."""
    font = "PropertyInterBold" if bold else "PropertyInter"
    words = [_clip_word(word, width, size, font) for word in str(text).split()]
    packed, line = [], ""
    for word in words:
        candidate = f"{line} {word}".strip()
        if pdfmetrics.stringWidth(candidate, font, size) <= width:
            line = candidate
        else:
            packed.append(line)
            line = word
    packed.append(line)
    if len(packed) > lines:
        packed = packed[:lines]
        packed[-1] = _clip_word(packed[-1] + "…", width, size, font)
    return "\n".join(packed)


class _Bar(Flowable):
    """Горизонтальная полоса доли в фиксированной колонке таблицы."""

    def __init__(self, fraction, width, height=8):
        super().__init__()
        self.fraction = max(0.0, min(1.0, float(fraction or 0)))
        self.width = width
        self.height = height

    def wrap(self, availWidth, availHeight):
        return self.width, self.height

    def draw(self):
        canvas = self.canv
        canvas.setFillColor(TRACK_GRAY)
        canvas.roundRect(0, 0, self.width, self.height, 3, stroke=0, fill=1)
        if self.fraction > 0:
            canvas.setFillColor(BAR_COLOR)
            canvas.roundRect(
                0, 0, self.width * self.fraction, self.height, 3, stroke=0, fill=1
            )


def _insurer_stats(slide):
    headline = Table(
        [
            [
                p(slide["portfolio_display"], 20, True, INK),
                p("Страховая сумма портфеля", 10, color=MUTED),
                p(slide["top_share_display"], 20, True, INK),
                p(slide["top_label"], 10, color=MUTED),
            ]
        ],
        colWidths=[
            SLIDE_WIDTH * 0.16,
            SLIDE_WIDTH * 0.20,
            SLIDE_WIDTH * 0.10,
            SLIDE_WIDTH * 0.54,
        ],
        hAlign="LEFT",
    )
    headline.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    return headline


def _insurer_table(slide, width, size, padding, logo_scale, lines):
    name_width = width * NAME_COL_RATIO
    bar_width = width * BAR_COL_RATIO
    sum_width = width * SUM_COL_RATIO
    share_width = width - name_width - bar_width - sum_width
    inner_name_width = name_width - LABEL_INSET - LABEL_IMAGE_COL
    header = [
        p("Страховая компания", size, True, colors.white),
        "",
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
            _Bar(row["bar"], bar_width - 14) if row["key"] else "",
            p(row["sum_display"], size, color=INK, right=True),
            p(row["share_display"], size, color=INK, right=True),
        ]
        for row in slide["rows"]
    ]
    total = [
        p("Итого", size, True, INK),
        "",
        p(slide["total_sum_display"], size, True, INK, right=True),
        p(slide["total_share_display"], size, True, INK, right=True),
    ]
    table = Table(
        [header] + body + [total],
        colWidths=[name_width, bar_width, sum_width, share_width],
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
        p(slide["title"], 22, True, INK, rightIndent=BRAND_HEAD_RESERVE),
        Spacer(1, 6),
        p(
            f'По состоянию на {slide["as_of"]:%d.%m.%Y}',
            12.5,
            color=MUTED,
            rightIndent=BRAND_HEAD_RESERVE,
        ),
        Spacer(1, 16),
    ]


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

    stats = _insurer_stats(slide)
    stats_gap = Spacer(1, 10)
    fixed = sum(f.wrap(SLIDE_WIDTH, 10000)[1] for f in head)
    fixed += stats.wrap(SLIDE_WIDTH, 10000)[1] + stats_gap.wrap(SLIDE_WIDTH, 10000)[1]
    budget = SLIDE_HEIGHT - fixed
    # Измеряем таблицу на той же ширине, на которой она будет отрисована,
    # и берём первый уровень сжатия, целиком помещающийся в остаток страницы.
    for size, padding, logo_scale, lines in FIT_LEVELS:
        table = _insurer_table(slide, SLIDE_WIDTH, size, padding, logo_scale, lines)
        if table.wrap(SLIDE_WIDTH, 10000)[1] <= budget:
            return head + [stats, stats_gap, table]
    # Последний уровень гарантированно помещает 12 строк + шапка + «Итого».
    size, padding, logo_scale, lines = FIT_LEVELS[-1]
    table = _insurer_table(slide, SLIDE_WIDTH, size, padding, logo_scale, lines)
    return head + [stats, stats_gap, table]


def _matrix_table(slide, width, size, padding, header_lines, name_lines):
    columns = slide["columns"]
    column_count = len(columns)
    name_width = width * MATRIX_NAME_RATIO
    total_width = width * MATRIX_TOTAL_RATIO
    column_width = (width - name_width - total_width) / column_count
    header = (
        [p("Филиал", size, True, colors.white)]
        + [
            p(
                _fit_name(
                    col["name"], column_width - 12, size, header_lines, bold=True
                ),
                size,
                True,
                colors.white,
                right=True,
            )
            for col in columns
        ]
        + [p("Итого", size, True, colors.white, right=True)]
    )
    body = []
    for row in slide["rows"]:
        body.append(
            [
                p(
                    _fit_name(row["name"], name_width - 12, size, name_lines),
                    size,
                    color=INK,
                )
            ]
            + [p(cell["display"], size, color=INK, right=True) for cell in row["cells"]]
            + [p(row["total_display"], size, True, INK, right=True)]
        )
    total = (
        [p("Итого", size, True, INK)]
        + [p(col["total_display"], size, True, INK, right=True) for col in columns]
        + [p(slide["total_sum_display"], size, True, INK, right=True)]
    )
    table = Table(
        [header] + body + [total],
        colWidths=[name_width] + [column_width] * column_count + [total_width],
        hAlign="LEFT",
    )
    last = len(body) + 1
    total_column = column_count + 1
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), BLACK),
        ("ROWBACKGROUNDS", (0, 1), (-1, last - 1), [colors.white, ROW_GRAY]),
        ("BACKGROUND", (total_column, 1), (total_column, last - 1), TOTAL_GRAY),
        ("BACKGROUND", (0, last), (-1, last), TOTAL_GRAY),
        ("LINEABOVE", (0, last), (-1, last), 1, BLACK),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), padding),
        ("BOTTOMPADDING", (0, 0), (-1, -1), padding),
    ]
    for row_index, row in enumerate(slide["rows"], 1):
        for cell_index, cell in enumerate(row["cells"], 1):
            if cell["heat"]:
                style.append(
                    (
                        "BACKGROUND",
                        (cell_index, row_index),
                        (cell_index, row_index),
                        HEAT_FILL[cell["heat"] - 1],
                    )
                )
    table.setStyle(TableStyle(style))
    return table


def _matrix_legend(slide):
    cells = [p("млн ₽:", 7.5, color=MUTED)] + [
        p(item["label"], 7.5, True, INK) for item in slide["legend"]
    ]
    widths = [pdfmetrics.stringWidth("млн ₽:", "PropertyInter", 7.5) + 10] + [
        pdfmetrics.stringWidth(item["label"], "PropertyInterBold", 7.5) + 12
        for item in slide["legend"]
    ]
    table = Table([cells], colWidths=widths, hAlign="LEFT")
    style = [
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("BOX", (1, 0), (-1, -1), 0.5, colors.HexColor("#bbbbbb")),
        ("INNERGRID", (1, 0), (-1, -1), 0.5, colors.HexColor("#bbbbbb")),
    ]
    for index, item in enumerate(slide["legend"], 1):
        style.append(
            ("BACKGROUND", (index, 0), (index, 0), colors.HexColor(item["color"]))
        )
    table.setStyle(TableStyle(style))
    return table


def _branch_matrix_slide(slide):
    head = _slide_head(slide)
    if slide["empty"]:
        return head + [
            p(
                "На выбранную дату нет действующих полисов с активным ДФА — "
                "распределение по филиалам и страховщикам пусто.",
                12,
                color=MUTED,
            )
        ]

    legend = _matrix_legend(slide)
    legend_gap = Spacer(1, 6)
    gap = Spacer(1, 10)
    intro = []
    intro_gap = Spacer(1, 8)
    if slide["top_combos"]:
        parts = " и ".join(
            f'{combo["branch"]} × {combo["insurer"]} — {combo["display"]}'
            for combo in slide["top_combos"]
        )
        # Вывод ограничен двумя строками: при длинных названиях филиалов
        # и страховщиков матрица не должна терять уровень сжатия шапки.
        text = _fit_name(f'{slide["top_combos_label"]}: {parts}', SLIDE_WIDTH, 10.5, 2)
        intro = [p(text, 10.5, True, INK), intro_gap]
    fixed = sum(f.wrap(SLIDE_WIDTH, 10000)[1] for f in head)
    fixed += gap.wrap(SLIDE_WIDTH, 10000)[1]
    fixed += legend_gap.wrap(SLIDE_WIDTH, 10000)[1] + legend.wrap(SLIDE_WIDTH, 10000)[1]
    fixed += sum(f.wrap(SLIDE_WIDTH, 10000)[1] for f in intro)
    budget = SLIDE_HEIGHT - fixed
    # «Иные страховщики» — обязательная шапка последней колонки; на уровне
    # с одной строкой заголовка она не должна обрезаться многоточием.
    column_width = (SLIDE_WIDTH * (1 - MATRIX_NAME_RATIO - MATRIX_TOTAL_RATIO)) / len(
        slide["columns"]
    )
    # Таблица измеряется на реальной ширине слайда; первый помещающийся
    # уровень сжатия гарантирует, что матрица, вывод, итоги и легенда на
    # странице.
    for size, padding, header_lines, name_lines in MATRIX_FIT_LEVELS:
        if (
            slide["columns"][-1].get("is_other")
            and header_lines == 1
            and pdfmetrics.stringWidth("Иные страховщики", "PropertyInterBold", size)
            > column_width - 12
        ):
            continue
        table = _matrix_table(
            slide, SLIDE_WIDTH, size, padding, header_lines, name_lines
        )
        if table.wrap(SLIDE_WIDTH, 10000)[1] <= budget:
            return head + intro + [table, legend_gap, legend, gap]
    size, padding, header_lines, name_lines = MATRIX_FIT_LEVELS[-1]
    table = _matrix_table(slide, SLIDE_WIDTH, size, padding, header_lines, name_lines)
    return head + intro + [table, legend_gap, legend, gap]


def _broker_center(text, size, color=colors.white):
    return Paragraph(
        text,
        ParagraphStyle(
            "broker-center",
            fontName="PropertyInterBold",
            fontSize=size,
            leading=size * 1.35,
            textColor=color,
            alignment=TA_CENTER,
        ),
    )


def _broker_table(slide, width, size, padding):
    blocks = slide["months"] + [slide["quarter_block"]]
    label_width = width * BROKER_LABEL_RATIO
    num_width = (width - label_width) / 12
    header = [p("Договоры", size, True, colors.white)]
    subheader = [""]
    for block in blocks:
        # Название блока живёт в первой колонке объединения; остальные пустые,
        # иначе ReportLab рисует только первую ячейку и сдвигает заголовки.
        header.extend([_broker_center(block["name"], size), "", ""])
        subheader.extend(
            p(
                _fit_name(label, num_width - 10, size, 3, bold=True),
                size,
                True,
                colors.white,
                right=True,
            )
            for label in ("Всего, млн ₽", "Без брокера, млн ₽", "Доля без брокера")
        )
    body = []
    for row_index in range(3):
        row = [p(blocks[0]["rows"][row_index]["label"], size, True, INK)]
        for block in blocks:
            cells = block["rows"][row_index]
            bold = block is slide["quarter_block"]
            row.extend(
                [
                    p(cells["total_display"], size, bold, INK, right=True),
                    p(cells["without_display"], size, bold, INK, right=True),
                    p(
                        cells["share_display"],
                        size,
                        bold or cells["share_bold"],
                        INK,
                        right=True,
                    ),
                ]
            )
        body.append(row)
    table = Table(
        [header, subheader] + body,
        colWidths=[label_width] + [num_width] * 12,
        hAlign="LEFT",
    )
    style = [
        ("SPAN", (0, 0), (0, 1)),
        ("BACKGROUND", (0, 0), (-1, 1), BLACK),
        ("ROWBACKGROUNDS", (0, 2), (-1, -1), [colors.white, ROW_GRAY]),
        ("BACKGROUND", (10, 2), (-1, -1), TOTAL_GRAY),
        ("LINEABOVE", (0, 2), (-1, 2), 1, BLACK),
        ("LINEBEFORE", (10, 0), (10, -1), 1, BLACK),
        ("LINEBEFORE", (4, 0), (4, -1), 0.5, colors.HexColor("#bbbbbb")),
        ("LINEBEFORE", (7, 0), (7, -1), 0.5, colors.HexColor("#bbbbbb")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), padding),
        ("BOTTOMPADDING", (0, 0), (-1, -1), padding),
    ]
    for index in range(4):
        style.append(("SPAN", (1 + index * 3, 0), (3 + index * 3, 0)))
    table.setStyle(TableStyle(style))
    return table


def _broker_widest_cell(slide, size):
    """Самая широкая цифра таблицы: колонки уже, чем строка итогов слайда 1."""
    widest = 0.0
    for block in slide["months"] + [slide["quarter_block"]]:
        font = (
            "PropertyInterBold" if block is slide["quarter_block"] else "PropertyInter"
        )
        for row in block["rows"]:
            widest = max(
                widest, pdfmetrics.stringWidth(row["total_display"], font, size)
            )
            widest = max(
                widest, pdfmetrics.stringWidth(row["without_display"], font, size)
            )
            share_font = "PropertyInterBold" if row["share_bold"] else font
            widest = max(
                widest, pdfmetrics.stringWidth(row["share_display"], share_font, size)
            )
    return widest


BROKER_CHART_HEIGHT = 112


class _BrokerChart(Flowable):
    """Три пары столбцов: доля без брокера новых и пролонгаций по месяцам.

    Шкала от нуля; высота столбца — height_pct из данных. Доля без
    знаменателя рисуется прочерком без столбца, реальный ноль — подписью
    «0,00%» без столбца.
    """

    BAR_WIDTH = 56
    BAR_GAP = 14
    PLOT_HEIGHT = 66
    BASELINE_Y = 34
    CHART_DARK = MUTED
    CHART_LIGHT = TOTAL_GRAY

    def __init__(self, chart, width):
        super().__init__()
        self.chart = chart
        self.width = width
        self.height = BROKER_CHART_HEIGHT

    def wrap(self, availWidth, availHeight):
        return self.width, self.height

    def _draw_bar(self, canvas, x, baseline, bar, dark):
        defined = bar["height_pct"] is not None
        height = float(bar["height_pct"]) / 100 * self.PLOT_HEIGHT if defined else 0.0
        if defined and height >= 0.5:
            canvas.setFillColor(self.CHART_DARK if dark else self.CHART_LIGHT)
            canvas.setStrokeColor(MUTED)
            canvas.setLineWidth(0.75)
            canvas.rect(x, baseline, self.BAR_WIDTH, height, stroke=not dark, fill=1)
            label_y = baseline + height + 3
        else:
            label_y = baseline + 3
        canvas.setFillColor(INK)
        canvas.setFont("PropertyInter", 7.5)
        canvas.drawCentredString(x + self.BAR_WIDTH / 2, label_y, bar["display"])

    def draw(self):
        canvas = self.canv
        months = self.chart["months"]
        if not months:
            return
        group_width = self.width / len(months)
        canvas.setStrokeColor(colors.HexColor("#c9d4e0"))
        canvas.setLineWidth(0.75)
        canvas.line(0, self.BASELINE_Y, self.width, self.BASELINE_Y)
        for index, entry in enumerate(months):
            # Пара столбцов симметрична относительно центра месячной группы:
            # внутренний зазор — BAR_GAP, пара целиком — 2 * BAR_WIDTH + BAR_GAP.
            center = group_width * index + group_width / 2
            self._draw_bar(
                canvas,
                center - self.BAR_WIDTH - self.BAR_GAP / 2,
                self.BASELINE_Y,
                entry["new"],
                True,
            )
            self._draw_bar(
                canvas,
                center + self.BAR_GAP / 2,
                self.BASELINE_Y,
                entry["prolong"],
                False,
            )
            canvas.setFillColor(INK)
            canvas.setFont("PropertyInter", 8)
            canvas.drawCentredString(center, 21, entry["name"])
        legend_y = 2
        canvas.setFillColor(self.CHART_DARK)
        canvas.rect(0, legend_y, 9, 9, stroke=0, fill=1)
        canvas.setFillColor(INK)
        canvas.setFont("PropertyInter", 7.5)
        canvas.drawString(13, legend_y + 1.5, "Новые договоры")
        light_x = (
            13 + pdfmetrics.stringWidth("Новые договоры", "PropertyInter", 7.5) + 16
        )
        canvas.setFillColor(self.CHART_LIGHT)
        canvas.rect(light_x, legend_y, 9, 9, stroke=0, fill=1)
        canvas.setStrokeColor(MUTED)
        canvas.setLineWidth(0.75)
        canvas.rect(light_x, legend_y, 9, 9, stroke=1, fill=1)
        canvas.setFillColor(INK)
        canvas.drawString(light_x + 13, legend_y + 1.5, "Пролонгации")


def _broker_head(slide):
    return [
        p(slide["title"], 22, True, INK, rightIndent=BRAND_HEAD_RESERVE),
        Spacer(1, 6),
        p(
            f'{slide["quarter_label"]} · {slide["subtitle"]}',
            12.5,
            color=MUTED,
            rightIndent=BRAND_HEAD_RESERVE,
        ),
        Spacer(1, 14),
    ]


def _broker_headline(slide):
    cells = [
        p(slide["share_display"], 30, True, INK),
        p(slide["share_label"], 9, color=MUTED),
        p(f'СС без брокера, млн ₽: {slide["without_display"]}', 10.5, True, INK),
        p(f'Общая СС, млн ₽: {slide["total_display"]}', 10.5, True, INK),
    ]
    # Доля не должна переноситься на вторую строку: ширина первой колонки
    # подгоняется под самое длинное значение, остальные сжимаются пропорционально.
    share_width = max(
        SLIDE_WIDTH * 0.13,
        pdfmetrics.stringWidth(slide["share_display"], "PropertyInterBold", 30) + 12,
    )
    rest = SLIDE_WIDTH - share_width
    ratios = (0.34, 0.33, 0.33)
    headline = Table(
        [cells],
        colWidths=[share_width] + [rest * ratio / sum(ratios) for ratio in ratios],
        hAlign="LEFT",
    )
    headline.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    return headline


def _broker_slide(slide):
    head = _broker_head(slide)
    gap = Spacer(1, 10)
    if slide["empty"]:
        return head + [
            p("Нет подходящих фактических оплат за квартал", 12, color=MUTED)
        ]
    headline = _broker_headline(slide)
    headline_gap = Spacer(1, 12)
    chart = _BrokerChart(slide["chart"], SLIDE_WIDTH)
    fixed = sum(f.wrap(SLIDE_WIDTH, 10000)[1] for f in head)
    fixed += headline.wrap(SLIDE_WIDTH, 10000)[1]
    fixed += headline_gap.wrap(SLIDE_WIDTH, 10000)[1]
    fixed += gap.wrap(SLIDE_WIDTH, 10000)[1] + chart.wrap(SLIDE_WIDTH, 10000)[1]
    budget = SLIDE_HEIGHT - fixed
    num_width = (SLIDE_WIDTH - SLIDE_WIDTH * BROKER_LABEL_RATIO) / 12
    for size, padding in BROKER_FIT_LEVELS:
        if _broker_widest_cell(slide, size) > num_width - 10:
            continue
        table = _broker_table(slide, SLIDE_WIDTH, size, padding)
        if table.wrap(SLIDE_WIDTH, 10000)[1] <= budget:
            return head + [headline, headline_gap, table, gap, chart]
    size, padding = BROKER_FIT_LEVELS[-1]
    table = _broker_table(slide, SLIDE_WIDTH, size, padding)
    return head + [headline, headline_gap, table, gap, chart]


# Слайд 4: две таблицы рядом — филиалы (уже) и лизингополучатели (шире,
# там длиннее названия). Размер, отступы и предел строк названий.
DIST_BRANCH_RATIO = 0.40
DIST_CLIENT_RATIO = 0.58
DIST_BRANCH_NAME_RATIO = 0.56
DIST_BRANCH_SUM_RATIO = 0.26
DIST_CLIENT_NAME_RATIO = 0.72
DIST_CLIENT_SUM_RATIO = 0.16
DIST_FIT_LEVELS = (
    (11, 4, 2),
    (10, 4, 2),
    (9, 3, 2),
    (8, 2.5, 2),
    (7, 2, 1),
)


def _dist_min_num_width():
    """Самая узкая числовая колонка обеих таблиц — граница для цифр."""
    left = SLIDE_WIDTH * DIST_BRANCH_RATIO
    right = SLIDE_WIDTH * DIST_CLIENT_RATIO
    return min(
        left * DIST_BRANCH_SUM_RATIO,
        left * (1 - DIST_BRANCH_NAME_RATIO - DIST_BRANCH_SUM_RATIO),
        right * DIST_CLIENT_SUM_RATIO,
        right * (1 - DIST_CLIENT_NAME_RATIO - DIST_CLIENT_SUM_RATIO),
    )


def _dist_widest_cell(slide, size):
    widest = 0.0
    for block in slide["tables"]:
        for row in block["rows"]:
            for key in ("sum_display", "share_display"):
                widest = max(
                    widest,
                    pdfmetrics.stringWidth(row[key], "PropertyInter", size),
                )
        for key in ("sum_display", "share_display"):
            widest = max(
                widest,
                pdfmetrics.stringWidth(block["total"][key], "PropertyInterBold", size),
            )
    return widest


def _dist_table(block, width, size, padding, name_lines, name_ratio, sum_ratio):
    name_width = width * name_ratio
    sum_width = width * sum_ratio
    share_width = width - name_width - sum_width
    header = [_broker_center(block["name"], size), "", ""]
    subheader = [
        p("Название", size, True, colors.white),
        p("СС, млн ₽", size, True, colors.white, right=True),
        p("Доля", size, True, colors.white, right=True),
    ]
    body = [
        [
            p(
                _fit_name(row["name"], name_width - 12, size, name_lines),
                size,
                color=INK,
            ),
            p(row["sum_display"], size, color=INK, right=True),
            p(row["share_display"], size, color=INK, right=True),
        ]
        for row in block["rows"]
    ]
    total = block["total"]
    total_row = [
        p(total["name"], size, True, INK),
        p(total["sum_display"], size, True, INK, right=True),
        p(total["share_display"], size, True, INK, right=True),
    ]
    table = Table(
        [header, subheader] + body + [total_row],
        colWidths=[name_width, sum_width, share_width],
        hAlign="LEFT",
    )
    last = len(body) + 2
    table.setStyle(
        TableStyle(
            [
                ("SPAN", (0, 0), (2, 0)),
                ("BACKGROUND", (0, 0), (-1, 1), BLACK),
                ("ROWBACKGROUNDS", (0, 2), (-1, last - 1), [colors.white, ROW_GRAY]),
                ("BACKGROUND", (0, last), (-1, last), TOTAL_GRAY),
                ("LINEABOVE", (0, last), (-1, last), 1, BLACK),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), padding),
                ("BOTTOMPADDING", (0, 0), (-1, -1), padding),
            ]
        )
    )
    return table


def _dist_tables_row(slide, size, padding, name_lines):
    branch_width = SLIDE_WIDTH * DIST_BRANCH_RATIO
    client_width = SLIDE_WIDTH * DIST_CLIENT_RATIO
    left = _dist_table(
        slide["tables"][0],
        branch_width,
        size,
        padding,
        name_lines,
        DIST_BRANCH_NAME_RATIO,
        DIST_BRANCH_SUM_RATIO,
    )
    right = _dist_table(
        slide["tables"][1],
        client_width,
        size,
        padding,
        name_lines,
        DIST_CLIENT_NAME_RATIO,
        DIST_CLIENT_SUM_RATIO,
    )
    tables = Table(
        [[left, "", right]],
        colWidths=[
            branch_width,
            SLIDE_WIDTH - branch_width - client_width,
            client_width,
        ],
        hAlign="LEFT",
    )
    tables.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    return tables


def _distribution_slide(slide):
    head = _broker_head(slide)
    gap = Spacer(1, 10)
    if slide["empty"]:
        return head + [
            p(
                "Нет подходящих фактических оплат без участия брокера " "за квартал",
                12,
                color=MUTED,
            )
        ]
    if slide["no_sums"]:
        return head + [
            p(
                "Оплаты без брокера в квартале есть, но страховая сумма не "
                f"определена ни у одной из {slide['unknown_count']} пар полис–год.",
                12,
                color=MUTED,
            )
        ]
    conclusion = slide["branches_conclusion"]
    # Крупная цифра с единицей не переносится: ширина колонки — по факту.
    sum_width = max(
        SLIDE_WIDTH * 0.24,
        pdfmetrics.stringWidth(slide["sum_display"], "PropertyInterBold", 30) + 12,
    )
    headline = Table(
        [
            [
                p(slide["sum_display"], 30, True, INK),
                p(slide["sum_label"], 11, True, INK),
            ],
            [
                "",
                p(
                    f'{conclusion["names"]} — {conclusion["share_display"]} '
                    "страховой суммы без брокера",
                    10.5,
                    True,
                    INK,
                )
                if conclusion
                else "",
            ],
        ],
        colWidths=[sum_width, SLIDE_WIDTH - sum_width],
        hAlign="LEFT",
    )
    headline.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    headline_gap = Spacer(1, 12)
    fixed = sum(f.wrap(SLIDE_WIDTH, 10000)[1] for f in head)
    fixed += headline.wrap(SLIDE_WIDTH, 10000)[1]
    fixed += headline_gap.wrap(SLIDE_WIDTH, 10000)[1] + gap.wrap(SLIDE_WIDTH, 10000)[1]
    budget = SLIDE_HEIGHT - fixed
    for size, padding, name_lines in DIST_FIT_LEVELS:
        if _dist_widest_cell(slide, size) > _dist_min_num_width() - 10:
            continue
        tables = _dist_tables_row(slide, size, padding, name_lines)
        if tables.wrap(SLIDE_WIDTH, 10000)[1] <= budget:
            return head + [headline, headline_gap, tables]
    size, padding, name_lines = DIST_FIT_LEVELS[-1]
    tables = _dist_tables_row(slide, size, padding, name_lines)
    return head + [headline, headline_gap, tables]


SLIDE_RENDERERS = {
    "insurers": _insurer_slide,
    "branch_matrix": _branch_matrix_slide,
    "broker": _broker_slide,
    "broker_distribution": _distribution_slide,
}


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
