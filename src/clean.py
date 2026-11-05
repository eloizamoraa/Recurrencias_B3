import re
import unicodedata
from functools import lru_cache

import pandas as pd


# Palabras que aparecen en mayúscula en los tickets pero no son
# nombres de persona. Ampliar según lo que salga en el Excel.
TECH_TERMS = {
    "microsoft", "teams", "outlook", "office", "excel", "word",
    "windows", "active", "directory", "azure", "sharepoint",
    "onedrive", "google", "chrome", "global", "protect", "cisco",
    "citrix", "oracle", "java", "adobe", "acrobat", "reader",
    "remedy", "service", "desk", "help",
}

# Columnas del Excel que contienen nombres de persona.
# Se usan como diccionario para anonimizar los textos.
NAME_COLUMNS = ["Customer*+", "Contact+", "Assignee+"]

# Palabras que indican que el valor no es una persona sino un
# departamento, una sede o un puesto ("DEPARTAMENT DE DRETS SOCIALS",
# "DSO OAC-LLEIDA-TAULA-01"...).
NOT_PERSON_WORDS = {
    "departament", "direccio", "general", "espai", "servei", "serveis",
    "oficina", "dso", "taula", "recepcio", "agencia", "consell",
    "institut", "centre", "area", "unitat", "seu", "secretaria",
    "gabinet", "subdireccio", "comissio", "generalitat", "catalunya",
}

# Partículas que no pueden cerrar un nombre ("MARIA DE", "JOAN I")
NAME_PARTICLES = {"de", "del", "la", "las", "los", "i", "y", "d", "l"}

# Separadores permitidos entre las palabras de un nombre
# ("LUCIA M. PEREZ", "JAUME  ARTIGUES", "COL·LET", "PÉREZ-GARCIA")
NAME_GAP = re.compile(r"[ .·'’\-]+")

WORD = re.compile(r"[^\W\d_]+")

# Campos de las plantillas de Remedy cuyo valor es un dato personal.
# Ej: "> Nom de contacte: ABEL VICO BAÑO"
#     "2. Nom i Cognoms de l'usuari afectat: ANNA GALINDO"
PERSONAL_FIELDS = [
    (
        r"nom de contacte|nom i cognoms?[^:\n]*|nom usuari"
        r"|nom d['’]usuari[^:\n]*|usuari amb el que[^:\n]*",
        "[NOMBRE]",
    ),
    (r"dni[^:\n]*|nie", "[DNI]"),
]

# DNI (12345678Z) y NIE (X1234567L)
DNI_PATTERN = re.compile(r"\b[XYZxyz]?\d{7,8}[A-Za-z]\b")


def safe_text(value) -> str:
    """
    Convierte un valor del Excel en texto seguro.

    - NaN -> ""
    - None -> ""
    - El resto -> str
    """
    if value is None:
        return ""

    # pd.isna sobre listas/arrays devuelve un array, no un bool
    if pd.api.types.is_scalar(value) and pd.isna(value):
        return ""

    return str(value).strip()


def clean_spaces(text: str) -> str:
    """
    Normaliza espacios y saltos de línea.
    """
    text = safe_text(text)

    # Saltos de línea de Windows / Mac antiguo -> \n
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # Tabuladores y espacios no separables -> espacio
    text = text.replace("\t", " ").replace("\xa0", " ")

    # Varios espacios consecutivos -> uno
    text = re.sub(r"[ ]+", " ", text)

    # Espacios al inicio y final de cada línea
    text = "\n".join(line.strip() for line in text.split("\n"))

    # Más de dos saltos de línea -> dos
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def clean_summary(summary, known_names=None) -> str:
    """
    Limpia Summary sin eliminar información técnica.

    known_names: diccionario creado con build_known_names().
    """
    text = safe_text(summary)

    if not text:
        return ""

    # Elimina prefijos administrativos (también si se repiten,
    # p. ej. "Tornar a obrir: Tornar a obrir: ...").
    prefix_pattern = (
        r"^(?:\s*(?:tornar\s+a\s+obrir|reobrir|"
        r"volver\s+a\s+abrir|reabrir)\s*[:\-]\s*)+"
    )

    text = re.sub(
        prefix_pattern,
        "",
        text,
        flags=re.IGNORECASE,
    )

    # Datos personales
    text = remove_urls_emails(text)
    text = remove_dni(text)
    text = remove_phones(text)
    text = remove_known_names(text, known_names)
    text = remove_truncated_name(text, known_names)
    text = remove_names(text, known_names)

    return clean_spaces(text)


