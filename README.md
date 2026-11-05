# Recurrencia de incidencias B3

Detectar incidencias recurrentes en los tickets del Service Desk (export de Remedy en Excel),
agruparlas con un LLM y generar borradores de artículos de conocimiento en Confluence.

**Flujo actual (funcional desde el 05/11/2026):**

```
Excel Remedy ──► limpieza / anonimización ──► lotes JSON
             ──► flujo Power Automate (agrupa y redacta resolución) ──► data/top10/*.json
             ──► borradores en Tot (Confluence)  +  PDFs de documentación
```

Primera versión funcional: el top 10 de recurrencias se publica como borradores en Tot
(`totgencat.atlassian.net`), colgando de la página `2485125311`. Lista de borradores creados
en `data/docs/confluence_drafts.json`.

> Todos los comandos se lanzan **desde la raíz del proyecto** (los scripts usan `from src...`
> y rutas relativas a `data/`).

### Uso rápido (flujo completo)

```powershell
python -m src.process           # 1. Excel Remedy -> tickets_clean.xlsx
python -m src.prepare_batches   # 2. muestra de 500 -> data/batches/batch_XXX.json
python -m src.send_batches      # 3. lotes -> flujo Power Automate -> data/top10/top10_batch_XXX.json
python -m src.publish_drafts    # 4. top 10 -> borradores en Tot (Confluence)
python -m src.build_docs        # (opcional) top 10 -> PDFs en data/docs/
```

---

## Estado actual (revisado 05/11/2026)

| # | Paso | Script | Estado |
|---|------|--------|--------|
| 0 | Entorno y dependencias | `.requirements.txt` | ✅ Hecho (faltan paquetes en el fichero) |
| 1 | Explorar el Excel de entrada | `src/input.py` | ✅ Hecho |
| 2 | Funciones de limpieza + pruebas | `src/clean.py`, `tests/test_clean.py` | ✅ Hecho (mejorable) |
| 3 | Generar Excel limpio | `src/process.py` | ✅ Hecho |
| 4 | Muestra de 500 tickets en 5 lotes | `src/prepare_batches.py` | ✅ Hecho (`Ticket_ID` y anonimización resueltos) |
| 4b | Top 10 recurrencias por patrones de texto (sin LLM) | `src/patterns.py` | ✅ Hecho (04/11) |
| 5 | Prompt + esquema de salida del LLM | `prompts/classify_tickets.txt`, `src/models.py` | ✅ Hecho (no se usa en el flujo actual) |
| 6 | Agrupar lotes y obtener top 10 | `src/send_batches.py` (flujo Power Automate) | ✅ Funciona (por ahora solo `top10_batch_001.json`) |
| 6b | PDFs de documentación del top 10 | `src/build_docs.py` | ✅ Hecho |
| 6c | Borradores del top 10 en Tot (Confluence) | `src/publish_drafts.py` | ✅ **Funciona** (05/11): 10 borradores creados |
| 7 | Prueba del flujo de Copilot Studio | `tests/test_flujo.py` | ✅ Probado |
| 8 | Módulo genérico de Confluence | `src/confluence.py`, `tests/test_confluence.py` | 🟡 Conexión y búsqueda OK; `crear_borrador` tiene un bug (no lo usa el flujo actual) |
| 9 | Orquestación en un solo comando | — | ❌ Sin empezar (de momento se lanzan los scripts en orden) |

---

## Estructura

