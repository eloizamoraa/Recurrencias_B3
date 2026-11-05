import json
import re
import sys
import unicodedata
from collections import Counter
from itertools import groupby
from xml.sax.saxutils import escape

import requests

from src.build_docs import OUTPUT_DIR, load_groups, split_description
from src.confluence import AUTH, BASE, SPACES


# Página bajo la que se crean los borradores (de la URL .../pages/edit-v2/<id>)
PARENT_ID = "2485125311"

# Registro de lo ya creado, para no duplicar páginas si se relanza
CREATED_FILE = OUTPUT_DIR / "confluence_drafts.json"

# Documentación existente del portal que se enlaza al final de cada borrador
RELATED_SEARCH_LIMIT = 10
RELATED_MAX = 5
# Una página que sale en las búsquedas de 3 o más elementos es ruido (páginas muy largas)
RELATED_NOISE = 3
# Los primeros resultados del buscador se aceptan siempre; el resto solo si el título
# de la página comparte alguna palabra con el elemento
RELATED_TOP_TRUSTED = 2

KEYWORD_STOP = {
    "acceso", "acces", "acceder", "accedir", "configuracio", "configurar", "desde", "error",
    "funciona", "incidencia", "incidencies", "equipo", "pagina", "para", "problemes",
    "servei", "servicio", "sobre", "usuari", "usuario", "amb", "con", "del", "las", "los",
    "por", "que", "sin", "una",
}


def keywords(text: str) -> set[str]:
    """Raíces de 5 letras sin acentos, para comparar castellano con catalán."""

    text = unicodedata.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode()

    return {w[:5] for w in re.findall(r"[a-z0-9]{3,}", text) if w not in KEYWORD_STOP}


def search_related(title: str) -> list[dict]:
    """Busca en los espacios del portal (CONFLUENCE_SPACES) páginas parecidas al título."""

    spaces = ", ".join(f'"{k}"' for k in SPACES)
    text = title.replace('"', "")
    cql = f'space in ({spaces}) AND type = page AND siteSearch ~ "{text}"'

    r = requests.get(
        f"{BASE}/rest/api/search",
        auth=AUTH,
        params={"cql": cql, "limit": RELATED_SEARCH_LIMIT, "expand": "content.space"},
    )
    r.raise_for_status()

    return [
        {
            "id": res["content"]["id"],
            "title": res["content"]["title"],
            "space": res["content"].get("space", {}).get("key", ""),
            "url": BASE + res["content"]["_links"]["webui"],
        }
        for res in r.json().get("results", [])
    ]


def related_by_group(groups: list[dict]) -> list[list[dict]]:
    """Resultados de cada elemento, sin las páginas que salen para casi todos."""

    results = [search_related(g.get("titulo_propuesto", "")) for g in groups]

    counts = Counter(page["id"] for pages in results for page in pages)
    noise = {page_id for page_id, n in counts.items() if n >= RELATED_NOISE}

    related = []

    for group, pages in zip(groups, results):
        description, _ = split_description(group.get("elemento_recurrente", ""))
        group_keys = keywords(group.get("titulo_propuesto", "") + " " + description)

        pages = [page for page in pages if page["id"] not in noise]
        keep = pages[:RELATED_TOP_TRUSTED] + [
            page for page in pages[RELATED_TOP_TRUSTED:] if keywords(page["title"]) & group_keys
        ]
        related.append(keep[:RELATED_MAX])

    return related


def page_space_id(page_id: str) -> str:

    r = requests.get(f"{BASE}/api/v2/pages/{page_id}", auth=AUTH)
    r.raise_for_status()

    return r.json()["spaceId"]


REMEDY_PANEL = (
    '<ac:structured-macro ac:name="panel" ac:schema-version="1">'
    '<ac:parameter ac:name="panelIcon">:Remedy:</ac:parameter>'
    '<ac:parameter ac:name="panelIconId">1f7207f6-c743-4dbd-9e5c-4eea2f86426f</ac:parameter>'
    '<ac:parameter ac:name="panelIconText">:Remedy:</ac:parameter>'
    '<ac:parameter ac:name="bgColor">#B3F5FF</ac:parameter>'
    "<ac:rich-text-body>{}</ac:rich-text-body></ac:structured-macro>"
)


def bold(text: str) -> str:
    return f"<strong>{escape(text)}</strong> "


