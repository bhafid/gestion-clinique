"""
Routes URL du module de Facturation Hospitalière Algérienne (NGAP, PPA, CNAS/CASNOS, Fiscalité DGI).
"""

from django.urls import path

from apps.facturation.views import (
    AjouterActeNGAPFactureView,
    AjouterMedicamentPPAFactureView,
    CreerConventionPatientView,
    CreerFacturePatientView,
    EnregistrerPaiementFactureView,
    FacturationAlgerieDashboardView,
    FactureOfficielleAlgeriePrintView,
    GenererBordereauTiersPayantView,
    ValiderFactureSequentielleView,
    api_simuler_droit_timbre,
)

app_name = "facturation"

urlpatterns = [
    path("", FacturationAlgerieDashboardView.as_view(), name="dashboard"),
    path("factures/create/", CreerFacturePatientView.as_view(), name="facture_create"),
    path(
        "factures/<int:facture_id>/add-acte/",
        AjouterActeNGAPFactureView.as_view(),
        name="facture_add_acte",
    ),
    path(
        "factures/<int:facture_id>/add-pharma/",
        AjouterMedicamentPPAFactureView.as_view(),
        name="facture_add_pharma",
    ),
    path(
        "factures/<int:facture_id>/validate/",
        ValiderFactureSequentielleView.as_view(),
        name="facture_validate",
    ),
    path(
        "factures/<int:facture_id>/pay/",
        EnregistrerPaiementFactureView.as_view(),
        name="facture_pay",
    ),
    path(
        "factures/<int:pk>/imprimer/",
        FactureOfficielleAlgeriePrintView.as_view(),
        name="facture_print",
    ),
    path("conventions/create/", CreerConventionPatientView.as_view(), name="convention_create"),
    path("bordereaux/generate/", GenererBordereauTiersPayantView.as_view(), name="bordereau_generate"),
    path("api/simuler-timbre/", api_simuler_droit_timbre, name="api_simuler_timbre"),
]