```
.env                         Credenciales (NO subir a git)
.requirements.txt            Dependencias
data/
  input/recurrencies_exemple_sept.xlsx   Export de Remedy (septiembre, ~8.500 tickets)
  processed/tickets_clean.xlsx           Salida del paso 3
  processed/sample_500.xlsx              Salida del paso 4
  batches/batch_001..005.json            Salida del paso 4 (100 tickets por lote)
  top10/top10_batch_XXX.json             Respuesta del flujo de Power Automate (paso 6)
  docs/confluence_drafts.json            Borradores creados en Tot (título -> id, url)
  docs/*.pdf                             PDFs del top 10 (paso 6b)
prompts/classify_tickets.txt  Prompt de sistema para clasificar tickets
src/
  input.py            Paso 1: inspección del Excel
  clean.py            Paso 2: limpieza y anonimización
  process.py          Paso 3: Excel original -> tickets_clean.xlsx
  prepare_batches.py  Paso 4: muestra + lotes JSON
  patterns.py         Paso 4b: top 10 por similitud de texto (sin LLM)
  models.py           Paso 5: modelos Pydantic de la respuesta del LLM
  send_batches.py     Paso 6: envía los lotes al flujo de Power Automate
  build_docs.py       Paso 6b: PDFs del top 10
  publish_drafts.py   Paso 6c: borradores del top 10 en Tot (Confluence)
  confluence.py       Paso 8: conexión, búsqueda y utilidades de Confluence
tests/
  test_clean.py       Prueba manual de las funciones de limpieza
  test_flujo.py       Prueba del flujo HTTP de Copilot Studio
  test_confluence.py  Prueba de conexión/búsqueda en Confluence
```

---

## Paso 0 — Entorno

Python 3.13. Las dependencias están instaladas en el Python global (no hay entorno virtual).

```powershell
pip install -r .requirements.txt
# No están en el fichero pero se usan:
pip install python-calamine markdown requests azure-identity
```

Variables necesarias en `.env`:

| Variable | Uso |
|----------|-----|
| `FLOW_URL_BATCHES` | URL HTTP del flujo de Power Automate que recibe los lotes (`src/send_batches.py`) |
| `COPILOT_FLOW_URL` | URL HTTP del flujo "Recurrencias B3 - API and Response" (`tests/test_flujo.py`). ⚠️ En el `.env` actual se llama `COPILOT_FLOW_URL_Documentacio`: renombrar una de las dos para que coincidan |
| `CONFLUENCE_URL` | URL base de Confluence (`https://xxx.atlassian.net/wiki`) |
| `CONFLUENCE_EMAIL` / `CONFLUENCE_TOKEN` | Usuario y API token de Atlassian |
| `CONFLUENCE_SPACES` | Clave(s) de espacio separadas por comas (se aceptan copiadas de la URL) |
| `CONFLUENCE_PARENT_ID` | Página padre donde colgar los borradores (⚠️ `publish_drafts.py` no la lee: usa `PARENT_ID = "2485125311"` fijo en el código) |
| `CONFLUENCE_DRAFT_SPACE` | (Opcional) Espacio para borradores. Por defecto, el primero de `CONFLUENCE_SPACES` |

## Paso 1 — Explorar el Excel

Muestra columnas, comprueba que existen las necesarias (`Summary*`, `Notes*`,
`Assigned Group*+`, `SRD`, `Resolution`), cuenta vacíos y enseña 3 ejemplos.

```powershell
python src/input.py
```

> Si sale `PermissionError: [Errno 13] Permission denied` es que el Excel está abierto en
> Excel (o OneDrive lo está sincronizando). Ciérralo y vuelve a lanzar el comando.

## Paso 2 — Limpieza (`src/clean.py`)

- `clean_summary`: quita prefijos "Tornar a obrir:", "Reabrir:"…, teléfonos y nombres.
- `clean_notes`: sustituye URLs → `[URL]`, emails → `[EMAIL]`, teléfonos → `[TELEFONO]`, nombres → `[NOMBRE]`.
- `remove_names`: 2+ palabras seguidas en *Mayúscula Inicial*, salvo términos técnicos (`TECH_TERMS`).
- `build_known_names` + `remove_known_names`: diccionario de personas sacado de las columnas
  `Customer*+`, `Contact+` y `Assignee+` del propio Excel. Detecta esos nombres en cualquier
  formato (MAYÚSCULAS, con o sin acentos, sin el segundo apellido).