def normalize_word(word: str) -> str:
    """
    Minúsculas y sin acentos, para comparar nombres:
    "MARTÍN" -> "martin", "Bañó" -> "bano".
    """
    word = unicodedata.normalize("NFKD", word)
    word = "".join(c for c in word if not unicodedata.combining(c))
    return word.lower()


def split_name(name: str) -> tuple[str, ...]:
    """
    "ADELAIDA TOMAS MARTÍN" -> ("adelaida", "tomas", "martin")
    """
    return tuple(normalize_word(w) for w in WORD.findall(name))


def build_known_names(df: pd.DataFrame) -> frozenset:
    """
    Crea el diccionario de nombres de persona a partir de las
    columnas NAME_COLUMNS del Excel (cliente, contacto, técnico).

    Además del nombre completo guardamos "nombre + primer apellido"
    ("ANNA ROSA PÈLACH ROCA" -> también "ANNA ROSA PÈLACH"), porque
    en los textos a veces no aparece el segundo apellido.
    """
    names = set()

    for column in NAME_COLUMNS:
        if column not in df.columns:
            continue

        for value in df[column].dropna().unique():
            words = split_name(str(value))

            # Una sola palabra no es suficiente para ser un nombre
            if len(words) < 2:
                continue

            # Departamentos, sedes, puestos...
            if any(w in NOT_PERSON_WORDS for w in words):
                continue

            names.add(words)

            # Sin el último apellido
            if len(words) >= 3 and words[-2] not in NAME_PARTICLES:
                names.add(words[:-1])

    return frozenset(names)


def remove_known_names(text: str, known_names) -> str:
    """
    Sustituye por [NOMBRE] los nombres del diccionario, sin
    importar mayúsculas ni acentos ("ADELAIDA TOMAS MARTÍN",
    "Adelaida Tomas Martin"...).
    """
    text = safe_text(text)

    if not text or not known_names:
        return text

    max_words = max(len(name) for name in known_names)

    words = list(WORD.finditer(text))
    normalized = [normalize_word(w.group(0)) for w in words]

    # joined[i]: la palabra i y la i+1 solo están separadas por
    # espacios / puntos / guiones (no por saltos de línea, comas...)
    joined = [
        NAME_GAP.fullmatch(text[words[i].end():words[i + 1].start()])
        is not None
        for i in range(len(words) - 1)
    ]

    spans = []
    i = 0

    while i < len(words):
        found = False

        # Probamos primero el nombre más largo posible
        for n in range(min(max_words, len(words) - i), 1, -1):
            if not all(joined[i:i + n - 1]):
                continue

            if tuple(normalized[i:i + n]) in known_names:
                spans.append((words[i].start(), words[i + n - 1].end()))
                i += n
                found = True
                break

        if not found:
            i += 1

    # Sustituimos de derecha a izquierda para no mover las posiciones
    for start, end in reversed(spans):
        text = text[:start] + "[NOMBRE]" + text[end:]

    return text


def remove_personal_fields(text: str) -> str:
    """
    Vacía los campos de plantilla que contienen datos personales.

    "> Nom de contacte: ABEL VICO BAÑO" -> "> Nom de contacte: [NOMBRE]"
    """
    text = safe_text(text)

    if not text:
        return ""

    for label, replacement in PERSONAL_FIELDS:
        text = re.sub(
            rf"^([ \t>\-]*(?:\d+\.\s*)?(?:{label})[ \t]*:)[ \t]*\S[^\n]*",
            rf"\1 {replacement}",
            text,
            flags=re.IGNORECASE | re.MULTILINE,
        )

    return text


