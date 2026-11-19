"""Batch ingest one tax year from Organized\Tax_Documents\<year>.

Mirrors the app's upload -> classify -> extract pipeline (tax.routes) for a
whole year folder:

  1. every document file is stored via tax.storage.add_document (SHA-256
     dedupe per year - re-runs are free);
  2. extraction runs LOCAL first (free; the native-text readers like the
     1040 e-file parser work fully offline), then AWS Textract FORMS for
     anything the local pass cannot read (scans, box-level readers);
  3. W-2 copies are deduped per (taxpayer, employer EIN) - Copy A repeats
     Copy B's boxes and would double-count wages in the summary. The best
     copy (Copy B > C > 1 > A) is kept, redundant ones are deleted from the
     store (their Organized file stays; the report records the decision).

Usage:
    backend/venv/Scripts/python.exe backend/scripts/tax_year_ingest.py 2024 [--pdf-password 7812]
"""
from __future__ import annotations

import argparse
import io
import sys
from datetime import datetime
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from tax import storage  # noqa: E402
from tax.classify import classify_form  # noqa: E402
from tax.extraction.images import iter_page_images  # noqa: E402
from tax.extraction.providers import (  # noqa: E402
    ExtractedKV,
    LocalDigitalProvider,
    NoPageImage,
    get_provider,
)
from tax.forms.f1040 import extract_f1040_facts  # noqa: E402
from tax.forms.f1095_c import extract_f1095_c_facts  # noqa: E402
from tax.forms.f1099_combined import extract_f1099_combined_facts  # noqa: E402
from tax.forms.f1099_int import extract_f1099_int_facts  # noqa: E402
from tax.forms.f1099_nec import extract_f1099_nec_facts  # noqa: E402
from tax.forms.f3922 import extract_f3922_facts  # noqa: E402
from tax.forms.il_1040 import extract_il_1040_facts  # noqa: E402
from tax.forms.paystub import extract_paystub_facts  # noqa: E402
from tax.forms.w2 import extract_w2_facts  # noqa: E402
from tax.models import DocKind, DocStage, ExtractionMethod, FormType  # noqa: E402

ORG_ROOT = Path(r'C:\Users\mothe\Documents\Scans\Organized\Tax_Documents')

_HOUSEHOLD_NAMES = ('Patrick', 'Sara')
_W2_COPY_ORDER = {'copy_b': 0, 'copy_c': 1, 'copy_1': 2, 'copy_a': 3}


def _person_from_name(name: str | None) -> str | None:
    if not name:
        return None
    first = name.strip().split()[0] if name.strip() else ''
    return first.title() or None


def _person_from_filename(filename: str | None) -> str | None:
    if not filename:
        return None
    low = filename.lower()
    for name in _HOUSEHOLD_NAMES:
        if name.lower() in low:
            return name
    return None


def _fact_name(facts: list) -> str | None:
    for f in facts:
        name = getattr(f, 'taxpayer_name', None)
        if name:
            return name
        if getattr(f, 'field_code', '') == 'employee_name' and f.value:
            return str(f.value)
    return None


def _has_text(kvs: list[ExtractedKV]) -> bool:
    return any(
        kv.key == '__native_text__' and len(kv.value.strip()) >= 40 for kv in kvs
    )


def _dispatch_facts(form: FormType, doc_id: str, year: int, kvs: list[ExtractedKV],
                    method: ExtractionMethod) -> list:
    """Same reader dispatch as tax.routes.extract_document."""
    if form is FormType.w2:
        return extract_w2_facts(doc_id, year, kvs, method=method)
    if form is FormType.paystub:
        return extract_paystub_facts(doc_id, year, kvs, method=method)
    if form is FormType.f1099_int:
        return extract_f1099_int_facts(doc_id, year, kvs, method=method)
    if form is FormType.f1099_nec:
        return extract_f1099_nec_facts(doc_id, year, kvs, method=method)
    if form is FormType.f1099_div:
        return extract_f1099_combined_facts(doc_id, year, kvs, method=method)
    if form is FormType.f1095_c:
        return extract_f1095_c_facts(doc_id, year, kvs, method=method)
    if form is FormType.f3922:
        return extract_f3922_facts(doc_id, year, kvs, method=method)
    if form is FormType.f1040:
        return extract_f1040_facts(doc_id, year, kvs, method=method)
    if form is FormType.f1040_il:
        return extract_il_1040_facts(doc_id, year, kvs, method=method)
    return []


