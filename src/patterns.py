"""
Detección de incidencias recurrentes a partir de los patrones de
texto de Summary y Notes (sin LLM).

1. Prepara el texto: quita datos anonimizados, IDs, rutas, firmas,
   avisos legales y líneas de plantilla que se repiten en muchos tickets.
2. Lo convierte en vectores TF-IDF (palabras + parejas de palabras,
   con stemming para unir singular/plural).
3. Agrupa tickets parecidos (HDBSCAN), fusiona los grupos cuyo
   contenido es casi igual y asigna a cada grupo los tickets sueltos
   que se le parecen lo suficiente.
4. Ordena los grupos por número de tickets y genera el top.
"""

import collections
import re
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd
from nltk.stem.snowball import SnowballStemmer
from sklearn.cluster import HDBSCAN, AgglomerativeClustering
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import normalize


# --------------------------------------------------
# RUTAS Y PARÁMETROS
# --------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent

INPUT_FILE = PROJECT_ROOT / "data" / "processed" / "tickets_clean.xlsx"

OUTPUT_DIR = PROJECT_ROOT / "data" / "results"

OUTPUT_FILE = OUTPUT_DIR / "top_recurrencias.xlsx"

TOP_N = 10

# El Summary es lo más informativo: pesa más que las notas
SUMMARY_WEIGHT = 3
MAX_NOTES_CHARS = 1500

# Tamaño mínimo de un grupo para considerarlo recurrente
MIN_CLUSTER_SIZE = 15

# Dos grupos se fusionan si la distancia coseno entre sus
# centroides es menor que este valor (0 = idénticos, 1 = nada que ver)
MERGE_DISTANCE = 0.55

# Un ticket suelto se asigna a un grupo si se parece al menos esto
ASSIGN_SIMILARITY = 0.55

# Los patrones se agrupan en temas ("reset mfa", "codi mfa", "mfa
# desktop" -> tema MFA) si TODOS se parecen al menos esto entre sí
THEME_DISTANCE = 0.8

RANDOM_STATE = 42


# --------------------------------------------------
# VOCABULARIO
# --------------------------------------------------

# Palabras sin significado para agrupar (catalán / castellano)
# y frases típicas de los técnicos ("Rebem trucada indicant...").
STOP_WORDS = """
de la el els les i y a en per amb que del al als un una uns unes es no o ho li
em et ens us hi se si ja ha han he hem heu va van ser esta estan aquest aquesta
aquests aquestes aquell seu seva seus seves meu meva nostre vostra mes molt tot
tots tota totes com quan on qui perque pero pel pels sobre fins des entre dia bon
bona tarda mati gracies salutacions cordials atentament los las lo por para con
este esta estos estas ese esa su sus mi mis le les nos muy pero porque como cuando
donde quien hay gracias saludos buenos buenas dias tardes rebem trucada truca
indicant indiquen comenta resolta setembre octubre agost juliol usuari usuaria
usuario indica nom contacte telefon dades adreca correu consulta incidencia
peticio sol licitud resolucio tiquet ticket favor hola
""".split()

# Formas distintas de decir lo mismo -> una sola
SYNONYMS = {
    r"\bone\s*drive\b": "onedrive",
    r"\b(duo|doble factor|multifactor|autenticaci[oó] multifactor)\b": "mfa",
    r"\b(contrase[ñn]a|password|paraula de pas)\b": "contrasenya",
    r"\bimpresora": "impressora",
    r"\b(ordenador|pc)\b": "ordinador",
    r"\bcorreo\b": "correu",
    r"\b(b[uú]stia|buz[oó]n)\b": "bustia",
}

# Inicio de firmas, avisos legales y correos reenviados.
# Todo lo que viene detrás se descarta.
CUT_PATTERN = re.compile(
    r"aquest missatge|este mensaje|av[ií]s legal|aviso legal"
    r"|abans d.imprimir|antes de imprimir|facebook|twitter|linkedin"
    r"|^\s*(?:de|from|enviat|enviado)\s*:\s|-{5,}"
    # Despedidas
    r"|^\s*(?:salutacions|atentament|cordialment|saludos|un saludo"
    r"|un cordial saludo|una salutaci[oó]|ben cordialment)\b"
    # Líneas de firma: organismo o dirección postal
    r"|^\s*(?:direcci[oó] general|subdirecci[oó] general|secretaria (?:de|general)"
    r"|gabinet|c/|carrer|avinguda|av\.|passeig|pg\.|pla[cç]a|tel\.|telf|tlf)",
    flags=re.IGNORECASE | re.MULTILINE,
)

