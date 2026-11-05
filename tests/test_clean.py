from src.clean import (
    safe_text,
    clean_summary,
    clean_notes,
    build_analysis_text,
    remove_phones,
    remove_names,
    build_known_names,
)
import pandas as pd


print("=" * 60)
print("TEST 1 - NaN")
print("=" * 60)

print(repr(safe_text(None)))


print("\n" + "=" * 60)
print("TEST 2 - SUMMARY")
print("=" * 60)

summary = (
    "Tornar a obrir: "
    "Alta de Manuel Garcia amb numero 936665935 d’una extensió o línia de telefonia fixa"
)

print("ORIGINAL:")
print(summary)

print("\nLIMPIO:")
print(clean_summary(summary))



print("\n" + "=" * 60)
print("TEST 3 - NOTES")
print("=" * 60)

notes = """
L'usuari indica que no pot connectar-se a la VPN.

Correu: exemple@empresa.com

Ha provat de reiniciar l'equip.
"""

print("ORIGINAL:")
print(notes)

print("\nLIMPIO:")
print(clean_notes(notes))


print("\n" + "=" * 60)
print("TEST 4 - ANALYSIS TEXT")
print("=" * 60)

print(
    build_analysis_text(
        "Tornar a obrir: Error de connexió VPN",
        """
        L'usuari no pot connectar a GlobalProtect.
        Correu: exemple@empresa.com
        Després de validar MFA apareix un error.
        """,
    )
)

print("\n" + "=" * 60)
print("TEST 5 - NOMBRES EN MAYÚSCULAS Y DNI")
print("=" * 60)

known_names = build_known_names(
    pd.DataFrame({"Customer*+": ["ADELAIDA TOMAS MARTÍN", "ABEL VICO BAÑO"]})
)

print(clean_summary("Consulta sobre LT2BA30010 de ADELAIDA TOMAS MARTÍN", known_names))

print(
    clean_notes(
        "> Nom de contacte: FRANCESC SERÓ MONCUSI\n"
        "> DNI o UID Persona a donar d'alta: 39971452M\n"
        "L'usuari Abel Vico Baño té una consulta genèrica.",
        known_names,
    )
)
