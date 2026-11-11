"""
Utilitaires d'Importation et d'Exportation Excel (.xlsx OpenXML natif et .csv UTF-8 BOM)
sans dépendance externe obligatoire (utilise les bibliothèques standard Python : zipfile, xml, csv, io).
"""

import csv
from datetime import date, datetime
import io
import re
from typing import Any, Dict, Iterable, List, Optional
import unicodedata
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape
import zipfile


def normalize_col_key(header: str) -> str:
    """
    Normalise un intitulé de colonne Excel/CSV en clé ASCII minuscule sans accents
    pour permettre une correspondance souple lors de l'import.
    """
    if not header:
        return ""
    text = str(header).strip().lower()
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return text


def _col_index_to_letters(idx_zero_based: int) -> str:
    """Convertit un index de colonne 0-based (0 -> A, 25 -> Z, 26 -> AA) en référence Excel."""
    result = ""
    n = idx_zero_based + 1
    while n > 0:
        n, rem = divmod(n - 1, 26)
        result = chr(65 + rem) + result
    return result


def _col_letters_to_index(cell_ref: str) -> int:
    """Extrait l'index 0-based de colonne depuis une référence de cellule Excel (ex: 'C12' -> 2)."""
    letters = "".join(ch for ch in cell_ref if ch.isalpha()).upper()
    idx = 0
    for ch in letters:
        idx = idx * 26 + (ord(ch) - 64)
    return max(0, idx - 1)


def build_xlsx_bytes(
    sheet_name: str,
    headers: List[str],
    rows: Iterable[Iterable[Any]],
) -> bytes:
    """
    Génère un fichier Microsoft Excel (.xlsx OpenXML standard) en mémoire avec :
    - En-tête stylisé (fond bleu hospitalier #0369A1, texte blanc gras)
    - Largeurs de colonnes ajustées automatiquement
    - Encodage UTF-8 complet (compatible Microsoft Excel, LibreOffice Calc, Google Sheets).
    """
    clean_sheet_title = re.sub(r"[\[\]\*\?\/\\:]", " ", sheet_name or "Feuille1").strip()[:31] or "Feuille1"
    all_rows: List[List[str]] = [[str(h) for h in headers]]
    for r in rows:
        all_rows.append(["" if v is None else str(v) for v in r])

    # Calcul des largeurs de colonnes
    col_widths: List[float] = []
    for col_idx in range(len(headers)):
        max_len = max(
            (len(row[col_idx]) for row in all_rows if col_idx < len(row)),
            default=12,
        )
        col_widths.append(min(52.0, max(12.0, float(max_len + 4))))

    cols_xml_parts = [
        f'<col min="{i + 1}" max="{i + 1}" width="{w:.1f}" customWidth="1"/>'
        for i, w in enumerate(col_widths)
    ]
    cols_xml = "<cols>" + "".join(cols_xml_parts) + "</cols>" if cols_xml_parts else ""

    sheet_data_parts: List[str] = []
    for row_idx, row_vals in enumerate(all_rows, start=1):
        cells_xml: List[str] = []
        style_attr = ' s="1"' if row_idx == 1 else ' s="2"'
        for col_idx, val in enumerate(row_vals):
            cell_ref = f"{_col_index_to_letters(col_idx)}{row_idx}"
            escaped_val = escape(val)
            cells_xml.append(
                f'<c r="{cell_ref}" t="inlineStr"{style_attr}><is><t xml:space="preserve">{escaped_val}</t></is></c>'
            )
        row_height = ' ht="24" customHeight="1"' if row_idx == 1 else ' ht="19" customHeight="1"'
        sheet_data_parts.append(f'<row r="{row_idx}"{row_height}>{"".join(cells_xml)}</row>')

    worksheet_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheetViews><sheetView tabSelected="1" workbookViewId="0">'
        '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
        "</sheetView></sheetViews>"
        f"{cols_xml}"
        f'<sheetData>{"".join(sheet_data_parts)}</sheetData>'
        "</worksheet>"
    )

    styles_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<fonts count="2">'
        '<font><sz val="10"/><color rgb="FF0F172A"/><name val="Calibri"/></font>'
        '<font><b/><sz val="10"/><color rgb="FFFFFFFF"/><name val="Calibri"/></font>'
        "</fonts>"
        '<fills count="3">'
        '<fill><patternFill patternType="none"/></fill>'
        '<fill><patternFill patternType="gray125"/></fill>'
        '<fill><patternFill patternType="solid"><fgColor rgb="FF0369A1"/><bgColor indexed="64"/></patternFill></fill>'
        "</fills>"
        '<borders count="2">'
        '<border><left/><right/><top/><bottom/><diagonal/></border>'
        '<border>'
        '<left style="thin"><color rgb="FFCBD5E1"/></left>'
        '<right style="thin"><color rgb="FFCBD5E1"/></right>'
        '<top style="thin"><color rgb="FFCBD5E1"/></top>'
        '<bottom style="thin"><color rgb="FFCBD5E1"/></bottom>'
        "<diagonal/>"
        "</border>"
        "</borders>"
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="3">'
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
        '<xf numFmtId="0" fontId="1" fillId="2" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1">'
        '<alignment vertical="center" wrapText="0"/>'
        "</xf>"
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyFont="1" applyBorder="1" applyAlignment="1">'
        '<alignment vertical="center"/>'
        "</xf>"
        "</cellXfs>"
        "</styleSheet>"
    )

    workbook_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<sheets><sheet name="{escape(clean_sheet_title)}" sheetId="1" r:id="rId1"/></sheets>'
        "</workbook>"
    )

    workbook_rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
        "</Relationships>"
    )

    root_rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        "</Relationships>"
    )

    content_types_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        "</Types>"
    )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types_xml)
        zf.writestr("_rels/.rels", root_rels_xml)
        zf.writestr("xl/workbook.xml", workbook_xml)
        zf.writestr("xl/_rels/workbook.xml.rels", workbook_rels_xml)
        zf.writestr("xl/styles.xml", styles_xml)
        zf.writestr("xl/worksheets/sheet1.xml", worksheet_xml)

    return buf.getvalue()


