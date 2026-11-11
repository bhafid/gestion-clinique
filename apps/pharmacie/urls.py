"""
Configuration des routes URL et endpoints API du module Pharmacie & Achats.
"""

from django.urls import path

from apps.pharmacie.views import (
    AjustementInventaireTournantView,
    CreerCommandeDepuisSuggestionsView,
    DispensationFEFOView,
    PharmacieDashboardView,
    QuarantaineRappelLotView,
    ReceptionLivraisonCommandeView,
    api_scan_code_barres,
)

app_name = "pharmacie"

urlpatterns = [
    # Tableau de bord principal Stock & Achats
    path("", PharmacieDashboardView.as_view(), name="dashboard"),
    # 1. Sortie de stock FEFO transactionnelle
    path("fefo-dispense/", DispensationFEFOView.as_view(), name="fefo_dispense"),
    # 2. Mise en quarantaine / Retrait rappel de lot / Perte péremption
    path("lot/<int:lot_id>/quarantine/", QuarantaineRappelLotView.as_view(), name="lot_quarantine"),
    # 3. Création de Bon de Commande depuis les suggestions (Stock Max - Stock Actuel)
    path("orders/create/", CreerCommandeDepuisSuggestionsView.as_view(), name="order_create"),
    # 4. Réception de livraison (N° lot + Date péremption obligatoires + Calcul PMP)
    path(
        "orders/<int:commande_id>/receive/",
        ReceptionLivraisonCommandeView.as_view(),
        name="order_receive",
    ),
    # 5. Inventaire tournant avec justification obligatoire
    path("inventory/adjust/", AjustementInventaireTournantView.as_view(), name="inventory_adjust"),
    # 6. Endpoint JSON Douchette Code-Barres CIP13 / EAN13
    path("api/barcode/<str:code_barres>/", api_scan_code_barres, name="api_barcode"),
]

