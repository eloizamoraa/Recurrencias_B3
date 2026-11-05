from pathlib import Path

import pandas as pd

from src.clean import clean_dataframe


# --------------------------------------------------
# RUTAS
# --------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent

INPUT_FILE = PROJECT_ROOT / "data" / "input" / "recurrencies_exemple_sept.xlsx"

OUTPUT_DIR = PROJECT_ROOT / "data" / "processed"

OUTPUT_FILE = OUTPUT_DIR / "tickets_clean.xlsx"


def main():

    print("=" * 60)
    print("PROCESAMIENTO DE TICKETS")
    print("=" * 60)

    # Creamos la carpeta si no existe
    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    # ----------------------------------------------
    # 1. Leer Excel
    # ----------------------------------------------

    print("\n1. Leyendo Excel...")

    df = pd.read_excel(INPUT_FILE, engine="calamine")

    print(f"   Tickets originales: {len(df)}")

    # ----------------------------------------------
    # 2. Limpiar
    # ----------------------------------------------

    print("\n2. Limpiando tickets...")

    clean_df = clean_dataframe(df)

    print(f"   Tickets procesados: {len(clean_df)}")

    # ----------------------------------------------
    # 3. Validaciones
    # ----------------------------------------------

    print("\n3. Validando resultado...")

    summary_empty = (
        clean_df["Summary_clean"]
        .eq("")
        .sum()
    )

    notes_empty = (
        clean_df["Notes_clean"]
        .eq("")
        .sum()
    )

    analysis_empty = (
        clean_df["Analysis_text"]
        .eq("")
        .sum()
    )
    resolution_empty = (
        clean_df["Resolution_clean"]
        .eq("")
        .sum()
    )

    print(f"   Summary_clean vacíos: {summary_empty}")
    print(f"   Notes_clean vacíos: {notes_empty}")
    print(f"   Analysis_text vacíos: {analysis_empty}")
    print(f"   Resolution_clean vacíos: {resolution_empty}")

    # ----------------------------------------------
    # 4. Guardar
    # ----------------------------------------------

    print("\n4. Guardando resultado...")

    clean_df.to_excel(
        OUTPUT_FILE,
        index=False,
    )

    print(f"   Archivo: {OUTPUT_FILE}")

    # ----------------------------------------------
    # 5. Mostrar ejemplos
    # ----------------------------------------------

    print("\n" + "=" * 60)
    print("EJEMPLOS")
    print("=" * 60)

    examples = clean_df[
        clean_df["Notes_clean"] != ""
    ].sample(
        n=min(5, len(clean_df)),
        random_state=42,
    )

    for _, ticket in examples.iterrows():

        print("\n" + "-" * 60)

        print("\nSUMMARY ORIGINAL:")
        print(ticket["Summary_original"])

        print("\nSUMMARY CLEAN:")
        print(ticket["Summary_clean"])

        print("\nNOTES ORIGINAL:")
        print(ticket["Notes_original"])

        print("\nNOTES CLEAN:")
        print(ticket["Notes_clean"])

        print("\nANALYSIS TEXT:")
        print(ticket["Analysis_text"])

        print("\nRESOLUTION ORIGINAL:")
        print(ticket["Resolution_original"])

        print("\nRESOLUTION CLEAN:")
        print(ticket["Resolution_clean"])

        print("\nASSIGNED GROUP:")
        print(ticket["Assigned_Groups"])

        print("\nSRD:")
        print(ticket["SRD"])

        print("\nSERVICE:")
        print(ticket["Service"])


    print("\n" + "=" * 60)
    print("PROCESO FINALIZADO")
    print("=" * 60)


if __name__ == "__main__":
    main()