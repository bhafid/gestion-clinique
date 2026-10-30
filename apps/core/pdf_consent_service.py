"""
Service de Génération Automatique du PDF « Consentement aux Soins et Décharge » (SIH).
Conforme aux exigences médico-légales (HDS / RGPD) :
- Marges normalisées de 20 mm (Format A4 : 210 x 297 mm)
- Police standard médicale (Helvetica / Helvetica-Bold)
- Palette sobre et institutionnelle (Bleu Marine #0C4A6E, Gris Ardoise #1E293B)
- En-tête avec logo vectoriel de l'établissement + titre officiel centré
- Bloc d'identification complète du patient (Nom, Nom de naissance, DDN, Téléphone, Adresse, NIR/IPP/CI, Médecin référent)
- Sections « Consentement aux soins & anesthésie » et « Décharge & responsabilité »
- Bloc de signature côte à côte protégé contre les coupures de saut de page (KeepTogether)
- Numérotation automatique des pages en pied de page (« Page X sur Y »)
"""

from __future__ import annotations

from datetime import date, datetime
from io import BytesIO
from pathlib import Path
import struct
import textwrap
from typing import Any, Dict, List, Optional, Tuple, Union
import zlib

from django.conf import settings
from django.utils import timezone


def _get_clinic_logo_path() -> Optional[Path]:
    """Retourne le chemin du fichier logo officiel de la clinique s'il est présent."""
    base_dir = getattr(settings, "BASE_DIR", Path(__file__).resolve().parent.parent.parent)
    candidate = Path(base_dir) / "static" / "images" / "logo_clinique.png"
    if candidate.exists():
        return candidate
    return None


def _decode_png_to_rgb_flate(png_path: Path) -> Optional[Tuple[int, int, bytes]]:
    """
    Décode un fichier PNG (8-bit RGB ou RGBA) en flux RGB compressé (FlateDecode)
    pour intégration native haute fidélité (sans déformation ni perte de couleur) dans un PDF 1.4.
    """
    try:
        raw = png_path.read_bytes()
        if raw[:8] != b"\x89PNG\r\n\x1a\n":
            return None
        pos = 8
        width = height = bit_depth = color_type = 0
        idat_chunks: List[bytes] = []
        while pos < len(raw):
            length = struct.unpack(">I", raw[pos : pos + 4])[0]
            chunk_type = raw[pos + 4 : pos + 8]
            chunk_data = raw[pos + 8 : pos + 8 + length]
            pos += 12 + length
            if chunk_type == b"IHDR":
                width, height, bit_depth, color_type = struct.unpack(">IIBB", chunk_data[:10])
            elif chunk_type == b"IDAT":
                idat_chunks.append(chunk_data)
            elif chunk_type == b"IEND":
                break

        if bit_depth != 8 or color_type not in (2, 6) or width <= 0 or height <= 0:
            return None

        bpp = 3 if color_type == 2 else 4
        stride = width * bpp
        decompressed = zlib.decompress(b"".join(idat_chunks))

        recon = bytearray(height * stride)
        in_pos = 0

        def paeth(a: int, b: int, c: int) -> int:
            p = a + b - c
            pa = abs(p - a)
            pb = abs(p - b)
            pc = abs(p - c)
            if pa <= pb and pa <= pc:
                return a
            elif pb <= pc:
                return b
            return c

        for row in range(height):
            filter_type = decompressed[in_pos]
            in_pos += 1
            row_start = row * stride
            prev_start = (row - 1) * stride
            for col in range(stride):
                x = decompressed[in_pos]
                in_pos += 1
                a = recon[row_start + col - bpp] if col >= bpp else 0
                b = recon[prev_start + col] if row > 0 else 0
                c = recon[prev_start + col - bpp] if (row > 0 and col >= bpp) else 0
                if filter_type == 0:
                    val = x
                elif filter_type == 1:
                    val = (x + a) & 0xFF
                elif filter_type == 2:
                    val = (x + b) & 0xFF
                elif filter_type == 3:
                    val = (x + ((a + b) >> 1)) & 0xFF
                elif filter_type == 4:
                    val = (x + paeth(a, b, c)) & 0xFF
                else:
                    val = x
                recon[row_start + col] = val

        if color_type == 2:
            rgb_bytes = bytes(recon)
        else:
            # Composite RGBA sur fond blanc pur (255, 255, 255)
            rgb_out = bytearray(width * height * 3)
            out_i = 0
            for i in range(0, len(recon), 4):
                r, g, b_ch, alpha = recon[i], recon[i + 1], recon[i + 2], recon[i + 3]
                if alpha == 255:
                    rgb_out[out_i] = r
                    rgb_out[out_i + 1] = g
                    rgb_out[out_i + 2] = b_ch
                elif alpha == 0:
                    rgb_out[out_i] = 255
                    rgb_out[out_i + 1] = 255
                    rgb_out[out_i + 2] = 255
                else:
                    inv = 255 - alpha
                    rgb_out[out_i] = (r * alpha + 255 * inv) // 255
                    rgb_out[out_i + 1] = (g * alpha + 255 * inv) // 255
                    rgb_out[out_i + 2] = (b_ch * alpha + 255 * inv) // 255
                out_i += 3
            rgb_bytes = bytes(rgb_out)

        return width, height, zlib.compress(rgb_bytes)
    except Exception:
        return None


def _format_date_fr(val: Any, include_time: bool = False) -> str:
    """Formate une date ou un datetime au format français JJ/MM/AAAA (à HH:MM)."""
    if not val:
        return "Non renseigné"
    if isinstance(val, datetime):
        if timezone.is_aware(val):
            val = timezone.localtime(val)
        return val.strftime("%d/%m/%Y à %H:%M") if include_time else val.strftime("%d/%m/%Y")
    if isinstance(val, date):
        return val.strftime("%d/%m/%Y")
    return str(val)