# Una línea que aparece en este número de tickets o más...
BOILERPLATE_MIN_TICKETS = 15
BOILERPLATE_MIN_CHARS = 40   # ...y es larga -> texto de plantilla
SIGNATURE_MIN_TICKETS = 10   # ...y no es "campo: valor" -> firma

stemmer = SnowballStemmer("spanish")


def strip_accents(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if not unicodedata.combining(c))


def normalize_text(text: str) -> str:
    """
    Minúsculas, sinónimos unificados y sin datos variables
    ([NOMBRE], IDs, rutas, números...).
    """
    text = str(text).lower()

    # "instal·lació" -> "installació" (si no, se parte en dos palabras)
    text = re.sub(r"l[·.]l", "ll", text)

    text = re.sub(r"\[(nombre|email|url|telefono|dni)\]|###", " ", text)

    # Rutas de red / unidades y cualquier palabra con números
    # (INC000..., LT2BA30010, 0301_EIFBCN001W...)
    text = re.sub(r"\\\\\S+|[a-z]:\\\S*|\S*\d\S*", " ", text)

    for pattern, replacement in SYNONYMS.items():
        text = re.sub(pattern, replacement, text)

    return re.sub(r"\s+", " ", text).strip()


def split_note_lines(notes: str) -> list[tuple[str, bool]]:
    """
    Separa Notes en líneas útiles.

    Devuelve (texto, es_campo). En las líneas "Etiqueta: valor" de
    las plantillas nos quedamos solo con el valor.
    """
    match = CUT_PATTERN.search(notes)

    if match:
        notes = notes[:match.start()]

    lines = []

    for line in notes.splitlines():
        line = line.strip(" >-()·*")
        is_field = False

        if ":" in line:
            label, value = line.split(":", 1)

            if len(label) < 90:
                line = value
                is_field = True

        line = line.strip()

        if line:
            lines.append((line, is_field))

    return lines


def build_texts(df: pd.DataFrame) -> pd.Series:
    """
    Texto final de cada ticket: Summary (con más peso) + Notes
    sin líneas de plantilla ni firmas.
    """
    note_lines = df["Notes_clean"].fillna("").astype(str).map(split_note_lines)

    # En cuántos tickets aparece cada línea
    frequency = collections.Counter(
        normalize_text(line)
        for lines in note_lines
        for line in {text for text, _ in lines}
    )

    def is_noise(line: str, is_field: bool) -> bool:
        times = frequency[line]

        if times >= BOILERPLATE_MIN_TICKETS and len(line) >= BOILERPLATE_MIN_CHARS:
            return True

        return not is_field and times >= SIGNATURE_MIN_TICKETS

    def notes_text(lines) -> str:
        kept = []

        for text, is_field in lines:
            text = normalize_text(text)

            if text and not is_noise(text, is_field):
                kept.append(text)

        return " ".join(kept)[:MAX_NOTES_CHARS]

    summary = df["Summary_clean"].fillna("").astype(str).map(normalize_text)

    return (summary + " ") * SUMMARY_WEIGHT + note_lines.map(notes_text)


# --------------------------------------------------
# VECTORIZACIÓN
# --------------------------------------------------

STOP_SET = {strip_accents(w) for w in STOP_WORDS}

# Para mostrar palabras legibles en lugar de raíces ("impressor")
stem_examples: dict[str, collections.Counter] = collections.defaultdict(
    collections.Counter
)


def tokenize(text: str) -> list[str]:
    """
    Palabras de 3+ letras, sin acentos, sin stop words y con stemming
    ("impressores" -> "impressor"). Incluye parejas de palabras.
    """
    words = re.findall(r"[^\W\d_]{3,}", strip_accents(text))
    words = [w for w in words if w not in STOP_SET]

    stems = []

    for word in words:
        stem = stemmer.stem(word)
        stem_examples[stem][word] += 1
        stems.append(stem)

    return stems + [f"{a} {b}" for a, b in zip(stems, stems[1:])]


