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


def clinic_branding(request: HttpRequest) -> Dict[str, str]:
    """Injecte CLINIC_LOGO_DATA_URI dans tous les templates Django."""
    return {
        "CLINIC_LOGO_DATA_URI": get_clinic_logo_data_uri(),
    }