- `remove_personal_fields`: vacía campos de plantilla como "Nom de contacte:", "Nom i Cognoms…:",
  "Nom d'usuari…:" y "DNI…:".
- `remove_dni`: DNI / NIE → `[DNI]`.
- `clean_dataframe`: genera `Summary_clean`, `Notes_clean`, `Resolution_clean` (misma limpieza
  que Notes), `Service`, `Analysis_text`… conservando los `*_original`.

Prueba rápida:

```powershell
python -m tests.test_clean
```

## Paso 3 — Generar el Excel limpio

```powershell
python -m src.process
```

Salida: `data/processed/tickets_clean.xlsx` (8.558 tickets en la última ejecución) y 5 ejemplos
original vs. limpio por pantalla.

## Paso 4 — Muestra y lotes

Coge 500 tickets aleatorios (`random_state=42`), los guarda en `sample_500.xlsx` para auditar
y los divide en lotes de 100 en `data/batches/`.

```powershell
python -m src.prepare_batches
```

> Lee `data/processed/tickets_clean.xlsx`: ciérralo en Excel antes (si no, `PermissionError`).

Cada lote: `{"batch_id", "ticket_count", "tickets": [{"ticket_id", "summary", "notes"}]}`.

## Paso 4b — Top 10 por patrones de texto (sin LLM)

Agrupa los 8.558 tickets por similitud de texto de Summary + Notes, en local:

1. Limpia el texto: quita `[NOMBRE]`, IDs, rutas, palabras con números, firmas de correo,
   avisos legales y líneas de plantilla que se repiten en muchos tickets. Unifica sinónimos
   (`duo` → `mfa`, `one drive` → `onedrive`…).
2. TF-IDF (palabras + parejas, con stemming para unir singular/plural) → 150 dimensiones (SVD).
3. HDBSCAN encuentra grupos densos → se fusionan los casi iguales → los tickets sueltos se
   asignan al grupo más parecido. Resultado: **patrones** (~96).
4. Los patrones se agrupan en **temas** (~69): p. ej. tema MFA = "reset mfa" + "codi mfa" +
   "error mfa" + "mfa desktop".

```powershell
python -m src.patterns     # ~2 minutos
```

Salida: `data/results/top_recurrencias.xlsx` con las hojas *Top 10*, *Temas*, *Patrones*
(con número de tickets, palabras clave, ejemplos, resoluciones, grupos asignados, servicio e
IDs de ticket) y *Tickets* (patrón y tema de cada ticket).

Parámetros ajustables al inicio del script: `MIN_CLUSTER_SIZE`, `MERGE_DISTANCE`,
`ASSIGN_SIMILARITY`, `THEME_DISTANCE` (más bajo = temas más pequeños y separados),
`SYNONYMS` y `STOP_WORDS`.

