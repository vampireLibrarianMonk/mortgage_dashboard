from starlette.testclient import TestClient
import main
from tax import storage

client = TestClient(main.app)
doc = next(d for d in storage.list_documents(2025) if d.original_filename == "2025_return.pdf")
r = client.post(f"/tax/2025/documents/{doc.id}/extract", json={"provider": "local"})
print("extract:", r.status_code, r.json().get("ok"))
facts = storage.load_facts(2025, doc.id)
codes = [f.field_code for f in facts]
print("has 8f fact:", "ret_fed_hsa_taxable_distribution" in codes, "| total facts:", len(codes))
body = client.get("/tax/summary?years=2025").json()
for d in body["years"][0]["deductions"]:
    print(d["jurisdiction"], "|", d["amount"], "|", d["note"])
