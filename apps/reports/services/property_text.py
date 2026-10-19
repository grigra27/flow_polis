"""
Марка и состояние (новое / б/у) имущества из свободного текста описания.

Структурированных полей марки и состояния в базе нет, поэтому это эвристика
по словарю: описания вида «б/у Автомобиль AUDI Q7 vin0674», «экскаватор
LIUGONG CLG933E (нов.)», «ВИС LADA GRANTA фургон». Что не распознано —
честно попадает в «Не распознано». Словарь собран по описаниям на проде
(2026-10-19: распознаётся ~82% страховой стоимости; остальное — в основном
оборудование и спецмашины, описанные только номером модели кузова); новая марка добавляется одной строкой в BRANDS.
"""

import re
from typing import Dict, List, Optional, Tuple

NOT_RECOGNIZED = "Не распознано"

# Марка → написания в описаниях (в верхнем регистре). Многословные
# написания проверяются как фраза, остальные — как отдельное слово.
BRANDS: Dict[str, List[str]] = {
    "LADA": ["LADA", "ЛАДА", "ВИС", "GRANTA", "VESTA", "LARGUS", "NIVA"],
    "Haval": ["HAVAL", "ХАВАЛ", "JOLION", "DARGO"],
    "Tank": ["TANK"],
    "GWM": ["GWM", "GREAT WALL", "POER", "WEY"],
    "Geely": ["GEELY", "ДЖИЛИ", "MONJARO", "COOLRAY"],
    "Chery": ["CHERY", "ЧЕРИ", "TIGGO"],
    "Omoda": ["OMODA"],
    "Exeed": ["EXEED"],
    "Hongqi": ["HONGQI"],
    "GAC": ["GAC"],
    "JAC": ["JAC"],
    "Changan": ["CHANGAN"],
    "Jetour": ["JETOUR"],
    "Tenet": ["TENET"],
    "Belgee": ["BELGEE"],
    "Solaris": ["SOLARIS"],
    "Hyundai": ["HYUNDAI", "ХЕНДЭ", "ХУНДАЙ"],
    "Kia": ["KIA", "КИА"],
    "Toyota": ["TOYOTA", "ТОЙОТА", "CAMRY", "LAND CRUISER"],
    "Lexus": ["LEXUS"],
    "BMW": ["BMW", "БМВ"],
    "Mercedes-Benz": ["MERCEDES-BENZ", "MERCEDES", "МЕРСЕДЕС"],
    "Audi": ["AUDI", "АУДИ"],
    "Volkswagen": ["VOLKSWAGEN", "VW", "ФОЛЬКСВАГЕН"],
    "Chevrolet": ["CHEVROLET", "ШЕВРОЛЕ", "TAHOE"],
    "Sollers": ["SOLLERS", "СОЛЛЕРС"],
    "ГАЗ": ["ГАЗ", "GAZ", "ГАЗЕЛЬ", "GAZELLE", "СОБОЛЬ", "SOBOL"],
    "УАЗ": ["УАЗ", "UAZ"],
    "КАМАЗ": ["КАМАЗ", "KAMAZ"],
    "МАЗ": ["МАЗ", "MAZ"],
    "НЕФАЗ": ["НЕФАЗ"],
    "ПАЗ": ["ПАЗ"],
    "Урал": ["УРАЛ"],
    "Тонар": ["ТОНАР", "TONAR"],
    "Беларус (МТЗ)": ["БЕЛАРУС", "BELARUS", "МТЗ"],
    "Shacman": ["SHACMAN", "ШАКМАН"],
    "Sitrak": ["SITRAK", "СИТРАК"],
    "Howo": ["HOWO", "ХОВО"],
    "FAW": ["FAW"],
    "Dongfeng": ["DONGFENG"],
    "Foton": ["FOTON"],
    "Hongyan": ["HONGYAN"],
    "Isuzu": ["ISUZU", "ИСУЗУ"],
    "Volvo": ["VOLVO", "ВОЛЬВО"],
    "Scania": ["SCANIA", "СКАНИЯ"],
    "MAN": ["MAN"],
    "DAF": ["DAF"],
    "Yutong": ["YUTONG"],
    "Higer": ["HIGER"],
    "Schmitz Cargobull": ["SCHMITZ", "CARGOBULL"],
    "Krone": ["KRONE"],
    "Kässbohrer": ["KASSBOHRER", "KÄSSBOHRER"],
    "Grunwald": ["GRUNWALD"],
    "Атлант": ["АТЛАНТ", "ATLANT"],
    "SANY": ["SANY", "САНИ"],
    "XCMG": ["XCMG"],
    "Zoomlion": ["ZOOMLION"],
    "LiuGong": ["LIUGONG", "LGCE"],
    "Lonking": ["LONKING"],
    "Lovol": ["LOVOL"],
    "Sunward": ["SUNWARD"],
    "SDLG": ["SDLG"],
    "Shantui": ["SHANTUI"],
    "Caterpillar": ["CATERPILLAR", "CAT"],
    "Komatsu": ["KOMATSU"],
    "Hitachi": ["HITACHI"],
    "JCB": ["JCB"],
    "Doosan": ["DOOSAN", "DEVELON"],
    "Hyundai CE": ["HD-CE"],
    "Bomag": ["BOMAG"],
    "Merlo": ["MERLO"],
    "Heli": ["HELI"],
    "Aodes": ["AODES"],
    "NFLG": ["NFLG"],
    "John Deere": ["JOHN DEERE", "DEERE"],
    "Kirovets": ["КИРОВЕЦ", "KIROVETS"],
    "Ростсельмаш": ["РОСТСЕЛЬМАШ", "ROSTSELMASH", "RSM", "РСМ", "ACROS", "TORUM"],
    "Baltmotors": ["BALTMOTORS"],
    "Wirtgen": ["WIRTGEN"],
    "Hamm": ["HAMM"],
    "Vögele": ["VOGELE", "VÖGELE"],
    "Tverstroymash": ["TVERSTROYMASH"],
    "Avatr": ["AVATR"],
    "Ammann": ["AMMANN"],
    "Zeekr": ["ZEEKR"],
    "Jaecoo": ["JAECOO"],
    "Evolute": ["EVOLUTE"],
    "Mitsubishi": ["MITSUBISHI"],
    "Mazda": ["MAZDA"],
    "Skoda": ["SKODA", "ŠKODA"],
    "Nissan": ["NISSAN"],
    "Renault": ["RENAULT"],
    "Ford": ["FORD"],
    "Porsche": ["PORSCHE"],
    "Land Rover": ["LAND ROVER", "RANGE ROVER"],
    "Ram": ["RAM"],
    "GMC": ["GMC"],
    "Cadillac": ["CADILLAC"],
    "Li Auto": ["LIXIANG", "LI AUTO"],
    "Voyah": ["VOYAH"],
    "Kanglim": ["KANGLIM"],
    "WeHeavy": ["WEHEAVY"],
    "Bull": ["BULL"],
    "Leotrack": ["LEOTRACK"],
    "Спецприцеп": ["SPECPRICEP", "СПЕЦПРИЦЕП"],
    "Liebherr": ["LIEBHERR"],
    "Manitou": ["MANITOU"],
    "Bobcat": ["BOBCAT"],
    "New Holland": ["NEW HOLLAND"],
    "Claas": ["CLAAS"],
    "Kubota": ["KUBOTA"],
    "Yanmar": ["YANMAR"],
    "Hyster": ["HYSTER"],
    "Linde": ["LINDE"],
    "Jungheinrich": ["JUNGHEINRICH"],
    "Hangcha": ["HANGCHA"],
    "Hidromek": ["HIDROMEK"],
    "Tadano": ["TADANO"],
    "Ивановец": ["ИВАНОВЕЦ"],
    "Галичанин": ["ГАЛИЧАНИН"],
    "Клинцы": ["КЛИНЦЫ"],
    "ЧЕТРА": ["ЧЕТРА"],
    "ДСТ-Урал": ["ДСТ-УРАЛ"],
}