Limitaciones conocidas: algunos temas son genéricos porque el ticket solo trae la categoría
del formulario ("Incidència amb perifèric/altres funcionament incorrecte", "Error en
programari"), y alguno mezcla cosas que solo comparten "no puc accedir" (correo + e-SPRIU).

## Paso 5 — Prompt y esquema

- `prompts/classify_tickets.txt`: reglas de clasificación (category_key estable en inglés
  snake_case, título en español, no agrupar solo por tecnología, `requires_review` si falta info…).
- `src/models.py`: `TicketClassification` / `BatchClassification` (Pydantic) para usar como
  *structured output* del LLM.

## Paso 6 — Agrupar los lotes con el flujo de Power Automate ✅

```powershell
python -m src.send_batches
```

Envía cada `data/batches/batch_XXX.json` al flujo de `FLOW_URL_BATCHES` (con token de
Microsoft, como el paso 7) y guarda la respuesta en `data/top10/top10_batch_XXX.json`
(campos: `tickets_procesados` y `grupos` con `elemento_recurrente`, `apariciones`,
`titulo_propuesto`, `service`, `srd`, `resolucion`). Si el flujo devuelve 502, revisar el
historial de ejecuciones en Power Automate (suele ser timeout: bajar `BATCH_SIZE`).

> Alternativa no implementada: un `src/classify.py` que llame directamente a Azure OpenAI con
> el prompt del paso 5 y `response_format=BatchClassification`. Necesitaría las variables de
> Azure OpenAI en `.env` (endpoint, key, deployment).

### Paso 6b — Documentación en PDF del top 10

```powershell
python -m src.build_docs
```

Lee todos los `data/top10/top10_*.json`, ordena los elementos por `apariciones` y genera en
`data/docs/`:

- un PDF por elemento (`01_<titulo>.pdf`, `02_...`): ficha (apariciones, servicio, SRD,
  fecha), descripción del problema, procedimiento de resolución numerado y tickets relacionados;
- `top10_documentacion.pdf`: portada con el índice + todos los elementos.

Usa `reportlab` y la fuente Arial de Windows (para acentos y `l·l`).

### Paso 6c — Borradores del top 10 en Tot (Confluence) ✅

```powershell
python -m src.publish_drafts      # todos
python -m src.publish_drafts 1    # solo el primero (prueba)
```

Crea un borrador (status `draft`) por elemento del top 10 como hijo de la página `PARENT_ID`
(2485125311, en el espacio personal), con el formato de las páginas de servicio:

- columna izquierda (en catalán, como la resolución del flujo): descripción del problema,
  apariciones y procedimiento de resolución con un `h3` por sección (`a) Diagnòstic inicial`,
  `b) Passos de resolució`, `c) Verificació final`, `d) Escalat`). Los pasos numerados van en
  lista numerada y las líneas `- ` en viñetas; `Resultat esperat:` se muestra en cursiva,
  `[Recomanat]` como etiqueta azul y cada `[IMATGE: ...]` como etiqueta amarilla
  "Captura pendent" con la descripción de la captura que falta. Al final, documentación
  existente relacionada del portal;
- columna derecha: índice "En aquesta pàgina" (macro `toc`) y los dos paneles de Remedy con
  Service y SRD rellenados (SRD "Sense assignar" se deja vacío) y el resto **vacío** para
  rellenarlo a mano.

Lo creado se guarda en `data/docs/confluence_drafts.json`. Al relanzar, los borradores que
existen se **sobrescriben** (se pierden las ediciones manuales) y los que se han borrado en
Confluence se vuelven a crear.

Última ejecución (05/11/2026): 10 borradores creados correctamente en Tot:

1. Microsoft Authenticator no genera o no accepta codi MFA
2. Monitor extern USB-C no detecta el portàtil
3. Unitats de xarxa no apareixen o no s'obren
4. Punt de xarxa del lloc sense connexió per cable
5. DUO no valida l'accés a la VPN
6. Auriculars no funcionen a Teams
7. Ordinador es penja i cal reiniciar-lo
8. Rainbow no s'obre ni permet trucar
9. Configuració d'escàner sol·licitada pel canal d'incidències
10. Accés a bústia compartida requereix delegació de permisos

> ⚠️ Si alguien edita un borrador a mano en Tot, **no relanzar** `publish_drafts` sin borrar
> antes su entrada de `confluence_drafts.json`, o se perderán los cambios.

## Paso 7 — Flujo de Copilot Studio

Envía un tema de ejemplo (tema, departamento, nº tickets, ejemplos) al flujo y devuelve el
texto del artículo. La primera vez abre el navegador para iniciar sesión con Microsoft
(el token queda cacheado como `recurrencias_b3`).

```powershell
python tests/test_flujo.py
```

## Paso 8 — Módulo genérico de Confluence

```powershell
python -m tests.test_confluence
```

1. Comprueba credenciales y espacios.
2. Busca artículos existentes por palabras clave (para no duplicar).
3. Crear borrador: comentado en el test hasta arreglar el bug de `_space_id` (ver abajo).
   Necesita un fichero `tests/respuesta_ejemplo.txt` con una respuesta de Copilot
   (se puede sacar de la salida del paso 7).

`separar_titulo` convierte la respuesta de Copilot (secciones *Síntomas, Causa probable,
Resolución paso a paso, Prevención, Cuándo escalar, Palabras clave*) a Markdown, y
`crear_borrador` la publica como página en estado **draft**.

## Paso 9 — Orquestación ❌ PENDIENTE

Un único comando que encadene `process` → `prepare_batches` → `send_batches` →
`publish_drafts` (y opcionalmente `build_docs`), comprobando antes en Tot si ya existe un
artículo para cada elemento del top 10 para no duplicar.

---

## Pendientes / problemas detectados

### Resueltos

- ~~`prepare_batches.py` falla por falta de `Ticket_ID`~~ ✅ 04/11: `Ticket_ID` sale de
  `Incident ID*+` (único, nunca vacío). `SRD` no sirve como identificador.
- ~~Anonimización de nombres en mayúsculas y DNI~~ ✅ 04/11. `remove_names` (Mayúscula
  Inicial) solo actúa si alguna palabra es un nombre/apellido conocido, y
  `remove_truncated_name` cubre los Summary cortados por Remedy ("de MARTA ASCEN...").
- ~~Lotes antiguos sin anonimizar / Excel de entrada más nuevo que `tickets_clean.xlsx`~~ ✅
  05/11: `tickets_clean.xlsx`, `sample_500.xlsx` y los 5 lotes regenerados.
- ~~`process.py` imprime dos veces el bloque "3. Validando resultado"~~ ✅
- ~~Copia suelta de `tickets_clean.xlsx` en la raíz~~ ✅ Eliminada.
- ~~No es repositorio git~~ ✅ 05/11: repo en GitHub (`eloizamoraa/Recurrencias_B3`).
- ~~Publicar el top 10 en Confluence~~ ✅ 05/11: 10 borradores en Tot.

### Abiertos

1. **`.env` está subido a git (con el token de Confluence).** Falta un `.gitignore`
   (`.env`, `__pycache__/`, `data/`). Además de añadirlo, quitar `.env` del repo
   (`git rm --cached .env`) y **regenerar el token de Atlassian**, porque sigue en el historial.
   Lo mismo aplica a los Excel y JSON de `data/`, que contienen tickets reales.
2. Solo se ha procesado `batch_001` en `data/top10/`: lanzar `send_batches` con los 5 lotes
   y revisar que el top 10 combinado tiene sentido.
3. **Bug en `confluence.py`**: `_space_id()` usa `SPACE`, que no existe; debería usar
   `DRAFT_SPACE`. Tampoco se usa `CONFLUENCE_PARENT_ID` al crear el borrador. No afecta al
   flujo actual (`publish_drafts.py` tiene su propio código de creación).
4. `publish_drafts.py` tiene `PARENT_ID` fijo en el código: leerlo de `CONFLUENCE_PARENT_ID`.
5. `tests/test_flujo.py` lee `COPILOT_FLOW_URL` pero en `.env` la variable se llama
   `COPILOT_FLOW_URL_Documentacio`.
6. Quedan nombres sueltos que no están en las columnas de personas (p. ej. firmas en
   mayúsculas al final de las notas).
7. `.requirements.txt`: repite `pydantic` y le faltan `python-calamine`, `markdown`,
   `requests` y `azure-identity`. (Convendría renombrarlo a `requirements.txt`.)

### Siguientes pasos recomendados

```powershell
# 1. Seguridad: .gitignore + sacar .env del repo + regenerar token de Atlassian
# 2. Procesar los 5 lotes y volver a publicar
python -m src.send_batches
python -m src.publish_drafts
# 3. Revisar los borradores en Tot y completar a mano los paneles de Remedy
# 4. Paso 9: orquestación en un solo comando
```