def right_column(group: dict) -> str:
    """Índice + paneles de Remedy como la plantilla de servicio (solo Service y SRD rellenados)."""

    service = escape(group.get("service") or "")
    srd = group.get("srd") or ""
    srd = "" if srd.strip().lower() == "sense assignar" else escape(srd)

    toc = (
        "<p><strong>En aquesta pàgina:</strong></p>"
        '<ac:structured-macro ac:name="toc" ac:schema-version="1">'
        '<ac:parameter ac:name="maxLevel">3</ac:parameter>'
        "</ac:structured-macro>"
    )

    remedy = (
        f"<p>{bold('Eina:')}</p>"
        f"<p>{bold('Service:')}{service}</p>"
        f"<p>{bold('Assigned Group:')}</p>"
        "<p><strong><u>Product Categorization</u></strong></p>"
        "<ul>"
        f"<li><p>{bold('Tier 1:')}</p></li>"
        f"<li><p>{bold('Tier 2:')}</p></li>"
        f"<li><p>{bold('Tier 3:')}</p></li>"
        f"<li><p>{bold('Product Name+:')}</p></li>"
        "</ul>"
        f"<p>{bold('SRD:')}{srd}</p>"
    )

    codes = (
        f"<p>{bold('Codi d’aplicació:')}</p>"
        f"<p>{bold('Codi de servei d’infraestructura:')}</p>"
        f"<p>{bold('Proveïdor infraestructura:')}</p>"
    )

    return toc + REMEDY_PANEL.format(remedy) + REMEDY_PANEL.format(codes)


def group_to_html(group: dict, related: list[dict]) -> str:
    """Cuerpo de la página en formato storage: contenido a la izquierda, índice y paneles a la derecha."""

    return (
        '<ac:layout><ac:layout-section ac:type="two_right_sidebar" ac:breakout-mode="wide">'
        f"<ac:layout-cell>{left_column(group, related)}</ac:layout-cell>"
        f"<ac:layout-cell>{right_column(group)}</ac:layout-cell>"
        "</ac:layout-section></ac:layout>"
    )


# Formato de "resolucion" que devuelve el flujo:
#   a) DIAGNÒSTIC INICIAL      -> sección
#   - texto                    -> viñeta
#   1. texto                   -> paso numerado (puede llevar "Resultat esperat: ...")
#   [IMATGE: descripción]      -> captura pendiente del paso anterior
#   [Recomanat]                -> paso opcional
SECTION_PATTERN = re.compile(r"^([a-h])\)\s+(.+)$")
NUMBERED_PATTERN = re.compile(r"^\d+[.)]\s+(.*)$")
IMAGE_PATTERN = re.compile(r"^\[IMATGE:\s*(.+?)\]$")
RECOMMENDED_TAG = "[Recomanat]"
EXPECTED_TAG = "Resultat esperat:"


def status(title: str, colour: str) -> str:
    return (
        '<ac:structured-macro ac:name="status" ac:schema-version="1">'
        f'<ac:parameter ac:name="colour">{colour}</ac:parameter>'
        f'<ac:parameter ac:name="title">{escape(title)}</ac:parameter>'
        "</ac:structured-macro>"
    )


def parse_resolution(text: str) -> list[dict]:
    """Separa la resolución en secciones: [{"title", "items": [{"kind", "text", "images"}]}]."""

    sections = []

    for line in (line.strip() for line in text.splitlines()):
        if not line:
            continue

        if match := SECTION_PATTERN.match(line):
            sections.append({"title": match[2].strip().capitalize(), "items": []})
            continue

        if not sections:
            sections.append({"title": "", "items": []})

        items = sections[-1]["items"]

        if match := IMAGE_PATTERN.match(line):
            if not items:
                items.append({"kind": "text", "text": "", "images": []})
            items[-1]["images"].append(match[1])
            continue

        if match := NUMBERED_PATTERN.match(line):
            kind, line = "step", match[1]
        elif line.startswith("- "):
            kind, line = "bullet", line[2:]
        elif items:
            # Continuación de la línea anterior
            items[-1]["text"] += " " + line
            continue
        else:
            kind = "text"

        items.append({"kind": kind, "text": line, "images": []})

    return sections


def item_html(item: dict) -> str:
    """Texto del paso con etiqueta "Recomanat", resultado esperado y capturas pendientes."""

    text = item["text"]
    recommended = RECOMMENDED_TAG in text
    text, _, expected = text.replace(RECOMMENDED_TAG, "").partition(EXPECTED_TAG)

    html = escape(text.strip())
    if recommended:
        html = status("Recomanat", "Blue") + " " + html
    if expected.strip():
        html += f"<br/><em>{EXPECTED_TAG}</em> {escape(expected.strip())}"

    html = f"<p>{html}</p>" if html else ""
    html += "".join(
        f"<p>{status('Captura pendent', 'Yellow')} <em>{escape(image)}</em></p>"
        for image in item["images"]
    )

    return html