def normalize_admission_data(
    source: Union[Dict[str, Any], Any],
    agent_user: Optional[Any] = None,
) -> Dict[str, str]:
    """
    Normalise les données d'entrée (dictionnaire brut, instance Hospitalization ou instance Patient)
    en un dictionnaire standardisé prêt pour le générateur PDF.
    """
    if isinstance(source, dict):
        raw = source
        return {
            "hospital_name": str(raw.get("hospital_name") or "CLINIQUE SIDI YAHIA 2"),
            "hospital_subtitle": str(
                raw.get("hospital_subtitle")
                or "Établissement Hospitalier Médico-Chirurgical • Direction des Admissions & Soins"
            ),
            "admission_id": str(raw.get("admission_id") or "ADM-2026-0001"),
            "admission_date": _format_date_fr(raw.get("admission_date") or timezone.now(), include_time=True),
            "patient_name": str(raw.get("patient_name") or raw.get("PatientName") or "NON RENSEIGNÉ"),
            "birth_name": str(raw.get("birth_name") or raw.get("BirthName") or raw.get("maiden_name") or "—"),
            "patient_dob": _format_date_fr(raw.get("patient_dob") or raw.get("PatientDOB") or ""),
            "patient_phone": str(raw.get("patient_phone") or raw.get("PatientPhone") or "Non renseigné"),
            "address": str(raw.get("address") or raw.get("Address") or ""),
            "city": str(raw.get("city") or raw.get("City") or ""),
            "state": str(raw.get("state") or raw.get("State") or ""),
            "patient_gov_id": str(
                raw.get("patient_gov_id") or raw.get("PatientID") or raw.get("nir") or raw.get("ipp") or "Non renseigné"
            ),
            "patient_ipp": str(raw.get("patient_ipp") or raw.get("ipp") or "—"),
            "provider_id": str(raw.get("provider_id") or raw.get("providerID") or "Équipe médicale de garde"),
            "service_room_bed": str(raw.get("service_room_bed") or "Attribution en cours"),
            "repr_name": str(raw.get("repr_name") or "........................................................"),
            "repr_relation": str(raw.get("repr_relation") or "Représentant légal / Tuteur"),
            "agent_name": str(
                raw.get("agent_name")
                or (agent_user.get_full_name() or agent_user.username if agent_user and getattr(agent_user, "is_authenticated", False) else "Service des Admissions")
            ),
            "additional_notes": str(raw.get("additional_notes") or ""),
        }

    # Support direct d'une instance Hospitalization ou Patient Django
    model_name = source.__class__.__name__
    if model_name == "Hospitalization":
        hosp = source
        patient = hosp.patient
        practitioner = getattr(hosp, "practitioner", None)
        provider_str = (
            f"Dr {practitioner.get_full_name() or practitioner.username}"
            if practitioner
            else "Médecin praticien référent du service"
        )
        bed_str = str(hosp.bed) if getattr(hosp, "bed", None) else "Non attribué"
        adm_id = f"ADM-{hosp.admission_date.strftime('%Y')}-{hosp.id:05d}" if hosp.id else "ADM-NOUVEAU"
        adm_date = _format_date_fr(hosp.admission_date, include_time=True)
    elif model_name == "Patient":
        patient = source
        hosp = patient.hospitalizations.select_related("bed__service", "practitioner").order_by("-admission_date").first()
        if hosp:
            practitioner = getattr(hosp, "practitioner", None)
            provider_str = (
                f"Dr {practitioner.get_full_name() or practitioner.username}"
                if practitioner
                else "Médecin praticien référent du service"
            )
            bed_str = str(hosp.bed) if getattr(hosp, "bed", None) else "Non attribué"
            adm_id = f"ADM-{hosp.admission_date.strftime('%Y')}-{hosp.id:05d}"
            adm_date = _format_date_fr(hosp.admission_date, include_time=True)
        else:
            provider_str = "Médecin praticien référent"
            bed_str = "Admission ambulatoire / En attente de lit"
            adm_id = f"ADM-{timezone.now().strftime('%Y')}-{patient.id or 1:05d}"
            adm_date = _format_date_fr(timezone.now(), include_time=True)
    else:
        raise ValueError(f"Type de source non supporté pour generateAdmissionPDF : {type(source)}")

    gov_ids = []
    if getattr(patient, "nir", ""):
        gov_ids.append(f"{patient.nir}")
    if getattr(patient, "national_id_number", ""):
        gov_ids.append(f"CI: {patient.national_id_number}")
    if getattr(patient, "ipp", ""):
        gov_ids.append(f"{patient.ipp}")

    return {
        "hospital_name": "CLINIQUE SIDI YAHIA 2",
        "hospital_subtitle": "Établissement Médico-Chirurgical • Service des Admissions",
        "admission_id": adm_id,
        "admission_date": adm_date,
        "patient_name": f"{patient.last_name.upper()} {patient.first_name}".strip(),
        "birth_name": getattr(patient, "maiden_name", "") or patient.last_name.upper(),
        "patient_dob": _format_date_fr(getattr(patient, "birth_date", None)),
        "patient_phone": getattr(patient, "phone", "") or "Non renseigné",
        "address": getattr(patient, "address", "") or "Non renseignée",
        "city": getattr(patient, "city", "") or "",
        "state": getattr(patient, "state_province", "") or "",
        "patient_gov_id": " / ".join(gov_ids) if gov_ids else "Non renseigné",
        "patient_ipp": getattr(patient, "ipp", "—"),
        "provider_id": provider_str,
        "service_room_bed": bed_str,
        "repr_name": getattr(patient, "trusted_person_name", "") or "........................................",
        "repr_relation": getattr(patient, "trusted_person_relation", "") or "Représentant légal / Tuteur",
        "agent_name": (
            agent_user.get_full_name() or agent_user.username
            if agent_user and getattr(agent_user, "is_authenticated", False)
            else "Gestionnaire des Admissions"
        ),
        "additional_notes": "",
    }