def _decrypt_pdf(data: bytes, password: str) -> bytes | None:
    """Decrypted PDF bytes when the password opens it; None otherwise."""
    try:
        from pypdf import PdfReader, PdfWriter

        if not data.startswith(b'%PDF'):
            return None
        reader = PdfReader(io.BytesIO(data))
        if not reader.is_encrypted:
            return None
        if not reader.decrypt(password):
            return None
        writer = PdfWriter()
        for page in reader.pages:
            writer.add_page(page)
        buf = io.BytesIO()
        writer.write(buf)
        return buf.getvalue()
    except Exception:  # noqa: BLE001
        return None


_TEXTRACT_CLIENT = None


def _textract_client():
    global _TEXTRACT_CLIENT
    if _TEXTRACT_CLIENT is None:
        import boto3

        _TEXTRACT_CLIENT = boto3.Session(region_name='us-east-1').client('textract')
    return _TEXTRACT_CLIENT


def _textract_full_text(data: bytes, kind: DocKind) -> str:
    """Full OCR text via DetectDocumentText (cheap), reading-order lines."""
    try:
        images = [data] if kind in (DocKind.png, DocKind.jpeg) else list(iter_page_images(data, kind))
    except Exception:  # noqa: BLE001
        return ''
    pages = []
    for image in images:
        try:
            resp = _textract_client().detect_document_text(Document={'Bytes': image})
        except Exception:  # noqa: BLE001
            continue
        blocks = [b for b in resp.get('Blocks', []) if b.get('BlockType') == 'LINE']
        blocks.sort(key=lambda b: (
            round(float(b.get('Geometry', {}).get('BoundingBox', {}).get('Top', 0.0)), 2),
            float(b.get('Geometry', {}).get('BoundingBox', {}).get('Left', 0.0))))
        pages.append(chr(10).join(b.get('Text', '') for b in blocks))
    return chr(10).join(p for p in pages if p)


def _extract_document(doc_id: str, year: int, filename: str, data: bytes,
                      kind: DocKind, pdf_password: str | None) -> dict:
    """Pipeline for one document's bytes: local first, then AWS. Returns a
    result dict for the report (does not touch the store)."""
    out = {'provider': None, 'form_type': None, 'fact_count': 0,
           'taxpayer': None, 'note': ''}

    kvs: list[ExtractedKV] = []
    method = ExtractionMethod.native_pdf
    if kind is DocKind.pdf and pdf_password:
        dec = _decrypt_pdf(data, pdf_password)
        if dec is not None:
            data = dec
    if kind is DocKind.pdf:
        kvs = LocalDigitalProvider().extract(data, kind)

    form: FormType | None = None
    facts: list = []
    if kvs:
        form = classify_form(kvs)
        facts = _dispatch_facts(form, doc_id, year, kvs, method)

    # The local pass produced nothing readable for a box-level reader (or the
    # doc is a plain scan) - escalate to Textract FORMS.
    box_level = form in (
        FormType.w2, FormType.paystub, FormType.f1099_int, FormType.f1099_nec,
        FormType.f1099_div, FormType.f1095_c, FormType.f3922,
    )
    if not facts and (not kvs or not _has_text(kvs) or form in (FormType.unknown, None) or box_level):
        has_raster = True
        if kind is DocKind.pdf:
            try:
                list(iter_page_images(data, kind))
            except NoPageImage:
                has_raster = False
            except Exception:  # noqa: BLE001 - let aws surface the real error
                has_raster = True
        if not has_raster:
            note = 'no page image for Textract (vector PDF); local result kept'
            out['note'] = (out['note'] + '; ' if out['note'] else '') + note
            aws_kvs = []
        else:
            try:
                aws = get_provider('aws')
                aws_kvs = aws.extract(data, kind)
            except Exception as e:  # noqa: BLE001
                note = f'aws failed: {e}'
                out['note'] = (out['note'] + '; ' if out['note'] else '') + note
                aws_kvs = []
        if aws_kvs:
            form_aws = classify_form(aws_kvs)
            facts_aws = _dispatch_facts(form_aws, doc_id, year, aws_kvs,
                                        ExtractionMethod.textract)
            if form_aws is FormType.unknown and not facts_aws:
                note = 'aws extracted text but no supported form matched'
                out['note'] = (out['note'] + '; ' if out['note'] else '') + note
            if facts_aws or (form_aws is not FormType.unknown and not facts):
                kvs = aws_kvs
                form = form_aws
                facts = facts_aws
                method = ExtractionMethod.textract
                out['provider'] = 'aws'

    # FORMS sees fields, not titles - when its classification came back
    # unknown, classify the full OCR text instead (cheap DetectDocumentText).
    if (form is FormType.unknown or form is None) and has_raster:
        try:
            ocr_text = _textract_full_text(data, kind)
        except Exception:  # noqa: BLE001
            ocr_text = ''
        if len(ocr_text.strip()) >= 40:
            form_txt = classify_form([
                ExtractedKV(key='__native_text__', value=ocr_text, confidence=0.6)])
            if form_txt is not FormType.unknown:
                form = form_txt
                if not kvs:
                    kvs = [ExtractedKV(key='__native_text__', value=ocr_text,
                                       confidence=0.6)]
                out['provider'] = 'aws'

    out['provider'] = out['provider'] or ('local' if kvs else None)
    out['form_type'] = form.value if form is not None else 'unknown'
    out['fact_count'] = len(facts)

    taxpayer = None
    if form in (FormType.w2, FormType.paystub):
        taxpayer = _person_from_name(_fact_name(facts)) or _person_from_filename(filename)
    if taxpayer is None:
        taxpayer = _person_from_filename(filename)
    out['taxpayer'] = taxpayer
    out['facts'] = facts
    return out


