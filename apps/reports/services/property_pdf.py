"""Постраничный A4-отчёт: восемь основных страниц и полные приложения.

Генератор получает готовый словарь отчёта и не обращается к БД или сети.
"""
from io import BytesIO
from pathlib import Path
from threading import Lock
from urllib.parse import unquote, urlsplit
from xml.sax.saxutils import escape
from decimal import Decimal

from django.conf import settings
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    PageTemplate,
    Frame,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    LongTable,
    PageBreak,
    NextPageTemplate,
    Image,
    KeepTogether,
    Flowable,
)

NAVY = colors.HexColor("#203b5e")
INK = colors.HexColor("#24384f")
MUTED = colors.HexColor("#5d7188")
LINE = colors.HexColor("#dce4ed")
SOFT = colors.HexColor("#f1f5f9")
BLUE = colors.HexColor("#4977a4")
MARGIN = 17 * mm
FONT_LOCK = Lock()


def _fonts():
    with FONT_LOCK:
        if "PropertyInter" not in pdfmetrics.getRegisteredFontNames():
            root = Path(settings.BASE_DIR) / "static/fonts/inter"
            pdfmetrics.registerFont(
                TTFont("PropertyInter", str(root / "inter-regular.ttf"))
            )
            pdfmetrics.registerFont(
                TTFont("PropertyInterBold", str(root / "inter-semibold.ttf"))
            )
            pdfmetrics.registerFontFamily(
                "PropertyInter", normal="PropertyInter", bold="PropertyInterBold"
            )


def number(value, places=1):
    if value is None:
        return "Не определена"
    return f"{Decimal(value):,.{places}f}".replace(",", " ").replace(".", ",")


def million(value):
    return number(Decimal(value) / 1_000_000)


def p(value, size=9.2, bold=False, color=INK, right=False, rightIndent=0):
    # Описания и названия из базы всегда проходят XML-экранирование.
    value = "".join(
        ch
        for ch in str(value if value is not None else "")
        if ch.isprintable() or ch in "\n\t"
    )
    return Paragraph(
        escape(value).replace("\n", "<br/>"),
        ParagraphStyle(
            "property",
            fontName="PropertyInterBold" if bold else "PropertyInter",
            fontSize=size,
            leading=size * 1.35,
            textColor=color,
            alignment=TA_RIGHT if right else 0,
            rightIndent=rightIndent,
            spaceAfter=0,
            splitLongWords=True,
        ),
    )


def heading(value, size=14):
    result = p(value, size, True, NAVY)
    if size >= 19:
        result.pdf_section = value
    return result


def note(value):
    return p(value, 8.5, color=MUTED)


def logo(url, size=18):
    """Только локальные изображения справочников внутри MEDIA_ROOT."""
    try:
        parts = urlsplit(url or "")
        if parts.scheme or parts.netloc:
            return None
        root = Path(settings.MEDIA_ROOT).resolve()
        media_prefix = "/" + settings.MEDIA_URL.strip("/") + "/"
        if not parts.path.startswith(media_prefix):
            return None
        relative = Path(unquote(parts.path[len(media_prefix) :]))
        if not relative.parts or relative.parts[0] not in {
            "branch_logos",
            "insurer_logos",
            "insurance_type_icons",
        }:
            return None
        path = (root / relative).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            return None
        from PIL import Image as PILImage

        with PILImage.open(path) as source:
            width, height = source.size
            if not width or not height:
                return None
        ratio = min(size / width, size / height)
        return Image(str(path), width=width * ratio, height=height * ratio)
    except (OSError, ValueError):
        return None


def label(row, width, color=INK, size=9.2, image_size=18):
    name = p(row["name"], size, color=color)
    image = logo(row.get("image_url"), size=image_size)
    if image is None:
        return name
    t = Table([[image, name]], colWidths=[23, width - 23])
    t.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    return t


class ReportTable(LongTable):
    def split(self, availWidth, availHeight):
        self._calc(availWidth, availHeight)
        # Не оставляем повторённую шапку с пустым обрывком строки у края листа.
        # При этом длинная строка может делиться на новом полном листе.
        if (
            self.repeatRows
            and availHeight < sum(self._rowHeights[: self.repeatRows]) + 36
        ):
            return []
        return super().split(availWidth, availHeight)


