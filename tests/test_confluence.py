from src.confluence import comprobar_conexion, buscar_articulo, separar_titulo, crear_borrador

# 1. Conexión
print("Espacio:", comprobar_conexion())

# 2. Búsqueda (cambia los términos por algo que sepas que ya está documentado)
for r in buscar_articulo(["GlobalProtect", "VPN"]):
    print(f"  - {r['titulo']}: {r['url']}")

# 3. Crear borrador de prueba (descomenta cuando 1 y 2 funcionen)
# ejemplo = open("tests/respuesta_ejemplo.txt", encoding="utf-8").read()
# titulo, cuerpo = separar_titulo(ejemplo)
# print("Título:", titulo)
# print("Borrador:", crear_borrador("[PRUEBA] " + titulo, cuerpo))