_LEADING_LETTERS_RE = re.compile(r"([A-ZА-ЯЁ]{2,})[0-9]")
_TOKEN_RE = re.compile(r"[A-ZА-ЯЁÄ0-9]+(?:-[A-ZА-ЯЁÄ]+)*")
_USED_RE = re.compile(r"(?<![А-ЯЁA-Z])Б\s*[/.]\s*У(?![А-ЯЁA-Z])|БЫВШ|ПОДЕРЖАН")
_NEW_RE = re.compile(r"(?<![А-ЯЁA-Z])НОВ(?:\.|ЫЙ|АЯ|ОЕ|ЫЕ|\b|(?=[^А-ЯЁ]))")

_PHRASES: List[Tuple[str, str]] = []
_WORDS: Dict[str, str] = {}
for _brand, _spellings in BRANDS.items():
    for _spelling in _spellings:
        if " " in _spelling:
            _PHRASES.append((_spelling, _brand))
        else:
            _WORDS[_spelling] = _brand


def detect_brand(text: str) -> str:
    """Марка из описания; при нескольких — та, что встречается раньше."""
    upper = (text or "").upper()
    found: List[Tuple[int, str]] = []
    for phrase, brand in _PHRASES:
        position = upper.find(phrase)
        if position >= 0:
            found.append((position, brand))
    for match in _TOKEN_RE.finditer(upper):
        word = match.group(0)
        brand = _WORDS.get(word)
        if brand is None and "-" in word:
            # «ГАЗ-Next», «КАМАЗ-Евро» — марка в первой части через дефис.
            brand = _WORDS.get(word.split("-")[0])
        if brand is None:
            # «CAT320», «КАМАЗ65115» — марка слитно с номером модели.
            letters = _LEADING_LETTERS_RE.match(word)
            if letters and letters.group(1) != word:
                brand = _WORDS.get(letters.group(1))
        if brand:
            found.append((match.start(), brand))
    if not found:
        return NOT_RECOGNIZED
    return min(found)[1]


CONDITION_NEW = "Новое"
CONDITION_USED = "Б/у"
CONDITION_UNKNOWN = "Не указано"


def detect_condition(text: str) -> str:
    """«Новое» / «Б/у» по пометкам в описании; иначе «Не указано»."""
    upper = (text or "").upper()
    if _USED_RE.search(upper):
        return CONDITION_USED
    if _NEW_RE.search(upper):
        return CONDITION_NEW
    return CONDITION_UNKNOWN


def property_age(property_year: Optional[int], year: int) -> Optional[int]:
    if not property_year:
        return None
    return max(year - property_year, 0)