def remove_urls_emails(text: str) -> str:
    """
    Sustituye URLs por [URL] y emails por [EMAIL].
    """
    text = safe_text(text)

    if not text:
        return ""

    # URLs (antes que los emails, para no romper URLs con "@")
    text = re.sub(
        r"(?:https?://|www\.)[^\s<>\"']+[^\s<>\"'.,;:!?)\]]",
        "[URL]",
        text,
        flags=re.IGNORECASE,
    )

    # Emails
    text = re.sub(
        r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)*\.[A-Za-z]{2,}\b",
        "[EMAIL]",
        text,
        flags=re.IGNORECASE,
    )

    return text


def remove_dni(text: str) -> str:
    """
    Sustituye DNI y NIE por [DNI].
    """
    text = safe_text(text)

    if not text:
        return ""

    return DNI_PATTERN.sub("[DNI]", text)


@lru_cache(maxsize=4)
def name_words(known_names: frozenset) -> frozenset:
    """
    Todas las palabras (nombres y apellidos) del diccionario:
    {"adelaida", "tomas", "martin", ...}
    """
    return frozenset(
        word
        for name in known_names
        for word in name
        if len(word) >= 3 and word not in NAME_PARTICLES
    )


@lru_cache(maxsize=4)
def first_names(known_names: frozenset) -> frozenset:
    """
    Nombres de pila del diccionario: {"adelaida", "abel", ...}
    """
    return frozenset(
        name[0]
        for name in known_names
        if len(name[0]) >= 3 and name[0] not in NOT_PERSON_WORDS
    )


def remove_truncated_name(text: str, known_names=None) -> str:
    """
    Remedy corta los Summary largos y el nombre queda incompleto:
    "... de MARTA ASCEN..."            -> "... de [NOMBRE]"
    "... de [NOMBRE] FER..."           -> "... de [NOMBRE]"
    "... - 170 W - ALICIA CARD..."     -> "... - 170 W - [NOMBRE]"
    """
    text = safe_text(text)

    if not text:
        return ""

    upper = "A-ZÁÉÍÓÚÀÈÒÏÜÇÑ"
    tail = rf"[{upper} .·'’\-]*\.{{2,}}\s*$"

    # Detrás de "de" o de un nombre ya sustituido
    text = re.sub(rf"\b(de|d')\s*[{upper}]{tail}", r"\1 [NOMBRE]", text)
    text = re.sub(rf"\[NOMBRE\]{tail}", "[NOMBRE]", text)

    # Mayúsculas al final que empiezan por un nombre conocido
    # Exigimos nombre de pila + al menos otra palabra separada por
    # espacio, para no comer rutas ("FITXERS.CTTI.INTRANET...").
    if known_names:
        known_first = first_names(known_names)

        for match in re.finditer(rf"(?:^|(?<=\s))([{upper}]+) [{upper}]", text):
            if (
                normalize_word(match.group(1)) in known_first
                and re.fullmatch(rf"[{upper} ]*\.{{2,}}\s*", text[match.end(1):])
            ):
                text = text[:match.start()] + "[NOMBRE]"
                break

    return text


def remove_names(text: str, known_names=None) -> str:
    """
    Sustituye nombres de persona por [NOMBRE].

    Consideramos nombre a 2 o más palabras seguidas que empiezan
    por mayúscula ("Manuel Garcia", "Maria Puig Soler").
    Una sola palabra en mayúscula no se toca, para no borrar
    palabras al inicio de frase ("Error", "Correu"...).

    Con known_names solo se sustituye si alguna palabra es un nombre
    o apellido conocido. Sin ese filtro se borraban departamentos y
    textos de plantilla ("Direcció General", "One Drive", "Si No"...).
    """
    text = safe_text(text)

    if not text:
        return ""

    word = r"[A-ZÁÉÍÓÚÀÈÒÏÜÇÑ][a-záéíóúàèòïüçñ]+"

    known_words = name_words(known_names) if known_names else None

    def replace(match: re.Match) -> str:
        words = match.group(0).lower().split()

        # Productos / términos técnicos: no son personas
        if any(w in TECH_TERMS for w in words):
            return match.group(0)

        if known_words is not None and not any(
            normalize_word(w) in known_words for w in words
        ):
            return match.group(0)

        return "[NOMBRE]"

    return re.sub(
        rf"\b{word}(?:[ ]+{word})+\b",
        replace,
        text,
    )