def vectorize(texts: pd.Series):
    vectorizer = TfidfVectorizer(
        tokenizer=tokenize,
        token_pattern=None,
        lowercase=False,
        min_df=3,
        max_df=0.15,
        sublinear_tf=True,
    )

    X = vectorizer.fit_transform(texts)

    # Reducimos a 150 dimensiones ("temas") para que la similitud
    # capture palabras relacionadas y no solo idénticas
    svd = TruncatedSVD(150, random_state=RANDOM_STATE)
    Z = normalize(svd.fit_transform(X))

    return X, Z, vectorizer.get_feature_names_out()


# --------------------------------------------------
# AGRUPACIÓN
# --------------------------------------------------

def cluster(Z: np.ndarray) -> np.ndarray:
    """
    Devuelve el grupo de cada ticket (-1 = no recurrente).
    """
    # 1. Grupos densos de tickets muy parecidos
    labels = HDBSCAN(
        min_cluster_size=MIN_CLUSTER_SIZE,
        min_samples=5,
        copy=True,
    ).fit_predict(Z)

    # Ignoramos grupos de tickets sin texto (vector vacío)
    groups = [
        k for k in np.unique(labels[labels >= 0])
        if np.linalg.norm(Z[labels == k].mean(0)) > 1e-6
    ]

    # 2. Fusionamos grupos casi iguales ("reset mfa" / "mfa no funciona")
    centroids = normalize(np.vstack([Z[labels == k].mean(0) for k in groups]))

    merged = AgglomerativeClustering(
        n_clusters=None,
        metric="cosine",
        linkage="average",
        distance_threshold=MERGE_DISTANCE,
    ).fit_predict(centroids)

    final = np.full(len(labels), -1)

    for group, new_group in zip(groups, merged):
        final[labels == group] = new_group

    # 3. Asignamos los tickets sueltos al grupo más parecido
    centroids = normalize(
        np.vstack([Z[final == g].mean(0) for g in range(merged.max() + 1)])
    )

    similarity = Z @ centroids.T
    best = similarity.argmax(1)

    loose = (final < 0) & (similarity.max(1) >= ASSIGN_SIMILARITY)
    final[loose] = best[loose]

    return final


def group_themes(Z: np.ndarray, labels: np.ndarray) -> np.ndarray:
    """
    Agrupa los patrones en temas. Devuelve el tema de cada ticket.

    Usamos enlace "complete": un patrón entra en un tema solo si se
    parece a todos los del tema (evita cadenas A~B~C con A y C distintos).
    """
    groups = np.unique(labels[labels >= 0])
    centroids = normalize(np.vstack([Z[labels == g].mean(0) for g in groups]))

    themes_of_groups = AgglomerativeClustering(
        n_clusters=None,
        metric="cosine",
        linkage="complete",
        distance_threshold=THEME_DISTANCE,
    ).fit_predict(centroids)

    themes = np.full(len(labels), -1)

    for group, theme in zip(groups, themes_of_groups):
        themes[labels == group] = theme

    return themes


# --------------------------------------------------
# RESUMEN DE CADA GRUPO
# --------------------------------------------------

def readable(term: str) -> str:
    """'impressor configuracio' -> 'impressora configuracio'"""
    return " ".join(
        stem_examples[stem].most_common(1)[0][0] if stem_examples[stem] else stem
        for stem in term.split()
    )


def top_values(series: pd.Series, n: int = 3) -> str:
    counts = series.replace("", np.nan).dropna().value_counts()
    total = counts.sum()

    return "; ".join(
        f"{value} ({count / total:.0%})"
        for value, count in counts.head(n).items()
    )