def doc_sha_of(data: bytes) -> str:
    return storage.sha256(data)


def _dedupe_ledger_path() -> Path:
    return BACKEND / 'txn_data' / 'tax_reconcile' / 'dedupe_removed.json'


def _read_dedupe_ledger() -> set:
    import json

    path = _dedupe_ledger_path()
    if not path.is_file():
        return set()
    return {e['sha256'] for e in json.loads(path.read_text(encoding='utf-8'))}


def _record_dedupe_removal(doc_id: str, year: int, filename: str) -> None:
    import json

    path = _dedupe_ledger_path()
    entries = json.loads(path.read_text(encoding='utf-8')) if path.is_file() else []
    if all(e['sha256'] != doc_id for e in entries):
        entries.append({'sha256': doc_id, 'year': year, 'filename': filename,
                        'removed_at': datetime.now().isoformat(timespec='seconds')})
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(entries, indent=2), encoding='utf-8')


def _w2_copy_rank(filename: str) -> int:
    """Lower is better: Copy B (the filed-with-return copy) is preferred."""
    low = filename.lower()
    for token, rank in _W2_COPY_ORDER.items():
        if token.replace('_', ' ') in low.replace('_', ' '):
            return rank
    return 9


def _dedupe_w2_copies(year: int, report: dict) -> None:
    """Keep one W-2 per (taxpayer, employer EIN); delete redundant copies.

    Copy A/C/1 repeat Copy B's boxes; summary.build_summary sums every W-2
    doc, so duplicates would double-count wages. The Organized file stays."""
    groups: dict[tuple, list] = {}
    for doc in storage.list_documents(year):
        if doc.form_type is not FormType.w2:
            continue
        facts = storage.load_facts(year, doc.id)
        ein = next((str(f.value) for f in facts if f.field_code == 'employer_ein'), '')
        key = (doc.taxpayer or '?', ein)
        groups.setdefault(key, []).append((doc, facts))

    for key, members in sorted(groups.items()):
        if len(members) < 2:
            continue
        def _rank(member: tuple) -> tuple:
            doc, facts = member
            box1 = next((str(f.value) for f in facts if f.field_code == 'box_1_wages'), '')
            has_wages = 0 if box1.strip(' ,.$') else 1
            low = doc.original_filename.lower()
            informative = 0 if low.startswith(('w2', 'w-2', '1099')) else 1
            return (has_wages, informative, _w2_copy_rank(doc.original_filename), -len(facts))
        members.sort(key=_rank)
        keep = members[0][0]
        for doc, _facts in members[1:]:
            storage.delete_document(year, doc.id)
            _record_dedupe_removal(doc.id, year, doc.original_filename)
            report['w2_dedupe_removed'].append({
                'removed': doc.original_filename,
                'kept': keep.original_filename,
                'group': f'{key[0]} EIN {key[1] or "?"}',
            })
            print(f"  W-2 dedupe: removed {doc.original_filename} "
                  f"(kept {keep.original_filename} for {key[0]} EIN {key[1] or '?'})")


def cmd_ingest(args: argparse.Namespace) -> None:
    for ys in args.years:
        year = int(ys)
        try:
            _ingest_year(year, args)
        except SystemExit as e:
            print(f'year {year}: {e}')
        except Exception as e:  # noqa: BLE001
            print(f'year {year}: FAILED {type(e).__name__}: {e}')