def remove_phones(text: str) -> str:
    """
    Sustituye teléfonos españoles (9 dígitos, empiezan por 6-9,
    con prefijo +34 / 0034 opcional y separadores opcionales).
    """
    text = safe_text(text)

    if not text:
        return ""

    text = re.sub(
        r"(?<![\w+])(?:(?:\+|00)34[\s.-]?)?[6789](?:[\s.-]?\d){8}(?!\w)",
        "[TELEFONO]",
        text,
    )

    return text


def clean_notes(notes, known_names=None) -> str:
    """
    Primera versión de limpieza de Notes.

    De momento hacemos una limpieza conservadora.
    Más adelante añadiremos reglas basadas en las
    plantillas reales encontradas en el Excel.

    known_names: diccionario creado con build_known_names().
    """
    text = safe_text(notes)

    if not text:
        return ""

    text = remove_urls_emails(text)

    # Datos personales
    text = remove_personal_fields(text)
    text = remove_dni(text)
    text = remove_phones(text)
    text = remove_known_names(text, known_names)
    text = remove_names(text, known_names)

    return clean_spaces(text)


def build_analysis_text(summary, notes, known_names=None) -> str:
    """
    Construye el texto que posteriormente recibirá el LLM.
    """

    summary_clean = clean_summary(summary, known_names)
    notes_clean = clean_notes(notes, known_names)

    parts = []

    if summary_clean:
        parts.append(summary_clean)

    if notes_clean:
        parts.append(notes_clean)

    return "\n".join(parts)


def clean_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """
    Crea un DataFrame preparado para el análisis de recurrencias.

    Conservamos los campos originales para poder comparar
    siempre el contenido original con el contenido limpio.
    """

    required_columns = [
      "Summary*",
        "Notes*",
        "Assigned Group*+",
        "SRD",
        "Resolution",
        "Service*+",
        "Incident ID*+",
    ]

    # Comprobamos que existen las columnas necesarias
    missing_columns = [
        column
        for column in required_columns
        if column not in df.columns
    ]

    if missing_columns:
        raise ValueError(
            f"Faltan columnas obligatorias: {missing_columns}"
        )

    # Creamos un nuevo DataFrame con el mismo índice.
    # No modificamos el original.
    clean_df = pd.DataFrame(index=df.index)

    # Identificador único del ticket (INC000...). SRD no sirve:
    # contiene textos como "Registre directe".
    clean_df["Ticket_ID"] = df["Incident ID*+"].apply(safe_text)

    clean_df["Summary_original"] = df["Summary*"].apply(safe_text)
    clean_df["Notes_original"] = df["Notes*"].apply(safe_text)

    # Nombres de persona que aparecen en el propio Excel
    known_names = build_known_names(df)

    clean_df["Summary_clean"] = df["Summary*"].apply(
        clean_summary, known_names=known_names
    )
    clean_df["Notes_clean"] = df["Notes*"].apply(
        clean_notes, known_names=known_names
    )

    clean_df["Assigned_Groups"] = df["Assigned Group*+"].apply(
        safe_text
    )
    clean_df["SRD"] = df["SRD"].apply(safe_text)
    # Resolution tiene el mismo tipo de texto libre que Notes
    # (firmas, emails, teléfonos...): misma limpieza.
    clean_df["Resolution_original"] = df["Resolution"].apply(safe_text)
    clean_df["Resolution_clean"] = df["Resolution"].apply(
        clean_notes, known_names=known_names
    )
    clean_df["Service"] = df["Service*+"].apply(safe_text)

    # Unimos los textos ya limpios (sin volver a limpiarlos).
    # Con una lista evitamos el fallo de apply(axis=1)
    # cuando el DataFrame está vacío.
    clean_df["Analysis_text"] = [
        "\n".join(part for part in (summary, notes) if part)
        for summary, notes in zip(
            clean_df["Summary_clean"],
            clean_df["Notes_clean"],
        )
    ]

    return clean_df