def build_csv_bytes(headers: List[str], rows: Iterable[Iterable[Any]]) -> bytes:
    """Génère un fichier CSV avec BOM UTF-8 et séparateur ';' pour ouverture directe sous Excel FR/DZ."""
    sio = io.StringIO()
    sio.write("\ufeff")
    writer = csv.writer(sio, delimiter=";", quoting=csv.QUOTE_MINIMAL)
    writer.writerow(headers)
    for r in rows:
        writer.writerow(["" if v is None else str(v) for v in r])
    return sio.getvalue().encode("utf-8")


def _parse_xlsx_raw_bytes(raw_bytes: bytes) -> List[List[str]]:
    """Lit la première feuille d'un classeur .xlsx OpenXML et retourne une liste de lignes."""
    ns = {"main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(io.BytesIO(raw_bytes), mode="r") as zf:
        shared_strings: List[str] = []
        if "xl/sharedStrings.xml" in zf.namelist():
            ss_root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            for si in ss_root.findall("main:si", ns):
                texts = [t.text or "" for t in si.findall(".//main:t", ns)]
                shared_strings.append("".join(texts))

        sheet_files = sorted(
            name
            for name in zf.namelist()
            if name.startswith("xl/worksheets/sheet") and name.endswith(".xml")
        )
        if not sheet_files:
            return []

        sheet_root = ET.fromstring(zf.read(sheet_files[0]))
        extracted_rows: List[List[str]] = []
        for row_el in sheet_root.findall(".//main:sheetData/main:row", ns):
            row_cells: Dict[int, str] = {}
            max_col = -1
            next_col = 0
            for c_el in row_el.findall("main:c", ns):
                ref = c_el.attrib.get("r", "")
                col_idx = _col_letters_to_index(ref) if ref else next_col
                next_col = col_idx + 1
                max_col = max(max_col, col_idx)

                cell_type = c_el.attrib.get("t", "")
                val_str = ""
                if cell_type == "inlineStr":
                    t_nodes = c_el.findall(".//main:t", ns)
                    val_str = "".join(t.text or "" for t in t_nodes)
                elif cell_type == "s":
                    v_el = c_el.find("main:v", ns)
                    if v_el is not None and v_el.text and v_el.text.isdigit():
                        s_idx = int(v_el.text)
                        if 0 <= s_idx < len(shared_strings):
                            val_str = shared_strings[s_idx]
                else:
                    v_el = c_el.find("main:v", ns)
                    if v_el is not None and v_el.text is not None:
                        val_str = v_el.text
                row_cells[col_idx] = val_str.strip()

            if max_col >= 0:
                row_list = [row_cells.get(i, "") for i in range(max_col + 1)]
                if any(cell != "" for cell in row_list):
                    extracted_rows.append(row_list)
        return extracted_rows


def _parse_csv_raw_bytes(raw_bytes: bytes) -> List[List[str]]:
    """Décode un fichier CSV/TSV (UTF-8-SIG ou CP1252) et détecte automatiquement le séparateur."""
    try:
        text = raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw_bytes.decode("cp1252", errors="replace")

    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return []

    first_line = lines[0]
    if first_line.count(";") >= first_line.count(",") and first_line.count(";") > 0:
        delimiter = ";"
    elif first_line.count("\t") > first_line.count(","):
        delimiter = "\t"
    else:
        delimiter = ","

    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    return [[cell.strip() for cell in row] for row in reader if any(c.strip() for c in row)]


def parse_excel_or_csv_bytes(raw_bytes: bytes, filename: str = "") -> List[Dict[str, str]]:
    """
    Parse un fichier Excel (.xlsx) ou CSV (.csv) et retourne une liste de dictionnaires
    indexés par clé de colonne normalisée (ex: 'nom_commercial', 'code_cip_ean13', 'nom', 'prenom').
    """
    if not raw_bytes:
        return []

    is_xlsx = raw_bytes[:4] == b"PK\x03\x04" or filename.lower().endswith(".xlsx")
    raw_rows = _parse_xlsx_raw_bytes(raw_bytes) if is_xlsx else _parse_csv_raw_bytes(raw_bytes)
    if len(raw_rows) < 2:
        return []

    header_row = raw_rows[0]
    norm_headers = [normalize_col_key(h) for h in header_row]

    records: List[Dict[str, str]] = []
    for row in raw_rows[1:]:
        rec: Dict[str, str] = {}
        for idx, key in enumerate(norm_headers):
            if not key:
                continue
            val = row[idx].strip() if idx < len(row) else ""
            rec[key] = val
        if any(v for v in rec.values()):
            records.append(rec)
    return records


def first_non_empty(rec: Dict[str, str], candidate_keys: List[str], default: str = "") -> str:
    """Retourne la première valeur non vide parmi plusieurs alias de colonnes Excel."""
    for k in candidate_keys:
        nk = normalize_col_key(k)
        if nk in rec and rec[nk] != "":
            return rec[nk]
    return default


def parse_flexible_date(val: str, default_date: Optional[date] = None) -> date:
    """Parse une date au format YYYY-MM-DD, DD/MM/YYYY ou DD-MM-YYYY."""
    clean = (val or "").strip()
    if not clean:
        return default_date or date(1985, 1, 1)
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(clean[:10], fmt).date()
        except ValueError:
            continue
    return default_date or date(1985, 1, 1)


def generate_valid_nir_for_patient(birth_date: date, gender: str, unique_seed: int) -> str:
    """
    Génère un NIR de 15 chiffres valide (avec clé de contrôle modulo 97)
    lorsqu'un fichier Excel de malades ne contient pas de NIR ou contient un N° Chifa court.
    """
    sex_digit = "1" if str(gender).upper().startswith("M") else "2"
    yy = f"{birth_date.year % 100:02d}"
    mm = f"{birth_date.month:02d}"
    dept = "16"
    serial = f"{(unique_seed % 999999) + 1:06d}"
    base_13 = f"{sex_digit}{yy}{mm}{dept}{serial}"
    key = 97 - (int(base_13) % 97)
    return f"{base_13}{key:02d}"