# =============================================================================
# MOTEUR 1 : REPORTLAB PLATYPUS (SI INSTALLÉ) AVEC NUMBERED CANVAS (PAGE X SUR Y)
# =============================================================================
def _generate_with_reportlab(data: Dict[str, str]) -> bytes:
    """
    Génère le PDF avec ReportLab Platypus :
    - Marges exactes de 20mm
    - Police Helvetica / Helvetica-Bold
    - En-tête bleu marine (#0C4A6E) + Logo médical vectoriel
    - Bloc de signature indivisible (KeepTogether)
    - Numérotation 'Page X sur Y' via NumberedCanvas en deux passes
    """
    from reportlab.graphics.shapes import Circle, Drawing, Polygon, Rect, String
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT, TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas
    from reportlab.platypus import (
        HRFlowable,
        Image as RLImage,
        KeepTogether,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    NAVY_BLUE = colors.HexColor("#0C4A6E")
    NAVY_DARK = colors.HexColor("#082F49")
    SLATE_DARK = colors.HexColor("#1E293B")
    SLATE_MUTED = colors.HexColor("#475569")
    BG_LIGHT = colors.HexColor("#F8FAFC")
    BORDER_COLOR = colors.HexColor("#CBD5E1")

    class NumberedCanvas(canvas.Canvas):
        """Canvas ReportLab à deux passes pour afficher 'Page X sur Y' en pied de page."""

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._saved_page_states = []

        def showPage(self):
            self._saved_page_states.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            num_pages = len(self._saved_page_states)
            for state in self._saved_page_states:
                self.__dict__.update(state)
                self._draw_footer(num_pages)
                super().showPage()
            super().save()

        def _draw_footer(self, page_count: int) -> None:
            self.saveState()
            page_width, _ = A4
            margin = 20 * mm
            footer_y = 12 * mm

            # Filet horizontal de pied de page
            self.setStrokeColor(BORDER_COLOR)
            self.setLineWidth(0.6)
            self.line(margin, footer_y + 4 * mm, page_width - margin, footer_y + 4 * mm)

            # Mention légale à gauche
            self.setFont("Helvetica", 7.5)
            self.setFillColor(SLATE_MUTED)
            self.drawString(
                margin,
                footer_y,
                f"{data['hospital_name']} • Document médico-légal confidentiel (Conformité HDS / RGPD) • Réf: {data['admission_id']}",
            )

            # Numérotation Page X sur Y à droite
            page_text = f"Page {self._pageNumber} sur {page_count}"
            self.setFont("Helvetica-Bold", 8)
            self.setFillColor(NAVY_BLUE)
            self.drawRightString(page_width - margin, footer_y, page_text)
            self.restoreState()

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
        title=f"Consentement aux soins et décharge - {data['patient_name']}",
        author=data["hospital_name"],
    )

    usable_width = A4[0] - 40 * mm
    styles = getSampleStyleSheet()

    style_hospital_title = ParagraphStyle(
        "HospitalTitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=13,
        leading=16,
        textColor=NAVY_BLUE,
    )
    style_hospital_sub = ParagraphStyle(
        "HospitalSub",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8.5,
        leading=11,
        textColor=SLATE_MUTED,
    )
    style_doc_title = ParagraphStyle(
        "DocTitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=13.5,
        leading=18,
        alignment=TA_CENTER,
        textColor=colors.white,
    )
    style_section_heading = ParagraphStyle(
        "SectionHeading",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=10.5,
        leading=14,
        textColor=NAVY_BLUE,
        spaceBefore=6,
        spaceAfter=4,
    )
    style_body = ParagraphStyle(
        "BodyLegal",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9.5,
        leading=14.5,
        alignment=TA_JUSTIFY,
        textColor=SLATE_DARK,
    )
    style_label = ParagraphStyle(
        "FieldLabel",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8.5,
        leading=12,
        textColor=SLATE_MUTED,
    )
    style_value = ParagraphStyle(
        "FieldValue",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=12,
        textColor=SLATE_DARK,
    )

    story: List[Any] = []

    # 1. EN-TÊTE : Logo officiel de l'hôpital (à gauche, proportions respectées) + Nom de l'établissement
    logo_path = _get_clinic_logo_path()
    if logo_path:
        # Proportions exactes 159x225 (~11.3mm x 16mm) sans déformation
        logo_flowable: Any = RLImage(str(logo_path), width=11.3 * mm, height=16.0 * mm)
    else:
        logo = Drawing(14 * mm, 14 * mm)
        logo.add(Rect(0, 0, 14 * mm, 14 * mm, rx=3 * mm, ry=3 * mm, fillColor=NAVY_BLUE, strokeColor=None))
        logo.add(Rect(5.6 * mm, 2.5 * mm, 2.8 * mm, 9 * mm, fillColor=colors.white, strokeColor=None))
        logo.add(Rect(2.5 * mm, 5.6 * mm, 9 * mm, 2.8 * mm, fillColor=colors.white, strokeColor=None))
        logo_flowable = logo

    header_title_block = [
        Paragraph(data["hospital_name"], style_hospital_title),
        Paragraph(data["hospital_subtitle"], style_hospital_sub),
    ]
    adm_badge_para = Paragraph(
        f"<b>N° d'Admission :</b> {data['admission_id']}<br/>"
        f"<b>Date &amp; Heure :</b> {data['admission_date']}",
        ParagraphStyle(
            "AdmMeta",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=8.5,
            leading=12,
            alignment=TA_RIGHT,
            textColor=SLATE_DARK,
        ),
    )

    top_header_table = Table(
        [[logo_flowable, header_title_block, adm_badge_para]],
        colWidths=[16 * mm, usable_width - 71 * mm, 55 * mm],
    )
    top_header_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2 * mm),
            ]
        )
    )
    story.append(top_header_table)
    story.append(Spacer(1, 2 * mm))

    # Bandeau Titre Centré, Gras, Grand : FORMULAIRE DE CONSENTEMENT AUX SOINS ET DÉCHARGE
    banner_table = Table(
        [[Paragraph("FORMULAIRE DE CONSENTEMENT AUX SOINS ET DÉCHARGE", style_doc_title)]],
        colWidths=[usable_width],
    )
    banner_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), NAVY_BLUE),
                ("TOPPADDING", (0, 0), (-1, -1), 3.2 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3.2 * mm),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ]
        )
    )
    story.append(banner_table)
    story.append(Spacer(1, 4 * mm))

    # 2. BLOC IDENTIFICATION DU PATIENT(E) & INFORMATIONS D'ADMISSION
    story.append(Paragraph("1. IDENTIFICATION DU PATIENT(E) ET INFORMATIONS D'ADMISSION", style_section_heading))

    full_address = " ".join(part for part in [data["address"], data["city"], data["state"]] if part).strip() or "Non renseignée"

    id_rows = [
        [
            Paragraph("N° d'Admission :", style_label),
            Paragraph(f"<b>{data['admission_id']}</b>", style_value),
            Paragraph("Date &amp; Heure :", style_label),
            Paragraph(data["admission_date"], style_value),
        ],
        [
            Paragraph("Nom &amp; Prénom du Patient :", style_label),
            Paragraph(f"<b>{data['patient_name']}</b>", style_value),
            Paragraph("Nom de naissance :", style_label),
            Paragraph(data["birth_name"], style_value),
        ],
        [
            Paragraph("Date de naissance :", style_label),
            Paragraph(data["patient_dob"], style_value),
            Paragraph("Téléphone :", style_label),
            Paragraph(data["patient_phone"], style_value),
        ],
        [
            Paragraph("Adresse complète :", style_label),
            Paragraph(full_address, style_value),
            Paragraph("Service / Lit :", style_label),
            Paragraph(data["service_room_bed"], style_value),
        ],
        [
            Paragraph("N° Sécurité Sociale / PC ou CI :", style_label),
            Paragraph(data["patient_gov_id"], style_value),
            Paragraph("Suivi par le Docteur(e) :", style_label),
            Paragraph(f"<b>{data['provider_id']}</b>", style_value),
        ],
    ]

    id_table = Table(
        id_rows,
        colWidths=[43 * mm, 45 * mm, 37 * mm, usable_width - 125 * mm],
    )
    id_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), BG_LIGHT),
                ("BOX", (0, 0), (-1, -1), 0.75, BORDER_COLOR),
                ("INNERGRID", (0, 0), (-1, -1), 0.4, BORDER_COLOR),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 2.2 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2.2 * mm),
                ("LEFTPADDING", (0, 0), (-1, -1), 2.5 * mm),
                ("RIGHTPADDING", (0, 0), (-1, -1), 2.5 * mm),
            ]
        )
    )
    story.append(id_table)
    story.append(Spacer(1, 5 * mm))

    # 3. CORPS DU TEXTE — SECTION CONSENTEMENT AUX SOINS & ANESTHÉSIE
    story.append(Paragraph("2. CONSENTEMENT ÉCLAIRÉ AUX SOINS, EXAMENS ET INTERVENTIONS", style_section_heading))

    consent_paragraph_1 = (
        f"Je soussigné(e), <b>{data['patient_name']}</b> (ou son représentant légal "
        f"<b>{data['repr_name']}</b>, agissant en qualité de <b>{data['repr_relation']}</b>), "
        f"donne par la présente mon consentement libre et éclairé pour les soins, examens, "
        f"interventions et traitements médicaux jugés nécessaires par l'équipe médicale de l'établissement."
    )
    consent_paragraph_2 = (
        f"Je soussigné(e) déclare avoir pris connaissance de ma maladie, du type d'intervention/examens, "
        f"des risques opératoires liés à l'anesthésie ainsi qu'à l'intervention que je dois subir et donne "
        f"mon consentement pour les soins prescrits par mon médecin (<b>{data['provider_id']}</b>)."
    )

    consent_box = Table(
        [[Paragraph(consent_paragraph_1 + "<br/><br/>" + consent_paragraph_2, style_body)]],
        colWidths=[usable_width],
    )
    consent_box.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 0.6, BORDER_COLOR),
                ("LEFTPADDING", (0, 0), (-1, -1), 4 * mm),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 3.5 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5 * mm),
            ]
        )
    )
    story.append(consent_box)
    story.append(Spacer(1, 5 * mm))

    # 4. CORPS DU TEXTE — SECTION DÉCHARGE & RESPONSABILITÉ
    story.append(Paragraph("3. DÉCHARGE DE RESPONSABILITÉ & EFFETS PERSONNELS", style_section_heading))

    discharge_paragraph = (
        "Je reconnais avoir été informé(e) des risques potentiels liés aux traitements et procédures. "
        "De plus, je décharge l'établissement de toute responsabilité concernant la perte ou le vol "
        "d'objets de valeur non déposés au coffre de l'hôpital lors de mon admission."
    )
    discharge_box = Table(
        [[Paragraph(discharge_paragraph, style_body)]],
        colWidths=[usable_width],
    )
    discharge_box.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), BG_LIGHT),
                ("BOX", (0, 0), (-1, -1), 0.6, BORDER_COLOR),
                ("LEFTPADDING", (0, 0), (-1, -1), 4 * mm),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 3.5 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5 * mm),
            ]
        )
    )
    story.append(discharge_box)

    if data.get("additional_notes"):
        story.append(Spacer(1, 4 * mm))
        story.append(Paragraph("OBSERVATIONS COMPLÉMENTAIRES D'ADMISSION", style_section_heading))
        story.append(Paragraph(data["additional_notes"], style_body))

    story.append(Spacer(1, 7 * mm))

    # 5. BLOC DE SIGNATURE CÔTÉ À CÔTE (Protégé par KeepTogether contre l'isolement sur page blanche)
    col_w = (usable_width - 6 * mm) / 2.0

    patient_sig_content = [
        Paragraph("<b>Signature du Patient(e) (ou représentant légal) :</b>", style_value),
        Spacer(1, 2 * mm),
        Paragraph(f"Nom complet : <b>{data['patient_name']}</b>", style_value),
        Paragraph("<i>(Précédé de la mention « Lu et approuvé »)</i>", style_hospital_sub),
        Spacer(1, 14 * mm),
        Paragraph("Signature : ____________________________________", style_value),
        Spacer(1, 3 * mm),
        Paragraph("Date : ____ / ____ / ________", style_value),
    ]

    agent_sig_content = [
        Paragraph("<b>Signature de l'Agent d'Admission :</b>", style_value),
        Spacer(1, 2 * mm),
        Paragraph(f"Agent : <b>{data['agent_name']}</b>", style_value),
        Paragraph("<i>(Cachet du Bureau des Admissions &amp; Signature)</i>", style_hospital_sub),
        Spacer(1, 14 * mm),
        Paragraph("Signature : ____________________________________", style_value),
        Spacer(1, 3 * mm),
        Paragraph(f"Date : {data['admission_date'][:10]}", style_value),
    ]

    sig_table = Table(
        [[patient_sig_content, "", agent_sig_content]],
        colWidths=[col_w, 6 * mm, col_w],
    )
    sig_table.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (0, 0), 0.75, NAVY_BLUE),
                ("BOX", (2, 0), (2, 0), 0.75, NAVY_BLUE),
                ("BACKGROUND", (0, 0), (0, 0), BG_LIGHT),
                ("BACKGROUND", (2, 0), (2, 0), BG_LIGHT),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (0, 0), 4 * mm),
                ("RIGHTPADDING", (0, 0), (0, 0), 4 * mm),
                ("TOPPADDING", (0, 0), (0, 0), 3.5 * mm),
                ("BOTTOMPADDING", (0, 0), (0, 0), 4 * mm),
                ("LEFTPADDING", (2, 0), (2, 0), 4 * mm),
                ("RIGHTPADDING", (2, 0), (2, 0), 4 * mm),
                ("TOPPADDING", (2, 0), (2, 0), 3.5 * mm),
                ("BOTTOMPADDING", (2, 0), (2, 0), 4 * mm),
            ]
        )
    )

    signature_block = KeepTogether(
        [
            Paragraph("4. VALIDATION ET SIGNATURES DES PARTIES", style_section_heading),
            Spacer(1, 1.5 * mm),
            sig_table,
        ]
    )
    story.append(signature_block)

    doc.build(story, canvasmaker=NumberedCanvas)
    return buffer.getvalue()


