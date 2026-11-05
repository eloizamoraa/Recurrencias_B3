from pathlib import Path
import json

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parent.parent

INPUT_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "tickets_clean.xlsx"
)

BATCH_DIR = (
    PROJECT_ROOT
    / "data"
    / "batches"
)

SAMPLE_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "sample_500.xlsx"
)

SAMPLE_SIZE = 500
BATCH_SIZE = 100
RANDOM_STATE = 42


def load_tickets() -> pd.DataFrame:
    """Carga los tickets ya limpiados."""

    print("Leyendo tickets...")

    df = pd.read_excel(INPUT_FILE)

    print(f"Tickets disponibles: {len(df)}")

    return df


def prepare_tickets(df: pd.DataFrame) -> pd.DataFrame:
    """
    Prepara los tickets que pueden enviarse al LLM.
    """

    df = df.copy()

    # NaN -> ""
    columns = [
        "Ticket_ID",
        "Summary_clean",
        "Notes_clean",
        "SRD",
        "Service",
        "Resolution_clean",]

    for column in columns:
        df[column] = (
            df[column]
            .fillna("")
            .astype(str)
            .str.strip()
        )

    # Eliminamos registros sin contenido útil
    df = df[
        (df["Summary_clean"] != "")
        | (df["Notes_clean"] != "")
        | (df["Resolution_clean"] != "")
    ].copy()

    # Necesitamos un identificador
    df = df[
        df["Ticket_ID"] != ""
    ].copy()

    return df


def create_sample(
    df: pd.DataFrame,
    sample_size: int = SAMPLE_SIZE
) -> pd.DataFrame:

    if len(df) <= sample_size:
        return df.copy()

    return df.sample(
        n=sample_size,
        random_state=RANDOM_STATE,
    )


def ticket_to_dict(row) -> dict:
    """
    Convierte una fila del DataFrame al formato que
    posteriormente recibirá Azure OpenAI.
    """

    return {
        "ticket_id": row["Ticket_ID"],
        "summary": row["Summary_clean"],
        "notes": row["Notes_clean"],
        "srd": row["SRD"],
        "service": row["Service"],
        "resolution": row["Resolution_clean"],
    }


def create_batches(
    sample_df: pd.DataFrame,
    batch_size: int = BATCH_SIZE
):
    """
    Divide los tickets en lotes.
    """

    BATCH_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    batches_created = 0

    for start in range(
        0,
        len(sample_df),
        batch_size,
    ):

        batch_df = sample_df.iloc[
            start:start + batch_size
        ]

        tickets = [
            ticket_to_dict(row)
            for _, row in batch_df.iterrows()
        ]

        batch_number = batches_created + 1

        batch = {
            "batch_id": f"batch_{batch_number:03d}",
            "ticket_count": len(tickets),
            "tickets": tickets,
        }

        output_file = (
            BATCH_DIR
            / f"batch_{batch_number:03d}.json"
        )

        with open(
            output_file,
            "w",
            encoding="utf-8",
        ) as file:

            json.dump(
                batch,
                file,
                ensure_ascii=False,
                indent=2,
            )

        print(
            f"Creado {output_file.name}: "
            f"{len(tickets)} tickets"
        )

        batches_created += 1

    return batches_created


def main():

    print("=" * 60)
    print("PREPARACIÓN DE LOTES")
    print("=" * 60)

    # 1. Cargar
    df = load_tickets()

    # 2. Preparar
    df = prepare_tickets(df)

    print(
        f"Tickets válidos para análisis: "
        f"{len(df)}"
    )

    # 3. Muestra
    sample_df = create_sample(df)

    print(
        f"Tickets seleccionados para muestra: "
        f"{len(sample_df)}"
    )

    # 4. Guardamos la muestra para poder auditarla
    SAMPLE_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    sample_df.to_excel(
        SAMPLE_FILE,
        index=False,
    )

    print(
        f"Muestra guardada: "
        f"{SAMPLE_FILE}"
    )

    # 5. Crear lotes
    batches = create_batches(sample_df)

    print("\n" + "=" * 60)
    print("RESULTADO")
    print("=" * 60)

    print(f"Tickets muestra: {len(sample_df)}")
    print(f"Tamaño lote: {BATCH_SIZE}")
    print(f"Lotes creados: {batches}")


if __name__ == "__main__":
    main()