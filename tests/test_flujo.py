import os
import requests
from dotenv import load_dotenv
from azure.identity import InteractiveBrowserCredential, TokenCachePersistenceOptions

load_dotenv()

cred = InteractiveBrowserCredential(
    cache_persistence_options=TokenCachePersistenceOptions(name="recurrencias_b3")
)
token = cred.get_token("https://service.flow.microsoft.com//.default").token

r = requests.post(
    os.environ["COPILOT_FLOW_URL"],
    headers={"Authorization": f"Bearer {token}"},
    json={
        "tema": "Error de conexión VPN GlobalProtect",
        "departamento": "Sistemas",
        "n_tickets": 37,
        "ejemplos": (
            "- L'usuari no pot connectar a GlobalProtect. Després de validar MFA apareix un error.\n"
            "- GlobalProtect es queda en 'Connecting...'. Resolt reinstal·lant el client.\n"
            "- Després del canvi de contrasenya no connecta la VPN. Resolt sincronitzant credencials."
        ),
    },
    timeout=180,
)
print(repr(r.text[:300]))
print("Status:", r.status_code)
print(r.text)