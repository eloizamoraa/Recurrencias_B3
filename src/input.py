import pandas as pd

EXCEL_PATH = "data/input/recurrencies_exemple_sept.xlsx"

df = pd.read_excel(EXCEL_PATH,engine="calamine")

print("=" * 50)
print("1. INFORMACIÓN DEL EXCEL")
print("=" * 50)

print(f"Tickets: {len(df)}")
print(f"Columnas: {len(df.columns)}")

print("\nColumnas disponibles:")
for column in df.columns:
    print(f"  - {column}")


print("\n" + "=" * 50)
print("2. COMPROBACIÓN DE COLUMNAS NECESARIAS")
print("=" * 50)

required_columns = [
    "Summary*",
    "Notes*",
    "Assigned Group*+",
    "SRD",
    "Resolution",
    "Service*+"
]

for column in required_columns:
    if column in df.columns:
        print(f"OK  {column}")
    else:
        print(f"ERROR  {column} no encontrada")


print("\n" + "=" * 50)
print("3. CALIDAD DE LOS DATOS")
print("=" * 50)

print(f"Assigned_Groups vacíos: {df['Assigned Group*+'].isna().sum()}")
print(f"Summary vacíos: {df['Summary*'].isna().sum()}")
print(f"Notes vacíos: {df['Notes*'].isna().sum()}")
print(f"SRD vacíos: {df['SRD'].isna().sum()}")
print(f"Resolution vacíos: {df['Resolution'].isna().sum()}")
print(f"Service vacíos: {df['Service*+'].isna().sum()}")



print("\n" + "=" * 50)
print("4. EJEMPLO")
print("=" * 50)

for _, ticket in df[["SRD", "Summary*", "Notes*", "Assigned Group*+", "Resolution", "Service*+"]].head(3).iterrows():

    print(f"\nSRD: {ticket['SRD']}")
    print(f"Summary: {ticket['Summary*']}")
    print(f"Notes: {ticket['Notes*']}")
    print(f"Assigned Groups: {ticket['Assigned Group*+']}")
    print(f"Resolution: {ticket['Resolution']}")
    print(f"Service: {ticket['Service*+']}")