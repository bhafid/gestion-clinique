"""
Routage d'URL pour le module Gestion d'Entrepôt et Bacs (WMS).
"""

from django.urls import path

from apps.entrepot.views import (
    AvailableDestinationBinsAPIView,
    BinBillingCalculateActionView,
    BinBillingDashboardView,
    BinBillingGenerateInvoiceActionView,
    BinInventoryAPIView,
    BinTransferActionView,
    BinTransferListView,
    FactureEntrepotDetailView,
    StorageBinBarcodeView,
    StorageBinCreateOrEditView,
    StorageBinQRCodeView,
    StorageBinToggleMaintenanceView,
    WarehouseDashboardView,
)

app_name = "entrepot"

urlpatterns = [
    # Tableau de bord principal WMS (Vue d'ensemble et grille des bacs)
    path("", WarehouseDashboardView.as_view(), name="dashboard"),

    # Transferts de stock inter-bacs
    path("transfer/", BinTransferActionView.as_view(), name="transfer_execute"),
    path("transfers/", BinTransferListView.as_view(), name="transfer_list"),

    # Endpoints AJAX / JSON pour les modals
    path("api/bins/<int:pk>/inventory/", BinInventoryAPIView.as_view(), name="api_bin_inventory"),
    path("api/bins/available/", AvailableDestinationBinsAPIView.as_view(), name="api_available_bins"),

    # Étiquetage physique Code-barres & QR Codes SVG
    path("bins/<int:pk>/barcode/", StorageBinBarcodeView.as_view(), name="bin_barcode"),
    path("bins/<int:pk>/qrcode/", StorageBinQRCodeView.as_view(), name="bin_qrcode"),

    # Gestion CRUD des bacs
    path("bins/save/", StorageBinCreateOrEditView.as_view(), name="bin_save"),
    path("bins/<int:pk>/toggle-maintenance/", StorageBinToggleMaintenanceView.as_view(), name="bin_toggle_maintenance"),

    # Facturation d'occupation & location des bacs
    path("billing/", BinBillingDashboardView.as_view(), name="billing_dashboard"),
    path("billing/calculate/", BinBillingCalculateActionView.as_view(), name="billing_calculate"),
    path("billing/generate-invoice/", BinBillingGenerateInvoiceActionView.as_view(), name="billing_generate_invoice"),
    path("invoices/<int:pk>/", FactureEntrepotDetailView.as_view(), name="invoice_detail"),
]