# =============================================================================
# MOTEUR 2 : GÉNÉRATEUR PDF 1.4 NATIF AUTONOME (ZÉRO DÉPENDANCE EXTERNE)
# =============================================================================
def _pdf_escape(text: str) -> bytes:
    """Encode une chaîne Unicode en bytes WinAnsi (CP1252) échappés pour les flux PDF."""
    cleaned = (
        text.replace("—", "-")
        .replace("–", "-")
        .replace("•", "\xb7")
        .replace("’", "'")
        .replace("…", "...")
    )
    raw = cleaned.encode("cp1252", errors="replace")
    out = bytearray()
    for b in raw:
        if b in (40, 41, 92):  # ( ) \
            out.append(92)
            out.append(b)
        elif b < 32 or b > 126:
            out.extend(f"\\{b:03o}".encode("ascii"))
        else:
            out.append(b)
    return bytes(out)


def _generate_with_native_pdf(data: Dict[str, str]) -> bytes:
    """
    Générateur PDF 1.4 vectoriel autonome (sans librairie tierce requise) :
    - Format A4 (595.28 x 841.89 pt), marges exactes de 20mm (56.69 pt)
    - Police Helvetica (/F1) et Helvetica-Bold (/F2) avec WinAnsiEncoding
    - En-tête Bleu Marine (#0C4A6E), tableau d'identification, sections Consentement & Décharge
    - Gestion des sauts de page pour ne jamais isoler le bloc de signature
    - Pied de page 'Page X sur Y' sur toutes les pages
    """
    PAGE_W = 595.28
    PAGE_H = 841.89
    MARGIN = 56.69  # 20 mm exactement (20 * 72 / 25.4)
    USABLE_W = PAGE_W - 2 * MARGIN
    BOTTOM_LIMIT = MARGIN + 35.0
    SIGNATURE_BLOCK_HEIGHT = 165.0

    pages_ops: List[List[bytes]] = [[]]
    y = PAGE_H - MARGIN

    def current_ops() -> List[bytes]:
        return pages_ops[-1]

    def new_page() -> None:
        nonlocal y
        pages_ops.append([])
        y = PAGE_H - MARGIN

    def draw_text(x: float, y_pos: float, text: str, bold: bool = False, size: float = 9.5, rgb: Tuple[float, float, float] = (0.12, 0.16, 0.23)) -> None:
        font = b"/F2" if bold else b"/F1"
        r, g, b = rgb
        cmd = (
            f"BT {r:.3f} {g:.3f} {b:.3f} rg {font.decode()} {size:.1f} Tf "
            f"1 0 0 1 {x:.2f} {y_pos:.2f} Tm (".encode("ascii")
            + _pdf_escape(text)
            + b") Tj ET"
        )
        current_ops().append(cmd)

    def draw_rect(x: float, y_pos: float, w: float, h: float, fill_rgb: Optional[Tuple[float, float, float]] = None, stroke_rgb: Optional[Tuple[float, float, float]] = None, line_w: float = 0.7) -> None:
        parts = [f"{line_w:.2f} w"]
        if fill_rgb:
            parts.append(f"{fill_rgb[0]:.3f} {fill_rgb[1]:.3f} {fill_rgb[2]:.3f} rg")
        if stroke_rgb:
            parts.append(f"{stroke_rgb[0]:.3f} {stroke_rgb[1]:.3f} {stroke_rgb[2]:.3f} RG")
        op = "B" if (fill_rgb and stroke_rgb) else ("f" if fill_rgb else "S")
        parts.append(f"{x:.2f} {y_pos:.2f} {w:.2f} {h:.2f} re {op}")
        current_ops().append(" ".join(parts).encode("ascii"))

    # 1. EN-TÊTE : Logo officiel de la clinique (proportions 159:225 exactes) + Nom de l'hôpital + N° Admission
    logo_path = _get_clinic_logo_path()
    decoded_logo = _decode_png_to_rgb_flate(logo_path) if logo_path else None

    if decoded_logo:
        img_w_px, img_h_px, _ = decoded_logo
        # Hauteur d'affichage 40 pt, largeur proportionnelle (~28.3 pt) pour respecter strictement le ratio
        disp_h = 40.0
        disp_w = disp_h * (img_w_px / float(img_h_px))
        current_ops().append(
            f"q {disp_w:.2f} 0 0 {disp_h:.2f} {MARGIN:.2f} {y - disp_h + 2.0:.2f} cm /ImLogo Do Q".encode("ascii")
        )
        text_x_offset = MARGIN + disp_w + 10.0
    else:
        logo_size = 36.0
        draw_rect(MARGIN, y - logo_size, logo_size, logo_size, fill_rgb=(0.047, 0.290, 0.431))
        draw_rect(MARGIN + 14.0, y - 30.0, 8.0, 24.0, fill_rgb=(1.0, 1.0, 1.0))
        draw_rect(MARGIN + 6.0, y - 22.0, 24.0, 8.0, fill_rgb=(1.0, 1.0, 1.0))
        text_x_offset = MARGIN + 44.0

    draw_text(text_x_offset, y - 14.0, data["hospital_name"], bold=True, size=13.0, rgb=(0.047, 0.290, 0.431))
    draw_text(text_x_offset, y - 27.0, data["hospital_subtitle"][:58], bold=False, size=8.0, rgb=(0.28, 0.33, 0.41))
    draw_text(PAGE_W - MARGIN - 145.0, y - 14.0, f"N° Admission : {data['admission_id']}", bold=True, size=8.5)
    draw_text(PAGE_W - MARGIN - 145.0, y - 27.0, f"Date : {data['admission_date']}", bold=False, size=8.0, rgb=(0.28, 0.33, 0.41))

    y -= 46.0

    # Bandeau Titre Centré : FORMULAIRE DE CONSENTEMENT AUX SOINS ET DÉCHARGE
    banner_h = 26.0
    draw_rect(MARGIN, y - banner_h, USABLE_W, banner_h, fill_rgb=(0.047, 0.290, 0.431))
    draw_text(MARGIN + 52.0, y - 17.0, "FORMULAIRE DE CONSENTEMENT AUX SOINS ET DÉCHARGE", bold=True, size=12.5, rgb=(1.0, 1.0, 1.0))
    y -= banner_h + 16.0

    # 2. SECTION 1 : IDENTIFICATION DU PATIENT(E)
    draw_text(MARGIN, y, "1. IDENTIFICATION DU PATIENT(E) ET INFORMATIONS D'ADMISSION", bold=True, size=10.5, rgb=(0.047, 0.290, 0.431))
    y -= 8.0

    full_address = ", ".join(part for part in [data["address"], data["city"], data["state"]] if part).strip() or "Non renseignée"
    id_box_h = 110.0
    draw_rect(MARGIN, y - id_box_h, USABLE_W, id_box_h, fill_rgb=(0.973, 0.980, 0.988), stroke_rgb=(0.796, 0.835, 0.882))

    mid_x = MARGIN + USABLE_W * 0.52
    current_ops().append(f"0.45 w 0.82 0.86 0.90 RG {mid_x:.2f} {y - id_box_h:.2f} m {mid_x:.2f} {y:.2f} l S".encode("ascii"))

    rows_info = [
        ("N° d'Admission :", data["admission_id"], "Date & Heure :", data["admission_date"]),
        ("Nom & Prénom :", data["patient_name"][:28], "Nom de naissance :", data["birth_name"][:24]),
        ("Date de naissance :", data["patient_dob"], "Téléphone :", data["patient_phone"][:22]),
        ("Adresse :", full_address[:34], "Service / Lit :", data["service_room_bed"][:28]),
        ("N° Sécu / PC-CI :", data["patient_gov_id"][:32], "Suivi par Dr :", data["provider_id"][:28]),
    ]
    row_y = y - 16.0
    for idx_r, (l_lbl, l_val, r_lbl, r_val) in enumerate(rows_info):
        draw_text(MARGIN + 8.0, row_y, l_lbl, bold=True, size=8.3, rgb=(0.28, 0.33, 0.41))
        draw_text(MARGIN + 92.0, row_y, l_val, bold=False, size=8.6)
        draw_text(mid_x + 8.0, row_y, r_lbl, bold=True, size=8.3, rgb=(0.28, 0.33, 0.41))
        draw_text(mid_x + 88.0, row_y, r_val, bold=False, size=8.6)
        if idx_r < len(rows_info) - 1:
            line_y_sep = row_y - 6.5
            current_ops().append(
                f"0.35 w 0.85 0.88 0.92 RG {MARGIN:.2f} {line_y_sep:.2f} m {MARGIN + USABLE_W:.2f} {line_y_sep:.2f} l S".encode("ascii")
            )
        row_y -= 21.5

    y -= id_box_h + 18.0

    # Helper pour écrire une section encadrée avec retour à la ligne automatique
    def write_section_box(title: str, paragraphs: List[str], fill: Optional[Tuple[float, float, float]] = None) -> None:
        nonlocal y
        wrapped_lines: List[str] = []
        for p in paragraphs:
            lines = textwrap.wrap(p, width=85)
            wrapped_lines.extend(lines)
            wrapped_lines.append("")
        if wrapped_lines and wrapped_lines[-1] == "":
            wrapped_lines.pop()

        box_h = len(wrapped_lines) * 14.0 + 18.0
        if y - (box_h + 24.0) < BOTTOM_LIMIT:
            new_page()

        draw_text(MARGIN, y, title, bold=True, size=10.5, rgb=(0.047, 0.290, 0.431))
        y -= 8.0
        draw_rect(MARGIN, y - box_h, USABLE_W, box_h, fill_rgb=fill, stroke_rgb=(0.796, 0.835, 0.882))
        line_y = y - 16.0
        for ln in wrapped_lines:
            if ln:
                draw_text(MARGIN + 12.0, line_y, ln, bold=False, size=9.3)
            line_y -= 14.0
        y -= box_h + 18.0

    # 3. SECTION 2 : CONSENTEMENT AUX SOINS
    consent_p1 = (
        f"Je soussigné(e), {data['patient_name']} (ou son représentant légal {data['repr_name']}, "
        f"agissant en qualité de {data['repr_relation']}), donne par la présente mon consentement "
        f"libre et éclairé pour les soins, examens, interventions et traitements médicaux jugés "
        f"nécessaires par l'équipe médicale de l'établissement."
    )
    consent_p2 = (
        f"Je soussigné(e) avoir pris connaissance de ma maladie, du type d'intervention/examens, "
        f"des risques opératoires liés à l'anesthésie ainsi qu'à l'intervention que je dois subir "
        f"et donne mon consentement pour les soins prescrits par mon médecin ({data['provider_id']})."
    )
    write_section_box("2. CONSENTEMENT ÉCLAIRÉ AUX SOINS, EXAMENS ET INTERVENTIONS", [consent_p1, consent_p2])

    # 4. SECTION 3 : DÉCHARGE & RESPONSABILITÉ
    discharge_p = (
        "Je reconnais avoir été informé(e) des risques potentiels liés aux traitements et procédures. "
        "De plus, je décharge l'établissement de toute responsabilité concernant la perte ou le vol "
        "d'objets de valeur non déposés au coffre de l'hôpital lors de mon admission."
    )
    write_section_box(
        "3. DÉCHARGE DE RESPONSABILITÉ & EFFETS PERSONNELS",
        [discharge_p],
        fill=(0.973, 0.980, 0.988),
    )

    if data.get("additional_notes"):
        write_section_box("OBSERVATIONS COMPLÉMENTAIRES", [data["additional_notes"]])

    # 5. BLOC DE SIGNATURE CÔTÉ À CÔTE (Protection anti-isolement sur page blanche)
    if y - SIGNATURE_BLOCK_HEIGHT < BOTTOM_LIMIT:
        new_page()

    draw_text(MARGIN, y, "4. VALIDATION ET SIGNATURES DES PARTIES", bold=True, size=10.5, rgb=(0.047, 0.290, 0.431))
    y -= 10.0

    col_w = (USABLE_W - 16.0) / 2.0
    sig_h = 125.0

    # Cadre Gauche : Patient / Représentant légal
    draw_rect(MARGIN, y - sig_h, col_w, sig_h, fill_rgb=(0.973, 0.980, 0.988), stroke_rgb=(0.047, 0.290, 0.431), line_w=0.9)
    draw_text(MARGIN + 10.0, y - 18.0, "Signature du Patient(e) (ou représentant) :", bold=True, size=9.0)
    draw_text(MARGIN + 10.0, y - 34.0, f"Nom complet : {data['patient_name'][:32]}", bold=False, size=8.5)
    draw_text(MARGIN + 10.0, y - 47.0, "(Mention manuscrite « Lu et approuvé »)", bold=False, size=7.8, rgb=(0.28, 0.33, 0.41))
    draw_text(MARGIN + 10.0, y - 88.0, "Signature : _______________________________", bold=False, size=8.8)
    draw_text(MARGIN + 10.0, y - 108.0, "Date : ____ / ____ / ________", bold=False, size=8.8)

    # Cadre Droite : Agent d'Admission
    right_x = MARGIN + col_w + 16.0
    draw_rect(right_x, y - sig_h, col_w, sig_h, fill_rgb=(0.973, 0.980, 0.988), stroke_rgb=(0.047, 0.290, 0.431), line_w=0.9)
    draw_text(right_x + 10.0, y - 18.0, "Signature de l'Agent d'Admission :", bold=True, size=9.0)
    draw_text(right_x + 10.0, y - 34.0, f"Agent : {data['agent_name'][:34]}", bold=False, size=8.5)
    draw_text(right_x + 10.0, y - 47.0, "(Cachet de l'établissement & Signature)", bold=False, size=7.8, rgb=(0.28, 0.33, 0.41))
    draw_text(right_x + 10.0, y - 88.0, "Signature : _______________________________", bold=False, size=8.8)
    draw_text(right_x + 10.0, y - 108.0, f"Date : {data['admission_date'][:10]}", bold=False, size=8.8)

    # 6. PIED DE PAGE SUR CHAQUE PAGE : "Page X sur Y"
    total_pages = len(pages_ops)
    for idx, ops in enumerate(pages_ops, start=1):
        footer_y = 34.0
        ops.append(f"0.60 w 0.796 0.835 0.882 RG {MARGIN:.2f} {footer_y + 10:.2f} m {PAGE_W - MARGIN:.2f} {footer_y + 10:.2f} l S".encode("ascii"))
        left_footer = f"{data['hospital_name']} - Consentement aux soins et décharge (Réf: {data['admission_id']})"
        ops.append(
            f"BT 0.28 0.33 0.41 rg /F1 7.5 Tf 1 0 0 1 {MARGIN:.2f} {footer_y:.2f} Tm (".encode("ascii")
            + _pdf_escape(left_footer)
            + b") Tj ET"
        )
        page_label = f"Page {idx} sur {total_pages}"
        ops.append(
            f"BT 0.047 0.290 0.431 rg /F2 8.5 Tf 1 0 0 1 {PAGE_W - MARGIN - 58.0:.2f} {footer_y:.2f} Tm (".encode("ascii")
            + _pdf_escape(page_label)
            + b") Tj ET"
        )

    # Assemblage de la structure binaire PDF 1.4
    objects: List[bytes] = []

    def add_obj(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    font1_id = add_obj(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    font2_id = add_obj(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")

    logo_xobj_id: Optional[int] = None
    if decoded_logo:
        img_w_px, img_h_px, compressed_rgb = decoded_logo
        logo_xobj_id = add_obj(
            (
                f"<< /Type /XObject /Subtype /Image /Width {img_w_px} /Height {img_h_px} "
                f"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /FlateDecode /Length {len(compressed_rgb)} >>\nstream\n"
            ).encode("ascii")
            + compressed_rgb
            + b"\nendstream"
        )

    pages_tree_id = add_obj(b"")  # Placeholder pour /Pages
    page_ids: List[int] = []

    xobj_res = f" /XObject << /ImLogo {logo_xobj_id} 0 R >>" if logo_xobj_id else ""

    for ops in pages_ops:
        stream_bytes = b"\n".join(ops)
        content_id = add_obj(
            f"<< /Length {len(stream_bytes)} >>\nstream\n".encode("ascii")
            + stream_bytes
            + b"\nendstream"
        )
        page_id = add_obj(
            f"<< /Type /Page /Parent {pages_tree_id} 0 R "
            f"/MediaBox [0 0 {PAGE_W:.2f} {PAGE_H:.2f}] "
            f"/Resources << /Font << /F1 {font1_id} 0 R /F2 {font2_id} 0 R >>{xobj_res} >> "
            f"/Contents {content_id} 0 R >>".encode("ascii")
        )
        page_ids.append(page_id)

    kids_str = " ".join(f"{pid} 0 R" for pid in page_ids)
    objects[pages_tree_id - 1] = f"<< /Type /Pages /Kids [{kids_str}] /Count {len(page_ids)} >>".encode("ascii")
    catalog_id = add_obj(f"<< /Type /Catalog /Pages {pages_tree_id} 0 R >>".encode("ascii"))

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets: List[int] = []
    for i, obj_bytes in enumerate(objects, start=1):
        offsets.append(len(out))
        out.extend(f"{i} 0 obj\n".encode("ascii"))
        out.extend(obj_bytes)
        out.extend(b"\nendobj\n")

    xref_pos = len(out)
    out.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    out.extend(b"0000000000 65535 f \n")
    for off in offsets:
        out.extend(f"{off:010d} 00000 n \n".encode("ascii"))

    out.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root {catalog_id} 0 R >>\n"
        f"startxref\n{xref_pos}\n%%EOF\n".encode("ascii")
    )
    return bytes(out)


def generate_admission_consent_pdf(
    admission_data: Union[Dict[str, Any], Any],
    output_path: Optional[Union[str, Path]] = None,
    agent_user: Optional[Any] = None,
) -> bytes:
    """
    Fonction / Service principal réutilisable pour générer le rapport PDF
    « FORMULAIRE DE CONSENTEMENT AUX SOINS ET DÉCHARGE ».

    Arguments:
        admission_data: Dictionnaire de données d'admission, instance `Hospitalization` ou instance `Patient`.
        output_path: Chemin fichier optionnel où enregistrer le PDF sur le serveur.
        agent_user: Utilisateur (Agent d'admission / Médecin) ayant déclenché l'édition.

    Retourne:
        Les octets (bytes) du document PDF généré.
    """
    normalized = normalize_admission_data(admission_data, agent_user=agent_user)

    try:
        pdf_bytes = _generate_with_reportlab(normalized)
    except ImportError:
        pdf_bytes = _generate_with_native_pdf(normalized)

    if output_path:
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(pdf_bytes)

    return pdf_bytes


# Alias camelCase conforme à la spécification technique demandée : generateAdmissionPDF(admissionData)
generateAdmissionPDF = generate_admission_consent_pdf

