from pathlib import Path
from datetime import date
from xml.sax.saxutils import escape
import json
import re
import unicodedata

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    KeepTogether,
    ListFlowable,
    ListItem,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent

INPUT_DIR = PROJECT_ROOT / "data" / "top10"
OUTPUT_DIR = PROJECT_ROOT / "data" / "docs"

COMBINED_FILE = OUTPUT_DIR / "top10_documentacion.pdf"

PRIMARY = colors.HexColor("#1F3A5F")
ACCENT = colors.HexColor("#2E75B6")
LIGHT = colors.HexColor("#EEF3F8")
GREY = colors.HexColor("#6B7280")

TICKET_PATTERN = re.compile(r"INC\d{6,}")
STEP_PATTERN = re.compile(r"^\s*(\d+)[).]\s*")


# ------------------------------------------------------------------
# Fuentes (Arial de Windows para acentos y "l·l"; Helvetica si no existe)
# ------------------------------------------------------------------

def register_fonts() -> tuple[str, str]:

    fonts_dir = Path("C:/Windows/Fonts")
    regular = fonts_dir / "arial.ttf"
    bold = fonts_dir / "arialbd.ttf"

    if regular.exists() and bold.exists():
        pdfmetrics.registerFont(TTFont("Arial", str(regular)))
        pdfmetrics.registerFont(TTFont("Arial-Bold", str(bold)))
        return "Arial", "Arial-Bold"

    return "Helvetica", "Helvetica-Bold"


FONT, FONT_BOLD = register_fonts()

STYLES = {
    "cover_title": ParagraphStyle(
        "cover_title", fontName=FONT_BOLD, fontSize=26, leading=32,
        textColor=PRIMARY, spaceAfter=12,
    ),
    "cover_sub": ParagraphStyle(
        "cover_sub", fontName=FONT, fontSize=13, leading=18, textColor=GREY,
    ),
    "kicker": ParagraphStyle(
        "kicker", fontName=FONT_BOLD, fontSize=9, leading=12,
        textColor=ACCENT, spaceAfter=4,
    ),
    "title": ParagraphStyle(
        "title", fontName=FONT_BOLD, fontSize=17, leading=22,
        textColor=PRIMARY, spaceAfter=10,
    ),
    "h2": ParagraphStyle(
        "h2", fontName=FONT_BOLD, fontSize=12, leading=16,
        textColor=PRIMARY, spaceBefore=12, spaceAfter=6,
    ),
    "body": ParagraphStyle(
        "body", fontName=FONT, fontSize=10, leading=14, alignment=TA_LEFT,
    ),
    "cell_label": ParagraphStyle(
        "cell_label", fontName=FONT_BOLD, fontSize=9, leading=12, textColor=PRIMARY,
    ),
    "cell": ParagraphStyle(
        "cell", fontName=FONT, fontSize=9, leading=12,
    ),
    "small": ParagraphStyle(
        "small", fontName=FONT, fontSize=8.5, leading=11, textColor=GREY,
    ),
}


# ------------------------------------------------------------------
# Datos
# ------------------------------------------------------------------

def load_groups() -> list[dict]:
    """Lee todos los top10_*.json y devuelve los grupos ordenados por apariciones."""

    groups = []

    for file in sorted(INPUT_DIR.glob("top10_*.json")):
        data = json.loads(file.read_text(encoding="utf-8"))

        for group in data.get("grupos", []):
            group["origen"] = file.stem
            groups.append(group)

    groups.sort(key=lambda g: g.get("apariciones", 0), reverse=True)

    return groups


def split_description(text: str) -> tuple[str, list[str]]:
    """Separa la descripción de la lista "Tickets: ..." que añade el flujo."""

    tickets = TICKET_PATTERN.findall(text)
    description = re.split(r"\s*Tickets?\s*:", text, maxsplit=1)[0].strip()

    return description, tickets


def split_steps(text: str) -> list[str]:
    """Convierte "1) ...\n2) ..." en una lista de pasos."""

    lines = [line.strip() for line in text.splitlines() if line.strip()]

    steps = []

    for line in lines:
        if STEP_PATTERN.match(line) or not steps:
            steps.append(STEP_PATTERN.sub("", line))
        else:
            steps[-1] += " " + line

    return steps


def slugify(text: str, max_len: int = 60) -> str:

    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^\w]+", "_", text.lower()).strip("_")

    return text[:max_len].rstrip("_")


