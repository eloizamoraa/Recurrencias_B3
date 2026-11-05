from pathlib import Path
import json
import os

import requests
from azure.identity import InteractiveBrowserCredential, TokenCachePersistenceOptions
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent

load_dotenv(PROJECT_ROOT / ".env", override=True)

FLOW_URL = os.environ["FLOW_URL_BATCHES"]
BATCH_DIR = PROJECT_ROOT / "data" / "batches"
OUT_DIR = PROJECT_ROOT / "data" / "top10"


def get_token() -> str:
    """Token de Power Automate (abre el navegador la primera vez y luego usa la caché)."""

    cred = InteractiveBrowserCredential(
        cache_persistence_options=TokenCachePersistenceOptions(name="recurrencias_b3")
    )

    return cred.get_token("https://service.flow.microsoft.com//.default").token


def main():

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    headers = {"Authorization": f"Bearer {get_token()}"}

    for batch_file in sorted(BATCH_DIR.glob("batch_*.json")):
        payload = json.loads(batch_file.read_text(encoding="utf-8"))

        resp = requests.post(FLOW_URL, headers=headers, json=payload, timeout=300)

        if not resp.ok:
            print(f"{batch_file.name}: ERROR {resp.status_code}")
            print(resp.text[:2000])
            continue

        out = OUT_DIR / f"top10_{payload['batch_id']}.json"
        out.write_text(json.dumps(resp.json(), ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"{batch_file.name} -> {out}")


if __name__ == "__main__":
    main()
