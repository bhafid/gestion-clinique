"""
Context processors globaux pour l'identité visuelle de la Clinique Sidi Yahia 2.
Garantit l'affichage du logo officiel sur tous les environnements (Ubuntu, Gunicorn, Nginx, Local)
grâce à un encodage Data URI Base64 en mémoire avec repli sur /static/images/logo_clinique.png.
"""

import base64
from functools import lru_cache
from pathlib import Path
from typing import Dict

from django.conf import settings
from django.http import HttpRequest


@lru_cache(maxsize=1)
def get_clinic_logo_data_uri() -> str:
    """
    Charge le logo officiel de la clinique depuis static/images/logo_clinique.png
    et le convertit en Data URI Base64 (mis en cache en mémoire).
    Permet un affichage instantané à 100% sur le serveur Ubuntu même sans collectstatic/Nginx.
    """
    candidate_paths = [
        Path(settings.BASE_DIR) / "static" / "images" / "logo_clinique.png",
        Path(settings.STATIC_ROOT) / "images" / "logo_clinique.png",
    ]
    for logo_path in candidate_paths:
        if logo_path.exists() and logo_path.is_file():
            try:
                raw_bytes = logo_path.read_bytes()
                b64_str = base64.b64encode(raw_bytes).decode("ascii")
                return f"data:image/png;base64,{b64_str}"
            except OSError:
                continue
    return "/static/images/logo_clinique.png"


def get_clinic_parameters_dict() -> Dict[str, str]:
    """
    Récupère les paramètres officiels de la clinique depuis la base de données (EtablissementFiscal)
    avec des valeurs de repli par défaut pour la Clinique Sidi Yahia 2.
    """
    defaults = {
        "nom_clinique": "Clinique Sidi Yahia 2",
        "raison_sociale": "SARL CLINIQUE MÉDICO-CHIRURGICALE SIDI YAHIA 2",
        "forme_juridique": "SARL au capital social de 50 000 000,00 DA",
        "adresse_complete": "27 chemin Ahmed KARA - Bir Mourad Rais - Alger, Algerie",
        "wilaya": "16 - Alger",
        "telephone": "+213 770 79 46 30",
        "email": "sidiyahiaclinique2@gmail.com",
        "site_web": "",
        "directeur_etablissement": "Direction Générale & Médicale",
        "nif": "002116099123456",
        "nis": "099916100654321",
        "rc": "16/00-1048291B21",
        "article_imposition": "16125849012",
        "rib_bancaire": "BEA Agence Hydra Alger : 002 00012 1203456789 44",
        "numero_convention_cnas": "CONV-CNAS-DZ-16-2026-089",
    }
    try:
        from apps.facturation.models import EtablissementFiscal

        etab = EtablissementFiscal.objects.first()
        if etab:
            return {
                "nom_clinique": getattr(etab, "nom_clinique", "") or defaults["nom_clinique"],
                "raison_sociale": etab.raison_sociale or defaults["raison_sociale"],
                "forme_juridique": etab.forme_juridique or defaults["forme_juridique"],
                "adresse_complete": etab.adresse_complete or defaults["adresse_complete"],
                "wilaya": etab.wilaya or defaults["wilaya"],
                "telephone": etab.telephone or defaults["telephone"],
                "email": getattr(etab, "email", "") or defaults["email"],
                "site_web": getattr(etab, "site_web", "") or "",
                "directeur_etablissement": getattr(etab, "directeur_etablissement", "") or defaults["directeur_etablissement"],
                "nif": etab.nif or defaults["nif"],
                "nis": etab.nis or defaults["nis"],
                "rc": etab.rc or defaults["rc"],
                "article_imposition": etab.article_imposition or defaults["article_imposition"],
                "rib_bancaire": etab.rib_bancaire or defaults["rib_bancaire"],
                "numero_convention_cnas": etab.numero_convention_cnas or defaults["numero_convention_cnas"],
            }
    except Exception:
        pass
    return defaults


def clinic_branding(request: HttpRequest) -> Dict[str, object]:
    """Injecte CLINIC_LOGO_DATA_URI et CLINIC_INFO dans tous les templates Django."""
    info = get_clinic_parameters_dict()
    return {
        "CLINIC_LOGO_DATA_URI": get_clinic_logo_data_uri(),
        "CLINIC_INFO": info,
        "CLINIC_NAME": info["nom_clinique"],
        "CLINIC_ADDRESS": info["adresse_complete"],
        "CLINIC_PHONE": info["telephone"],
        "CLINIC_EMAIL": info["email"],
    }