def describe_groups(df, X, Z, terms, labels, name="Patrón") -> pd.DataFrame:
    """
    Una fila por grupo (patrón o tema) con su tamaño, palabras clave,
    ejemplos, resoluciones y grupos de soporte.
    """
    rows = []

    for group in np.unique(labels[labels >= 0]):
        idx = np.where(labels == group)[0]

        # Palabras más características del grupo
        weights = np.asarray(X[idx].mean(0)).ravel()
        keywords = [readable(t) for t in terms[weights.argsort()[::-1][:8]]]

        # Tickets más representativos (los más cercanos al centro)
        centroid = normalize(Z[idx].mean(0, keepdims=True))
        closest = idx[np.argsort(-(Z[idx] @ centroid.T).ravel())]

        group_df = df.iloc[idx]

        # "Incidència programa de [NOMBRE]" -> "incidència programa"
        summaries = (
            group_df["Summary_clean"]
            .map(normalize_text)
            .str.replace(r"^(re|rv|fw|fwd)\s*:\s*", "", regex=True)
            .str.replace(r"(\s+(de|per a|per|a))+\s*$", "", regex=True)
            .str.strip(" -:.,;")
        )

        rows.append({
            name: int(group),
            "Tickets": len(idx),
            "% del total": round(100 * len(idx) / len(df), 1),
            "Patrón más repetido": summaries.replace("", np.nan).mode().iat[0]
            if summaries.str.len().gt(0).any() else "",
            "Palabras clave": ", ".join(dict.fromkeys(keywords)),
            "Ejemplos (Summary)": "\n".join(
                df["Summary_clean"].iloc[closest[:5]]
            ),
            "Resoluciones ejemplo": "\n---\n".join(
                df["Resolution_clean"].iloc[closest[:3]].str[:400]
            ),
            "Grupos asignados": top_values(group_df["Assigned_Groups"]),
            "Servicio": top_values(group_df["Service"]),
            "Ticket_IDs": ", ".join(df["Ticket_ID"].iloc[closest]),
        })

    return (
        pd.DataFrame(rows)
        .sort_values("Tickets", ascending=False)
        .reset_index(drop=True)
    )


def main():

    print("=" * 60)
    print("DETECCIÓN DE INCIDENCIAS RECURRENTES (PATRONES DE TEXTO)")
    print("=" * 60)

    print("\n1. Leyendo tickets...")

    df = pd.read_excel(INPUT_FILE, engine="calamine").fillna("")
    df = df.astype({c: str for c in df.columns})

    print(f"   Tickets: {len(df)}")

    print("\n2. Preparando textos (quitando plantillas y firmas)...")

    texts = build_texts(df)

    print("\n3. Vectorizando...")

    X, Z, terms = vectorize(texts)

    print(f"   Vocabulario: {len(terms)} términos")

    print("\n4. Agrupando (puede tardar ~1 minuto)...")

    labels = cluster(Z)
    themes = group_themes(Z, labels)

    grouped = (labels >= 0).sum()

    print(f"   Patrones: {labels.max() + 1}")
    print(f"   Temas: {themes.max() + 1}")
    print(f"   Tickets agrupados: {grouped} ({grouped / len(df):.0%})")

    print("\n5. Resumiendo...")

    patterns = describe_groups(df, X, Z, terms, labels, name="Patrón")
    topics = describe_groups(df, X, Z, terms, themes, name="Tema")

    # Patrón -> tema
    pattern_theme = dict(zip(labels, themes))
    patterns.insert(1, "Tema", patterns["Patrón"].map(pattern_theme))

    # Subpatrones de cada tema: "reset mfa (126) / mfa (66) / ..."
    topics.insert(
        4,
        "Subpatrones",
        topics["Tema"].map(
            lambda theme: " / ".join(
                f"{row['Patrón más repetido']} ({row['Tickets']})"
                for _, row in patterns[patterns["Tema"] == theme].iterrows()
            )
        ),
    )

    tickets = df[["Ticket_ID", "Summary_clean", "Assigned_Groups", "Service"]].copy()
    tickets["Patrón"] = labels
    tickets["Tema"] = themes

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    with pd.ExcelWriter(OUTPUT_FILE) as writer:
        topics.head(TOP_N).to_excel(writer, sheet_name=f"Top {TOP_N}", index=False)
        topics.to_excel(writer, sheet_name="Temas", index=False)
        patterns.to_excel(writer, sheet_name="Patrones", index=False)
        tickets.to_excel(writer, sheet_name="Tickets", index=False)

    print(f"   Archivo: {OUTPUT_FILE}")

    print("\n" + "=" * 60)
    print(f"TOP {TOP_N} INCIDENCIAS RECURRENTES")
    print("=" * 60)

    for rank, row in topics.head(TOP_N).iterrows():
        print(
            f"\n{rank + 1:>2}. {row['Tickets']} tickets "
            f"({row['% del total']}%) - {row['Patrón más repetido']}"
        )
        print(f"    Subpatrones: {row['Subpatrones']}")
        print(f"    Palabras clave: {row['Palabras clave']}")
        print(f"    Grupos: {row['Grupos asignados']}")


if __name__ == "__main__":
    main()
