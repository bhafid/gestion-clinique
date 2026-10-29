"""
Configuration du routage centralisé pour hospital_system.
Intègre le Dashboard hebdomadaire, l'interface d'administration personnalisée HDS,
et l'accès modulaire aux différentes spécialités hospitalières.
"""

from django.contrib import admin
from django.urls import include, path

from apps.core.views import WeeklyDashboardView

# -----------------------------------------------------------------------------
# Personnalisation de l'Administration Hospitalière (Branding & HDS)
# -----------------------------------------------------------------------------
# admin.site.site_header = "Centre Hospitalier Universitaire (CHU) - Portail Médical HDS"
admin.site.site_header = "CLinique Sidi Yahia 2"
admin.site.site_title = "SIH - Dossiers Patients & Soins"
admin.site.index_title = "Supervision Hospitalière & Gestion des Pôles Cliniques"

urlpatterns = [
    # Tableau de bord hebdomadaire (Accueil)
    path("", WeeklyDashboardView.as_view(), name="home_dashboard"),
    
    # Interface d'Administration Sécurisée
    path("admin/", admin.site.urls),
    
    # Modules Hospitaliers
    path("core/", include("apps.core.urls", namespace="core")),
    path("chirurgie/", include("apps.chirurgie.urls", namespace="chirurgie")),
    path("maternite/", include("apps.gynecologie_maternite.urls", namespace="gynecologie_maternite")),
    path("pediatrie/", include("apps.pediatrie.urls", namespace="pediatrie")),
    path("urologie/", include("apps.urologie.urls", namespace="urologie")),
]

