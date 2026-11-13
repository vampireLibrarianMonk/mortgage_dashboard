import re, io
from tax import storage
from pypdf import PdfReader

doc = next(d for d in storage.list_documents(2025) if d.original_filename == "2025_return.pdf")
data, kind = storage.read_original(2025, doc.id)
r = PdfReader(io.BytesIO(data))

out = []
t6 = r.pages[6].extract_text(extraction_mode="layout") or ""
out.append("=== page 6 (1040 p1) LAYOUT, FULL WIDTH, rows 1a-11b:")
for ln in t6.splitlines():
    if re.search(r"Total amount from|Other earned income|Add lines 1a|Tax-exempt|Taxable interest|Qualified dividends|Ordinary|IRA distributions|Pensions|Social security|Capital gain|Additional income|total income|adjusted gross|Deduction", ln):
        out.append(f"  {ln.rstrip()}")
        out.append("")

open("_probe_ded.out", "w", encoding="utf-8").write("\n".join(out) + "\n")
print("done")
