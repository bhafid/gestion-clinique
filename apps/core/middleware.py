"""
Middleware de sécurité HDS / RGPD :
Interdit tout accès anonyme à l'application hospitalière.
Toute requête non authentifiée est redirigée vers le portail de connexion (/login/).
"""

from django.conf import settings
from django.shortcuts import redirect


class StrictAuthenticationMiddleware:
    """
    Garantit qu'aucune page du SIH (Tableau de bord, lits, plannings, pôles cliniques)
    n'est accessible sans authentification préalable.
    """

    EXEMPT_PREFIXES = (
        "/login/",
        "/logout/",
        "/admin/login/",
        "/static/",
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.user.is_authenticated:
            path = request.path_info
            if not any(path.startswith(prefix) for prefix in self.EXEMPT_PREFIXES):
                login_url = getattr(settings, "LOGIN_URL", "/login/")
                return redirect(f"{login_url}?next={request.get_full_path()}")
        return self.get_response(request)