def _ingest_year(year: int, args: argparse.Namespace) -> None:
    year_dir = ORG_ROOT / str(year)
    if not year_dir.is_dir():
        sys.exit(f'no folder: {year_dir}')
    files = sorted(p for p in year_dir.rglob('*') if p.is_file())
    print(f'ingesting {year}: {len(files)} files under {year_dir}')

    report = {
        'year': year, 'started_at': datetime.now().isoformat(timespec='seconds'),
        'ingested': [], 'skipped_existing': [], 'w2_dedupe_removed': [],
        'notes': [],
    }

    skip = [s.strip().lower() for s in (args.skip or '').split(',') if s.strip()]
    for path in files:
        name = path.name
        if any(s in name.lower() for s in skip):
            report['notes'].append(f'{name}: skipped by --skip')
            print(f'  SKIP {name}: matches --skip')
            continue
        try:
            data = path.read_bytes()
        except OSError as e:
            report['notes'].append(f'{name}: read failed ({e})')
            print(f'  SKIP {name}: read failed')
            continue
        try:
            kind = storage.detect_kind(data)
        except storage.UnsupportedDocument:
            if data[:2] in (b'II', b'MM'):  # TIFF -> PNG (the store accepts PNG)
                try:
                    from PIL import Image

                    with Image.open(io.BytesIO(data)) as im:
                        frame = im.convert('L') if im.mode not in ('L', 'RGB', 'RGBA') else im.copy()
                        buf = io.BytesIO()
                        frame.save(buf, format='PNG')
                        data = buf.getvalue()
                    kind = DocKind.png
                    name = path.stem + '.png'
                except Exception as e:  # noqa: BLE001
                    report['notes'].append(f'{name}: tiff convert failed ({e})')
                    print(f'  SKIP {name}: tiff convert failed')
                    continue
            else:
                report['notes'].append(f'{name}: unsupported kind, skipped')
                print(f'  SKIP {name}: unsupported file kind')
                continue

        dedupe_ledger = _read_dedupe_ledger()
        if doc_sha_of(data) in dedupe_ledger:
            report['notes'].append(f'{name}: previously removed by W-2 dedupe, skipped')
            print(f'  SKIP {name}: previously removed by W-2 dedupe')
            continue
        doc, created = storage.add_document(year, name, data)
        if not created:
            existing = storage.get_document(year, doc.id)
            done = (existing is not None and existing.stage in (
                DocStage.extracted, DocStage.verified) and not args.force)
            if done:
                report['skipped_existing'].append(name)
                print(f'  SKIP {name}: already stored + extracted')
                continue
        print(f'  ... {name}: extracting')
        result = _extract_document(doc.id, year, name, data, kind, args.pdf_password or None)
        facts = result.pop('facts')
        patch = {
            'stage': DocStage.extracted if facts else (
                DocStage.classified if result['form_type'] != 'unknown' else DocStage.ingested),
            'form_type': FormType(result['form_type']) if result['form_type'] != 'unknown' else FormType.unknown,
            'note': result['note'],
        }
        if result['taxpayer']:
            patch['taxpayer'] = result['taxpayer']
        storage.update_document(year, doc.id, **patch)
        if facts:
            storage.save_facts(year, doc.id, facts)
        entry = {
            'filename': name, 'document_id': doc.id, 'created': created,
            **{k: result[k] for k in ('provider', 'form_type', 'fact_count', 'taxpayer', 'note')},
        }
        report['ingested'].append(entry)
        print(f"  {name}: {result['form_type']} via {result['provider']} "
              f"({result['fact_count']} facts, taxpayer={result['taxpayer'] or '-'})"
              + (f" [{result['note']}]" if result['note'] else ''))

    _dedupe_w2_copies(year, report)
    report['finished_at'] = datetime.now().isoformat(timespec='seconds')
    out = BACKEND / 'txn_data' / 'tax_reconcile' / f'ingest_{year}.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    import json

    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f"year {year}: {len(report['ingested'])} ingested, "
          f"{len(report['skipped_existing'])} skipped-existing, "
          f"{len(report['w2_dedupe_removed'])} W-2 copies removed")
    print(f'report -> {out}')


def main() -> None:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser(description='Batch-ingest one tax year')
    parser.add_argument('years', nargs='+', help='tax year(s), e.g. 2024 2023')
    parser.add_argument('--pdf-password', default='',
                        help='password for password-protected PDFs')
    parser.add_argument('--skip', default='',
                        help='comma-separated filename substrings to skip');
    parser.add_argument('--force', action='store_true',
                        help='re-extract every stored document of the year, even extracted ones')
    args = parser.parse_args()
    cmd_ingest(args)


if __name__ == '__main__':
    main()