def section_html(items: list[dict]) -> str:
    """Pasos seguidos -> <ol>, viñetas seguidas -> <ul>, el resto en párrafos."""

    html = []
    tags = {"step": "ol", "bullet": "ul"}

    for kind, block in groupby(items, key=lambda item: item["kind"]):
        block = list(block)

        if kind in tags:
            html.append(f"<{tags[kind]}>" + "".join(f"<li>{item_html(item)}</li>" for item in block) + f"</{tags[kind]}>")
        else:
            html.extend(item_html(item) for item in block)

    return "".join(html)


def left_column(group: dict, related: list[dict]) -> str:
    """Contenido del elemento recurrente + enlaces a documentación existente."""

    description, _ = split_description(group.get("elemento_recurrente", ""))
    sections = parse_resolution(group.get("resolucion", ""))

    html = ["<h2>Descripció del problema</h2>"]
    html.append(f"<p>{escape(description)}</p>")

    html.append("<h2>Procediment de resolució</h2>")
    if sections:
        for section in sections:
            if section["title"]:
                html.append(f"<h3>{escape(section['title'])}</h3>")
            html.append(section_html(section["items"]))
    else:
        html.append("<p>Sense procediment disponible.</p>")

    html.append("<h2>Documentació relacionada</h2>")
    if related:
        html.append("<p>Pàgines del portal que poden coincidir amb aquesta documentació (revisar abans de publicar):</p>")
        html.append("<ul>" + "".join(
            f'<li><p><a href="{escape(page["url"])}">{escape(page["title"])}</a> ({escape(page["space"])})</p></li>'
            for page in related
        ) + "</ul>")
    else:
        html.append("<p>No s'ha trobat documentació relacionada al portal.</p>")

    return "".join(html)


def create_draft(space_id: str, title: str, html: str) -> dict:

    body = {
        "spaceId": space_id,
        "status": "draft",
        "title": title[:250],
        "parentId": PARENT_ID,
        "body": {"representation": "storage", "value": html},
    }

    r = requests.post(f"{BASE}/api/v2/pages", auth=AUTH, json=body)

    if not r.ok:
        raise RuntimeError(f"Error {r.status_code} al crear '{title}': {r.text[:500]}")

    page = r.json()

    return {"id": page["id"], "url": BASE + page["_links"]["webui"]}


def update_draft(page_id: str, title: str, html: str) -> bool:
    """Sustituye el contenido de un borrador ya creado. False si ya no existe."""

    body = {
        "id": page_id,
        "status": "draft",
        "title": title[:250],
        "body": {"representation": "storage", "value": html},
        "version": {"number": 1},
    }

    r = requests.put(f"{BASE}/api/v2/pages/{page_id}", auth=AUTH, json=body)

    if r.status_code == 404:
        return False

    if not r.ok:
        raise RuntimeError(f"Error {r.status_code} al actualizar '{title}': {r.text[:500]}")

    return True


def main(limit: int | None = None):

    groups = load_groups()[:limit]

    created = {}
    if CREATED_FILE.exists():
        created = json.loads(CREATED_FILE.read_text(encoding="utf-8"))

    space_id = page_space_id(PARENT_ID)

    related = related_by_group(groups)

    for position, (group, pages) in enumerate(zip(groups, related), start=1):
        title = group.get("titulo_propuesto", f"Elemento recurrente {position}")

        html = group_to_html(group, pages)

        if title in created and update_draft(created[title]["id"], title, html):
            print(f"{position:02d}. Actualizado: {title}\n    {created[title]['url']}")
            continue

        # Nuevo, o borrado en Confluence: se crea de nuevo
        page = create_draft(space_id, title, html)
        created[title] = page

        CREATED_FILE.parent.mkdir(parents=True, exist_ok=True)
        CREATED_FILE.write_text(json.dumps(created, ensure_ascii=False, indent=2), encoding="utf-8")

        print(f"{position:02d}. {title}\n    {page['url']}")


if __name__ == "__main__":
    # python -m src.publish_drafts 1  -> solo el primero (para probar)
    main(int(sys.argv[1]) if len(sys.argv) > 1 else None)