def table(headers, rows, widths, *, small=False, padding=6):
    size = 8.5 if small else 9.2
    body = [
        [
            cell if isinstance(cell, (Flowable, list, tuple)) else p(cell, size)
            for cell in row
        ]
        for row in rows
    ]
    if not body:
        body = [[p("Нет данных в выбранном срезе", size)] + [""] * (len(headers) - 1)]
    t = ReportTable(
        [
            [
                h if isinstance(h, Flowable) else p(h, 8.2, True, colors.white)
                for h in headers
            ]
        ]
        + body,
        colWidths=widths,
        repeatRows=1,
        hAlign="LEFT",
        splitInRow=1,
    )
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [SOFT, colors.white]),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), padding),
                ("BOTTOMPADDING", (0, 0), (-1, -1), padding),
                ("LINEBELOW", (0, 0), (-1, 0), 0.5, NAVY),
            ]
        )
    )
    return t


def kpis(items, width):
    gap = 8
    cellwidth = (width - gap * (len(items) - 1)) / len(items)
    values = []
    widths = []
    for i, (title, value, sub) in enumerate(items):
        if i:
            values.append("")
            widths.append(gap)
        box = Table(
            [
                [p(title, 8.2, color=MUTED)],
                [p(value, 22, True, NAVY)],
                [p(sub, 8.2, color=MUTED)],
            ],
            colWidths=[cellwidth],
        )
        box.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), SOFT),
                    ("LEFTPADDING", (0, 0), (-1, -1), 10),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]
            )
        )
        values.append(box)
        widths.append(cellwidth)
    t = Table([values], colWidths=widths)
    t.setStyle(
        TableStyle(
            [
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    return t


def grouped(rows, width, *, limit=None):
    rows = list(rows)
    if limit and len(rows) > limit:
        rest = rows[limit:]
        rows = rows[:limit] + [
            {
                "name": "Прочие",
                "count": sum(r["count"] for r in rest),
                "sum": sum((r["sum"] for r in rest), Decimal(0)),
                "share": sum((r["share"] for r in rest), Decimal(0)),
            }
        ]
    name_width = width * 0.46
    return table(
        ["Сегмент", "СС, млн ₽", "Доля, %", "Зап."],
        [
            [
                label(r, name_width - 14),
                p(million(r["sum"]), right=True),
                p(number(r["share"]), right=True),
                p(r["count"], right=True),
            ]
            for r in rows
        ],
        [name_width, width * 0.24, width * 0.16, width * 0.14],
    )


class MonthChart(Flowable):
    def __init__(self, rows, width):
        super().__init__()
        self.rows = rows
        self.width = width
        self.height = 155

    def draw(self):
        c = self.canv
        top = max((r["sum"] for r in self.rows), default=0)
        pitch = self.width / max(len(self.rows), 1)
        baseline = 28
        c.setStrokeColor(LINE)
        c.line(0, baseline, self.width, baseline)
        for i, row in enumerate(self.rows):
            barheight = float(row["sum"] / top) * 105 if top else 0
            x = i * pitch + pitch * 0.18
            w = pitch * 0.64
            c.setFillColor(BLUE if i < 3 else colors.HexColor("#96a9be"))
            c.rect(x, baseline, w, barheight, fill=1, stroke=0)
            c.setFont("PropertyInter", 7.5)
            c.setFillColor(INK)
            c.drawCentredString(
                x + w / 2, baseline + barheight + 5, number(row["sum"] / 1_000_000, 0)
            )
            c.setFillColor(MUTED)
            c.drawCentredString(x + w / 2, 15, row["label"])
            c.drawCentredString(x + w / 2, 3, f'{row["count"]} зап.')


class ReportDocument(BaseDocTemplate):
    def __init__(self, stream, report, total_pages=0):
        super().__init__(
            stream,
            pagesize=A4,
            leftMargin=MARGIN,
            rightMargin=MARGIN,
            topMargin=29 * mm,
            bottomMargin=23 * mm,
            title=f'Страховая защита имущества на {report["as_of"]:%d.%m.%Y}',
            author="InsFlow",
            allowSplitting=True,
        )
        self.report = report
        self.total_pages = total_pages
        for name, size in (("portrait", A4), ("landscape", landscape(A4))):
            w, h = size
            frame = Frame(
                MARGIN,
                23 * mm,
                w - 2 * MARGIN,
                h - 52 * mm,
                id=name,
                leftPadding=0,
                rightPadding=0,
                topPadding=0,
                bottomPadding=0,
            )
            self.addPageTemplates(
                PageTemplate(
                    id=name, frames=[frame], pagesize=size, onPage=self.decorate
                )
            )

    def afterFlowable(self, flowable):
        if hasattr(flowable, "pdf_section"):
            key = f"section-{self.seq.nextf('section')}"
            self.canv.bookmarkPage(key)
            self.canv.addOutlineEntry(flowable.pdf_section, key, level=0, closed=False)

    def decorate(self, c, doc):
        w, h = self.pageTemplate.pagesize
        c.saveState()
        c.setFillColor(NAVY)
        c.rect(0, h - 10 * mm, w, 10 * mm, fill=1, stroke=0)
        c.setFont("PropertyInterBold", 8)
        c.setFillColor(colors.white)
        c.drawString(MARGIN, h - 6.8 * mm, "СТРАХОВАЯ ЗАЩИТА ИМУЩЕСТВА")
        c.drawRightString(
            w - MARGIN, h - 6.8 * mm, self.report["as_of"].strftime("%d.%m.%Y")
        )
        c.setFont("PropertyInter", 7.5)
        c.setFillColor(MUTED)
        c.drawString(MARGIN, h - 18 * mm, "Для руководства лизинговой компании")
        c.drawRightString(
            w - MARGIN, h - 18 * mm, "Основная часть" if doc.page <= 8 else "Приложения"
        )
        c.setStrokeColor(LINE)
        c.line(MARGIN, 18 * mm, w - MARGIN, 18 * mm)
        scope = self.report["scope_label"]
        branches = (
            "Все филиалы"
            if not self.report["selected_branches"]
            else f'Филиалов выбрано: {len(self.report["selected_branches"])}'
        )
        c.drawString(MARGIN, 12 * mm, f"{scope} · {branches} · Без ОСАГО")
        c.drawRightString(
            w - MARGIN,
            12 * mm,
            f"{doc.page} / {self.total_pages}" if self.total_pages else str(doc.page),
        )
        c.restoreState()


def _story(r):
    width = A4[0] - 2 * MARGIN
    story = []

    def add(*items):
        story.extend(items)

    def gap(n=9):
        add(Spacer(1, n))

    def section(title, subtitle="", new=True):
        if new:
            add(PageBreak())
        add(heading(title, 22))
        gap(9)
        if subtitle:
            add(note(subtitle))
            gap(13)

    def pair(title, rows):
        return [heading(title, 12), Spacer(1, 8), grouped(rows, width / 2 - 7)]

    section(
        "Страховая защита имущества",
        f'Срез на {r["as_of"]:%d.%m.%Y} · {r["scope_label"]}',
        False,
    )
    add(p(", ".join(r["selected_branches"]) or "Все филиалы", 10, color=MUTED))
    gap(16)
    add(
        kpis(
            [
                (
                    "Совокупная СС имущества",
                    million(r["totals"]["sum"]) + " млн ₽",
                    "Текущий страховой год",
                )
            ],
            width,
        )
    )
    gap(12)
    add(
        kpis(
            [
                (
                    "Страховых записей",
                    str(r["totals"]["count"]),
                    "Полисы / учётные позиции",
                ),
                (
                    "Лизингополучателей",
                    str(r["totals"]["lessees"]),
                    "Уникальные клиенты",
                ),
                (
                    "Страховых компаний",
                    str(r["totals"]["insurers"]),
                    "В имущественном срезе",
                ),
            ],
            width,
        )
    )
    gap(20)
    add(heading("Главное о портфеле"))
    gap()
    facts = [
        f'На три крупнейшие страховые компании приходится {number(r["concentration"]["top3_share"])}% СС.'
    ]
    if r["by_type"]:
        first = r["by_type"][0]
        facts.append(f'Крупнейший вид: {first["name"]} - {number(first["share"])}% СС.')
    renewal = r["renewals"][-1]
    facts.append(
        f'Окончания в ближайшие 90 дней: {renewal["endings"]["count"]}. Текущая СС: {million(renewal["endings"]["sum"])} млн ₽.'
    )
    for fact in facts:
        add(p(fact, 11))
        gap(9)
    gap()
    add(heading("Полнота и границы данных", 12))
    gap()
    add(
        note(
            f'Записей без определённой СС: {r["totals"]["missing_sum_count"]}. Они входят в количество, но исключены из стоимости. '
            + (
                f'Полнота СС по числу записей: {number(r["known_percent"])}%.'
                if r["known_percent"] is not None
                else "В выбранном срезе нет имущественных записей."
            )
        )
    )
    gap()
    add(
        note(
            f'Лимиты по виду «Ответственность» показаны отдельно: {million(r["liability"]["sum"])} млн ₽. Количество записей: {r["liability"]["count"]}.'
        )
    )
    gap()
    add(
        note(
            f'Сформировано {r["generated_at"]:%d.%m.%Y %H:%M %Z}. Методика {r["methodology_version"]}. Основная часть: страницы 1-8; далее приложения.'
        )
    )

    section(
        "Состав имущественного портфеля",
        "Доли рассчитаны по известной СС. Количество означает страховые записи.",
    )
    add(heading("Виды страхования", 12))
    gap()
    add(grouped(r["by_type"], width, limit=4))
    gap(18)
    nested = Table(
        [
            [
                pair("Возраст имущества", r["by_age"]),
                pair("Размер страховой суммы", r["by_size"]),
            ]
        ],
        colWidths=[width / 2, width / 2],
    )
    nested.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    add(nested)
    gap()
    add(
        note(
            "Возраст определяется по году выпуска. Неизвестная СС выделена отдельно; марки, франшизы и пометки состояния приведены в приложениях."
        )
    )

    section(
        "Страховые компании",
        "Крупнейшие компании и концентрация по СС. Полный список - в приложении А.",
    )
    add(grouped(r["insurers"], width, limit=8))
    gap(17)
    add(
        kpis(
            [
                (
                    "Три крупнейшие компании",
                    number(r["concentration"]["top3_share"]) + "%",
                    "От совокупной СС имущества",
                ),
                (
                    "Индекс HHI",
                    number(r["concentration"]["hhi"], 0),
                    "Концентрация распределения СС",
                ),
            ],
            width,
        )
    )
    gap(12)
    add(
        note(
            "HHI характеризует распределение портфеля. Он не является оценкой надёжности страховщика или качества урегулирования убытков."
        )
    )

    section(
        "Распределение по филиалам",
        "Обслуживающие филиалы лизинговой компании; это не фактическое местонахождение имущества.",
    )
    add(grouped(r["by_branch"], width, limit=8))
    gap(20)
    add(heading("Страховщики пяти крупнейших филиалов", 12))
    gap()
    rows = []
    for row in r["full_branch_matrix"]["rows"][:5]:
        candidates = [
            (cell["sum"], name)
            for cell, name in zip(row["cells"], r["full_branch_matrix"]["headers"])
            if name != "Прочие"
        ]
        best = max(candidates, default=(0, "Нет известной СС"))
        share = best[0] / row["total"] * 100 if row["total"] else 0
        rows.append([row["name"], best[1], number(share) + "%"])
    add(
        table(
            ["Филиал", "Крупнейший страховщик", "Доля СС филиала"],
            rows,
            [width * 0.35, width * 0.45, width * 0.2],
        )
    )
    gap()
    add(
        note(
            "Полная матрица всех страховщиков и филиалов приведена в приложениях. При большом числе филиалов основная часть показывает крупнейшие."
        )
    )

    section(
        "Как менялся портфель",
        "Сопоставимые срезы с теми же фильтрами. История восстановлена по текущей базе.",
    )
    comparisons = []
    for x in r["history"]:
        comparisons.append(
            [
                f'{x["months"]} мес. / {x["date"]:%d.%m.%Y}',
                million(x["sum"]),
                million(x["delta"]),
                number(x["percent"]) + "%" if x["percent"] is not None else "Нет базы",
                f'{x["entered"]} / {x["exited"]}',
            ]
        )
    add(
        table(
            [
                "Сравнение",
                "СС ранее, млн ₽",
                "Изменение, млн ₽",
                "Изменение, %",
                "Вошли / вышли",
            ],
            comparisons,
            [width * 0.27, width * 0.19, width * 0.20, width * 0.17, width * 0.17],
        )
    )
    gap(19)
    add(heading("Доли страховых компаний", 12))
    gap()
    dynamics = r["insurer_dynamics"]
    if dynamics:
        widths = [width * 0.28] + [width * 0.72 / (len(dynamics["dates"]) + 1)] * (
            len(dynamics["dates"]) + 1
        )
        add(
            table(
                ["Страховщик"]
                + [d.strftime("%d.%m.%y") for d in dynamics["dates"]]
                + ["Δ, п.п."],
                [
                    [row["name"]]
                    + [number(v) for v in row["shares"]]
                    + [number(row["change"])]
                    for row in dynamics["rows"][:5]
                ],
                widths,
                small=True,
            )
        )
    else:
        add(note("Для этой даты пока нет сопоставимых квартальных срезов."))
    gap(15)
    add(
        note(
            "Изменение учтённой СС связано с составом портфеля, переходом между страховыми годами и уточнениями данных. Оно не тождественно росту стоимости имущества компании."
        )
    )
    gap()
    add(
        note(
            "Записи без известной даты закрытия ДФА и изменения ручных статусов ограничивают точность восстановления истории. Данные до июля 2025 года могут быть неполными."
        )
    )

    section(
        "Окончания и кандидаты на продление",
        "Имущественные виды без ОСАГО. Горизонты 30/60/90 дней накопительные.",
    )
    add(
        kpis(
            [
                (
                    f'Окончания за {x["days"]} дней',
                    str(x["endings"]["count"]),
                    million(x["endings"]["sum"]) + " млн ₽ текущей СС",
                )
                for x in r["renewals"]
            ],
            width,
        )
    )
    gap(13)
    add(
        table(
            ["Горизонт", "Кандидаты на продление", "Текущая СС кандидатов, млн ₽"],
            [
                [
                    f'{x["days"]} дней',
                    x["candidates"]["count"],
                    million(x["candidates"]["sum"]),
                ]
                for x in r["renewals"]
            ],
            [width * 0.23, width * 0.34, width * 0.43],
        )
    )
    gap(15)
    add(heading("Календарь окончаний на 12 месяцев", 12))
    gap()
    add(note("Млн ₽ текущей СС; первый месяц начинается с даты среза."))
    gap(10)
    add(MonthChart(r["ending_by_month"], width))
    gap(18)
    add(
        note(
            "Кандидаты: продлеваемый вид, ДФА продолжается после окончания, нет известного расторжения до окончания. Это не подтверждение разрыва страхования: новый связанный полис может быть уже оформлен."
        )
    )
    gap()
    add(
        note(
            "Показана СС текущего года, а не прогноз суммы или цены следующего страхового года."
        )
    )

    section(
        "Крупные позиции и лизингополучатели",
        "Наиболее значимые записи; полные описания 20 крупнейших позиций - в приложении.",
    )
    add(heading("Пять крупнейших страховых записей", 12))
    gap()
    add(
        table(
            ["Полис / лизингополучатель", "Вид / филиал", "СС, млн ₽", "Полис до"],
            [
                [
                    p(o["policy_number"] + "\n" + o["client"]),
                    p(o["type"] + "\n" + o["branch"]),
                    p(
                        million(o["sum"]) if o["sum"] is not None else "Не определена",
                        right=True,
                    ),
                    o["end_date"].strftime("%d.%m.%Y"),
                ]
                for o in r["top_objects"][:5]
            ],
            [width * 0.44, width * 0.25, width * 0.16, width * 0.15],
        )
    )
    gap(20)
    add(heading("Пять крупнейших лизингополучателей", 12))
    gap()
    add(grouped(r["clients"][:5], width))
    gap(16)
    add(
        note(
            "Концентрация по лизингополучателям показывает распределение страховых сумм. Она не оценивает платёжеспособность клиента."
        )
    )

    section(
        "Методика и полнота данных",
        f'Версия {r["methodology_version"]} · сформировано {r["generated_at"]:%d.%m.%Y %H:%M %Z}',
    )
    methods = [
        (
            "Состав портфеля",
            "Полисы в силе на дату среза с активным на эту дату ДФА. ОСАГО не входит. Именованный вид «Ответственность» вынесен отдельно.",
        ),
        (
            "Страховая сумма",
            "СС первого взноса последнего начавшегося страхового года, один раз на запись. Неизвестная сумма не заменяется максимумом или СС предыдущего года.",
        ),
        (
            "Количество и среднее",
            "Количество - страховые записи, не уникальные физические объекты. Средняя СС рассчитана только по записям с известной суммой.",
        ),
        (
            "Филиалы и история",
            "Филиал означает обслуживание портфеля. Исторические срезы восстановлены из текущей базы и могут изменяться после её уточнений.",
        ),
        (
            "Описание имущества",
            "Марки и пометки «новое/б/у» определяются по свободному описанию и являются вспомогательными сведениями.",
        ),
        (
            "Границы выводов",
            "Отчёт не определяет долю застрахованного во всём имуществе компании, недострахование, надёжность страховщиков или наличие разрывов покрытия.",
        ),
    ]
    for title, body in methods:
        add(heading(title, 11))
        gap(5)
        add(p(body))
        gap(12)
    add(heading("Имущество и ответственность", 12))
    gap()
    add(
        table(
            ["Показатель", "Значение"],
            [
                ["СС имущества, млн ₽", million(r["totals"]["sum"])],
                [
                    "Сумма лимитов ответственности, млн ₽",
                    million(r["liability"]["sum"]),
                ],
                [
                    "СС имущества + лимиты ответственности, млн ₽",
                    million(r["scope_total"]),
                ],
                ["Записей без СС имущества", r["totals"]["missing_sum_count"]],
            ],
            [width * 0.73, width * 0.27],
        )
    )
    gap()
    add(
        note(
            "Лимиты ответственности не складываются с СС имущества в основных показателях этого отчёта. Имущественные показатели совпадают с Дашбордом и кратким срезом на ту же дату при тех же фильтрах."
        )
    )

    section(
        "Приложение А. Полные распределения",
        "Все страховые компании и менеджеры выбранного имущественного среза.",
    )
    add(heading("Страховые компании", 13))
    gap()
    add(grouped(r["insurers"], width))
    gap(18)
    if r["insurer_dynamics"]:
        dynamics = r["insurer_dynamics"]
        add(KeepTogether([heading("Полная таблица динамики долей", 13), Spacer(1, 9)]))
        widths = [width * 0.28] + [width * 0.72 / (len(dynamics["dates"]) + 1)] * (
            len(dynamics["dates"]) + 1
        )
        add(
            table(
                ["Страховщик"]
                + [d.strftime("%d.%m.%y") for d in dynamics["dates"]]
                + ["Δ, п.п."],
                [
                    [row["name"]]
                    + [number(v) for v in row["shares"]]
                    + [number(row["change"])]
                    for row in dynamics["rows"]
                ],
                widths,
                small=True,
            )
        )
        gap(18)
    add(KeepTogether([heading("Менеджеры лизинговой компании", 13), Spacer(1, 9)]))
    add(grouped(r["all_managers"], width))
    gap()
    add(
        note(
            f'Записей без менеджера: {r["without_manager"]["count"]}; СС {million(r["without_manager"]["sum"])} млн ₽.'
        )
    )

    # Отдельные альбомные листы: не уменьшаем таблицы до нечитаемого размера.
    add(NextPageTemplate("landscape"), PageBreak())
    wide = landscape(A4)[0] - 2 * MARGIN
    for matrix_index, (title, key) in enumerate(
        (
            ("Филиалы × страховые компании", "full_branch_matrix"),
            ("Страховые компании × виды", "insurer_by_type"),
        )
    ):
        matrix = r[key]
        chunks = list(range(0, len(matrix["headers"]), 6)) or [0]
        for chunk_index, start in enumerate(chunks):
            if matrix_index or chunk_index:
                add(PageBreak())
            add(heading("Приложение Б. " + title, 19))
            gap(8)
            add(
                note(
                    f"СС, млн ₽. Часть {chunk_index+1} из {len(chunks)}. «Итого» - вся строка, включая столбцы других частей."
                )
            )
            gap(12)
            headers = matrix["headers"][start : start + 6]
            widths = (
                [wide * 0.24]
                + [wide * 0.62 / max(len(headers), 1)] * len(headers)
                + [wide * 0.14]
            )
            rows = [
                [label(row, widths[0] - 14, image_size=14)]
                + [
                    million(cell["sum"]) if cell["sum"] else "-"
                    for cell in row["cells"][start : start + 6]
                ]
                + [million(row["total"])]
                for row in matrix["rows"]
            ]
            add(
                table(
                    ["Филиал" if key == "full_branch_matrix" else "Страховщик"]
                    + [
                        label(
                            column,
                            widths[i + 1] - 14,
                            color=colors.white,
                            size=8.2,
                            image_size=14,
                        )
                        for i, column in enumerate(matrix["columns"][start : start + 6])
                    ]
                    + ["Итого"],
                    rows,
                    widths,
                    padding=3,
                )
            )

    add(NextPageTemplate("portrait"), PageBreak())
    section(
        "Приложение В. Характеристики имущества",
        "Вспомогательные распределения. Неуказанные и нераспознанные значения показаны явно.",
        False,
    )
    for title, key in (
        ("Марки из описаний", "by_brand"),
        ("Пометка нового / подержанного имущества", "by_condition"),
        ("Франшиза по учётным данным", "by_franchise"),
        ("По году окончания полиса", "by_end_year"),
    ):
        add(KeepTogether([heading(title, 13), Spacer(1, 9)]))
        add(grouped(r[key], width))
        gap(18)
    add(
        note(
            "«Не распознано» не обязательно означает ошибку: марка может быть неприменима к данному имуществу. Группы «Другие марки» сохраняют сумму и количество остальных распознанных марок."
        )
    )

    section(
        "Приложение Г. Крупнейшие позиции",
        "До 20 записей по известной СС. Полные описания без сокращения; продолжение таблицы - на следующих страницах.",
    )
    rows = []
    for i, o in enumerate(r["top_objects"], 1):
        rows.append(
            [
                str(i),
                p(
                    f'{o["policy_number"]}\nДФА: {o["dfa_number"]}\n{o["client"]}\n{o["description"]}'
                ),
                [
                    label(
                        {"name": o[key], "image_url": o[key + "_image_url"]},
                        width * 0.24 - 14,
                    )
                    for key in ("type", "insurer", "branch")
                ]
                + [p(f'До {o["end_date"]:%d.%m.%Y}')],
                p(
                    million(o["sum"]) if o["sum"] is not None else "Не определена",
                    right=True,
                ),
            ]
        )
    add(
        table(
            [
                "№",
                "Полис, ДФА, лизингополучатель и имущество",
                "Страхование",
                "СС, млн ₽",
            ],
            rows,
            [width * 0.06, width * 0.55, width * 0.24, width * 0.15],
        )
    )
    gap(18)
    add(KeepTogether([heading("Крупные ближайшие окончания", 13), Spacer(1, 9)]))
    add(
        table(
            ["Полис / лизингополучатель", "Дата окончания", "СС, млн ₽"],
            [
                [
                    p(o.policy_number + "\n" + o.client),
                    o.end_date.strftime("%d.%m.%Y"),
                    million(o.insured_sum) if o.insured_sum_known else "Не определена",
                ]
                for o in r["upcoming_objects"]
            ],
            [width * 0.60, width * 0.23, width * 0.17],
        )
    )
    section(
        "Приложение Д. Ответственность",
        "Лимиты по виду «Ответственность» показаны отдельно и не входят в СС имущества.",
    )
    add(
        table(
            ["Полис / ДФА", "Лизингополучатель / страховщик", "Филиал", "Лимит, млн ₽"],
            [
                [
                    p(o["policy_number"] + "\n" + o["dfa_number"]),
                    p(o["client"] + "\n" + o["insurer"]),
                    o["branch"],
                    million(o["sum"]) if o["sum"] is not None else "Не определён",
                ]
                for o in r["liability"]["rows"]
            ],
            [width * 0.25, width * 0.37, width * 0.21, width * 0.17],
        )
    )
    gap(15)
    add(
        note(
            f'Записей: {r["liability"]["count"]}. Сумма учтённых лимитов: {million(r["liability"]["sum"])} млн ₽. Лимиты разных договоров не означают единое покрытие на эту сумму.'
        )
    )
    return story


def build_property_pdf(report):
    """Возвращает готовый PDF. Два прохода дают точное число страниц."""
    _fonts()
    first = ReportDocument(BytesIO(), report)
    first.build(_story(report))
    output = BytesIO()
    final = ReportDocument(output, report, total_pages=first.page)
    final.build(_story(report))
    return output.getvalue()
