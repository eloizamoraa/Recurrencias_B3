import os
import re
from pathlib import Path
from urllib.parse import unquote

import markdown
import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)

BASE = os.environ["CONFLUENCE_URL"].rstrip("/")
AUTH = (os.environ["CONFLUENCE_EMAIL"], os.environ["CONFLUENCE_TOKEN"])
# Admite una o varias claves separadas por comas. Si se copian de una
# URL de Confluence vienen con "%2C" y un "~" delante: los limpiamos.
SPACES = [k.strip().lstrip("~") for k in unquote(os.environ["CONFLUENCE_SPACES"]).split(",")
          if k.strip()]
# Espacio donde se crean los borradores (por defecto, el primero de la lista)
DRAFT_SPACE = os.environ.get("CONFLUENCE_DRAFT_SPACE", SPACES[0])

SECCIONES = ["Síntomas", "Causa probable", "Resolución paso a paso",
             "Prevención", "Cuándo escalar", "Palabras clave"]


def _get_spaces(keys: list[str]) -> list[dict]:
    r = requests.get(f"{BASE}/api/v2/spaces", auth=AUTH,
                     params={"keys": ",".join(keys), "limit": 250})
    r.raise_for_status()
    return r.json()["results"]


def comprobar_conexion() -> str:
    """Devuelve el nombre de los espacios si las credenciales funcionan."""
    resultados = _get_spaces(SPACES)
    if not resultados:
        raise ValueError(f"No se encuentra ningún espacio de {SPACES} o no tienes acceso.")
    encontrados = {s["key"] for s in resultados}
    faltan = [k for k in SPACES if k not in encontrados]
    if faltan:
        print(f"AVISO: no se encuentran o no tienes acceso a: {faltan}")
    return ", ".join(s["name"] for s in resultados)


def buscar_articulo(palabras_clave: list[str], limite: int = 5) -> list[dict]:
    """Busca páginas del espacio que contengan alguna de las palabras clave."""
    terminos = [p.strip().replace('"', "") for p in palabras_clave if p.strip()]
    texto = " OR ".join(f'text ~ "{t}"' for t in terminos)
    espacios = ", ".join(f'"{k}"' for k in SPACES)
    cql = f'space in ({espacios}) AND type = page AND ({texto})'
    r = requests.get(f"{BASE}/rest/api/search", auth=AUTH,
                     params={"cql": cql, "limit": limite})
    r.raise_for_status()
    return [
        {"titulo": res["content"]["title"],
         "url": BASE + res["content"]["_links"]["webui"],
         "id": res["content"]["id"]}
        for res in r.json().get("results", [])
    ]


def separar_titulo(respuesta: str) -> tuple[str, str]:
    """Devuelve (título, cuerpo en Markdown) a partir de la respuesta de Copilot."""
    lineas = [l.rstrip() for l in respuesta.strip().splitlines()]
    while lineas and not lineas[0].strip():
        lineas.pop(0)
    titulo = lineas[0].lstrip("# ").strip()
    cuerpo = []
    for l in lineas[1:]:
        limpia = l.strip().lstrip("#").strip()
        if limpia in SECCIONES:
            cuerpo.append(f"\n## {limpia}\n")
        elif re.match(r"^(Departamento|Frecuencia):", limpia):
            clave, valor = limpia.split(":", 1)
            cuerpo.append(f"**{clave}:**{valor}  ")
        else:
            cuerpo.append(l)
    return titulo[:250], "\n".join(cuerpo)


def _space_id() -> str:
    r = requests.get(f"{BASE}/api/v2/spaces", auth=AUTH, params={"keys": SPACE})
    r.raise_for_status()
    return r.json()["results"][0]["id"]


def crear_borrador(titulo: str, cuerpo_md: str, parent_id: str | None = None) -> str:
    """Crea la página como BORRADOR. Devuelve la URL para revisarla."""
    html = markdown.markdown(cuerpo_md, extensions=["sane_lists"])
    body = {
        "spaceId": _space_id(),
        "status": "draft",
        "title": titulo,
        "body": {"representation": "storage", "value": html},
    }
    if parent_id:
        body["parentId"] = parent_id
    r = requests.post(f"{BASE}/api/v2/pages", auth=AUTH, json=body)
    if not r.ok:
        raise RuntimeError(f"Error {r.status_code} al crear la página: {r.text[:500]}")
    return BASE + r.json()["_links"]["webui"]