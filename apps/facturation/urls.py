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
    ImputerConsommationMaladeView,
    ParametrageActeNGAPSaveView,
    ParametrageFiscalUpdateView,
    ParametrageOrganismeSaveView,
    ValiderFactureSequentielleView,
    api_simuler_droit_timbre,
)

app_name = "facturation"

urlpatterns = [
    path("", FacturationAlgerieDashboardView.as_view(), name="dashboard"),
    path("factures/create/", CreerFacturePatientView.as_view(), name="facture_create"),
    path("consommation-malade/", ImputerConsommationMaladeView.as_view(), name="consommation_malade"),
    path(
        "factures/<int:facture_id>/add-acte/",
        AjouterActeNGAPFactureView.as_view(),
        name="facture_add_acte",
    ),
    path(
        "factures/<int:facture_id>/ajouter-acte/",
        AjouterActeNGAPFactureView.as_view(),
        name="facture_ajouter_acte",
    ),
    path(
        "factures/<int:facture_id>/add-pharma/",
        AjouterMedicamentPPAFactureView.as_view(),
        name="facture_add_pharma",
    ),
    path(
        "factures/<int:facture_id>/ajouter-medicament/",
        AjouterMedicamentPPAFactureView.as_view(),
        name="facture_ajouter_medicament",
    ),
    path(
        "factures/<int:facture_id>/validate/",
        ValiderFactureSequentielleView.as_view(),
        name="facture_validate",
    ),
    path(
        "factures/<int:facture_id>/valider/",
        ValiderFactureSequentielleView.as_view(),
        name="facture_valider",
    ),
    path(
        "factures/<int:facture_id>/pay/",
        EnregistrerPaiementFactureView.as_view(),
        name="facture_pay",
    ),
    path(
        "factures/<int:facture_id>/encaisser/",
        EnregistrerPaiementFactureView.as_view(),
        name="facture_encaisser",
    ),
    path(
        "factures/<int:pk>/imprimer/",
        FactureOfficielleAlgeriePrintView.as_view(),
        name="facture_print",
    ),
    path("conventions/create/", CreerConventionPatientView.as_view(), name="convention_create"),
    path("bordereaux/generate/", GenererBordereauTiersPayantView.as_view(), name="bordereau_generate"),
    path("settings/fiscal/", ParametrageFiscalUpdateView.as_view(), name="settings_fiscal"),
    path("settings/ngap-save/", ParametrageActeNGAPSaveView.as_view(), name="settings_ngap_save"),
    path("settings/organisme-save/", ParametrageOrganismeSaveView.as_view(), name="settings_organisme_save"),
    path("api/simuler-timbre/", api_simuler_droit_timbre, name="api_simuler_timbre"),
]

