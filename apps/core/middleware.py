"""
Middleware de sécurité HDS / RGPD :
1. StrictAuthenticationMiddleware : Interdit tout accès anonyme à l'application hospitalière.
2. RoleInactivityTimeoutMiddleware : Déconnecte automatiquement toute session inactive depuis plus
   de 5 minutes (300 secondes) pour le rôle GESTIONNAIRE_ADMISSION (ou selon la politique de sécurité),
   avec journalisation immuable dans SecurityAuditLog.
"""

import time
from django.conf import settings
from django.contrib.auth import logout
from django.shortcuts import redirect

from .models import AuditActionType, SecurityAuditLog, UserRole


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


class RoleInactivityTimeoutMiddleware:
    """
    Implémente l'expiration automatique de session après 5 minutes (300 secondes)
    d'inactivité pour le rôle GESTIONNAIRE_ADMISSION (poste d'accueil/admission exposé).
    """

    ROLE_TIMEOUTS_SECONDS = {
        UserRole.GESTIONNAIRE_ADMISSION: 300,  # 5 minutes strictes (300s)
    }
    DEFAULT_TIMEOUT_SECONDS = 28800  # 8 heures pour les sessions médicales standards

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            now_ts = int(time.time())
            user_role = getattr(request.user, "role", None)
            max_idle = self.ROLE_TIMEOUTS_SECONDS.get(user_role, self.DEFAULT_TIMEOUT_SECONDS)

            last_activity = request.session.get("last_activity_ts")
            if last_activity is not None and (now_ts - int(last_activity)) > max_idle:
                SecurityAuditLog.log_action(
                    user=request.user,
                    action_type=AuditActionType.SESSION_TIMEOUT,
                    resource_name="Session",
                    details=f"Session expirée automatiquement après {now_ts - int(last_activity)}s d'inactivité (seuil: {max_idle}s).",
                    ip_address=request.META.get("REMOTE_ADDR"),
                )
                logout(request)
                login_url = getattr(settings, "LOGIN_URL", "/login/")
                return redirect(f"{login_url}?timeout=1")

            request.session["last_activity_ts"] = now_ts

        return self.get_response(request)