def p(text: str, style: str = "body") -> Paragraph:
    return Paragraph(escape(str(text or "")).replace("\n", "<br/>"), STYLES[style])


# ------------------------------------------------------------------
# Plantilla de un elemento recurrente
# ------------------------------------------------------------------

def element_story(group: dict, position: int) -> list:

    description, tickets = split_description(group.get("elemento_recurrente", ""))
    steps = split_steps(group.get("resolucion", ""))

    story = [
        p(f"ELEMENTO RECURRENTE #{position}", "kicker"),
        p(group.get("titulo_propuesto", "Sin título"), "title"),
    ]

    # Ficha
    rows = [
        ("Apariciones", str(group.get("apariciones", ""))),
        ("Servicio", group.get("service") or "—"),
        ("SRD", group.get("srd") or "—"),
        ("Fecha documento", date.today().strftime("%d/%m/%Y")),
    ]

    table = Table(
        [[p(label, "cell_label"), p(value, "cell")] for label, value in rows],
        colWidths=[4 * cm, 13 * cm],
    )
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), LIGHT),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#C9D3DF")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story += [table, Spacer(1, 6)]

    # Descripción
    story += [p("Descripción del problema", "h2"), p(description)]

    # Procedimiento
    story.append(p("Procedimiento de resolución", "h2"))

    if steps:
        story.append(ListFlowable(
            [ListItem(p(step), leftIndent=14) for step in steps],
            bulletType="1",
            bulletFontName=FONT_BOLD,
            bulletFontSize=10,
            bulletColor=ACCENT,
            leftIndent=14,
            spaceBefore=2,
        ))
    else:
        story.append(p("Sin procedimiento disponible."))

    # Tickets
    if tickets:
        story.append(KeepTogether([
            p("Tickets relacionados", "h2"),
            p(", ".join(tickets), "small"),
        ]))

    return story


def draw_page(canvas, doc):
    """Cabecera y pie de cada página."""

    canvas.saveState()
    width, height = A4

    canvas.setFillColor(PRIMARY)
    canvas.rect(0, height - 0.6 * cm, width, 0.6 * cm, stroke=0, fill=1)

    canvas.setFont(FONT, 8)
    canvas.setFillColor(GREY)
    canvas.drawString(2 * cm, 1.2 * cm, "Recurrencia de incidencias B3")
    canvas.drawRightString(width - 2 * cm, 1.2 * cm, f"Página {doc.page}")

    canvas.restoreState()


def build_pdf(path: Path, story: list, title: str):

    doc = SimpleDocTemplate(
        str(path),
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
        title=title,
    )
    doc.build(story, onFirstPage=draw_page, onLaterPages=draw_page)


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------

def cover_story(groups: list[dict]) -> list:

    story = [
        Spacer(1, 5 * cm),
        p("Top 10 incidencias recurrentes", "cover_title"),
        p(f"Documentación de resolución · {date.today().strftime('%d/%m/%Y')}", "cover_sub"),
        Spacer(1, 1.5 * cm),
    ]

    rows = [[p("#", "cell_label"), p("Elemento recurrente", "cell_label"), p("Apariciones", "cell_label")]]
    rows += [
        [p(str(i), "cell"), p(g.get("titulo_propuesto", ""), "cell"), p(str(g.get("apariciones", "")), "cell")]
        for i, g in enumerate(groups, start=1)
    ]

    table = Table(rows, colWidths=[1 * cm, 13.5 * cm, 2.5 * cm], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), LIGHT),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor("#C9D3DF")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(table)

    return story


def main():

    groups = load_groups()

    if not groups:
        print(f"No hay ficheros top10_*.json en {INPUT_DIR}")
        return

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Un PDF por elemento
    for position, group in enumerate(groups, start=1):
        title = group.get("titulo_propuesto", f"elemento_{position}")
        path = OUTPUT_DIR / f"{position:02d}_{slugify(title)}.pdf"

        build_pdf(path, element_story(group, position), title)
        print(f"Creado {path.name}")

    # PDF conjunto: portada + índice + todos los elementos
    story = cover_story(groups)

    for position, group in enumerate(groups, start=1):
        story += [PageBreak()] + element_story(group, position)

    build_pdf(COMBINED_FILE, story, "Top 10 incidencias recurrentes")
    print(f"\nCreado {COMBINED_FILE.name} ({len(groups)} elementos)")


if __name__ == "__main__":
    main()
