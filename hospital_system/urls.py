"""
Configuration du routage centralisé pour hospital_system.
Intègre le Dashboard hebdomadaire, l'interface d'administration personnalisée HDS,
et l'accès modulaire aux différentes spécialités hospitalières.
"""

from pathlib import Path

from django.conf import settings
from django.contrib import admin
from django.contrib.staticfiles import finders
from django.http import Http404
from django.urls import include, path, re_path
from django.views.static import serve

from apps.core.views import HospitalLoginView, WeeklyDashboardView, hospital_logout_view


def serve_static_with_fallback(request, path: str):
    """
    Sert les fichiers statiques (images, logo, CSS/JS Admin) aussi bien depuis STATIC_ROOT
    (staticfiles/) que depuis BASE_DIR/static/ ou les répertoires d'applications Django,
    garantissant l'affichage du logo sur Ubuntu (Gunicorn/Nginx) même avant collectstatic.
    """
    static_root_file = Path(settings.STATIC_ROOT) / path
    if static_root_file.exists() and static_root_file.is_file():
        return serve(request, path, document_root=settings.STATIC_ROOT)

    static_dir_file = Path(settings.BASE_DIR) / "static" / path
    if static_dir_file.exists() and static_dir_file.is_file():
        return serve(request, path, document_root=Path(settings.BASE_DIR) / "static")

    found_path = finders.find(path)
    if found_path:
        found_file = Path(found_path)
        return serve(request, found_file.name, document_root=found_file.parent)

    raise Http404(f"Fichier statique introuvable : {path}")

# -----------------------------------------------------------------------------
# Personnalisation de l'Administration Hospitalière (Branding & HDS)
# -----------------------------------------------------------------------------
# admin.site.site_header = "Centre Hospitalier Universitaire (CHU) - Portail Médical HDS"
admin.site.site_header = "CLinique Sidi Yahia 2"
admin.site.site_title = "SIH - Dossiers Patients & Soins"
admin.site.index_title = "Supervision Hospitalière & Gestion des Pôles Cliniques"

urlpatterns = [
    # Authentification unifiée multi-rôles (aucun accès anonyme)
    path("login/", HospitalLoginView.as_view(), name="login"),
    path("logout/", hospital_logout_view, name="logout"),
    path("admin/login/", HospitalLoginView.as_view(), name="admin_login"),
    path("admin/logout/", hospital_logout_view, name="admin_logout"),

    # Tableau de bord hebdomadaire (Accueil protégé)
    path("", WeeklyDashboardView.as_view(), name="home_dashboard"),
    
    # Interface d'Administration Sécurisée
    path("admin/", admin.site.urls),
    
    # Modules Hospitaliers
    path("core/", include("apps.core.urls", namespace="core")),
    path("chirurgie/", include("apps.chirurgie.urls", namespace="chirurgie")),
    path("maternite/", include("apps.gynecologie_maternite.urls", namespace="gynecologie_maternite")),
    path("pediatrie/", include("apps.pediatrie.urls", namespace="pediatrie")),
    path("urologie/", include("apps.urologie.urls", namespace="urologie")),

    # Service direct des fichiers statiques (Logo, CSS/JS Admin) même via Gunicorn (:8000)
    re_path(r"^static/(?P<path>.*)$", serve_static_with_fallback),
]

