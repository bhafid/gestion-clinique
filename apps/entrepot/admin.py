"""
Configuration Django Admin pour le module Gestion d'Entrepôt et Bacs (WMS).
"""

from django.contrib import admin
from django.utils.html import format_html

from apps.entrepot.models import (
    BinBillingLog,
    BinInventory,
    BinTransfer,
    ClientEntrepot,
    FactureEntrepot,
    LigneFactureEntrepot,
    StorageBin,
    Warehouse,
)


class BinInventoryInline(admin.TabularInline):
    model = BinInventory
    extra = 1
    autocomplete_fields = ["product"]


@admin.register(Warehouse)
class WarehouseAdmin(admin.ModelAdmin):
    list_display = ["code", "name", "address", "total_bins_display", "is_active", "created_at"]
    list_filter = ["is_active"]
    search_fields = ["code", "name", "address"]

    def total_bins_display(self, obj: Warehouse) -> int:
        return obj.bins.count()
    total_bins_display.short_description = "Nombre de Bacs"


@admin.register(ClientEntrepot)
class ClientEntrepotAdmin(admin.ModelAdmin):
    list_display = ["code", "name", "client_type", "contact_name", "phone", "email", "is_active"]
    list_filter = ["client_type", "is_active"]
    search_fields = ["code", "name", "contact_name", "nif", "email"]


@admin.register(StorageBin)
class StorageBinAdmin(admin.ModelAdmin):
    list_display = [
        "code",
        "warehouse",
        "status_badge",
        "capacity",
        "current_load",
        "fill_progress_bar",
        "client",
        "daily_rate",
        "monthly_rate",
        "barcode_link",
    ]
    list_filter = ["warehouse", "status", "client"]
    search_fields = ["code", "warehouse__name", "zone_allee", "rack_niveau"]
    inlines = [BinInventoryInline]

    def status_badge(self, obj: StorageBin) -> str:
        colors = {
            "AVAILABLE": "#059669",
            "OCCUPIED": "#0284c7",
            "FULL": "#dc2626",
            "MAINTENANCE": "#64748b",
        }
        color = colors.get(obj.status, "#64748b")
        return format_html(
            '<span style="padding: 3px 8px; border-radius: 9999px; font-weight: bold; font-size: 11px; background: {}; color: white;">{}</span>',
            color,
            obj.get_status_display(),
        )
    status_badge.short_description = "Statut"

    def fill_progress_bar(self, obj: StorageBin) -> str:
        pct = obj.fill_rate_percent
        bar_color = "#059669" if pct < 70 else ("#f59e0b" if pct < 100 else "#dc2626")
        return format_html(
            '<div style="width: 80px; background: #e2e8f0; border-radius: 4px; overflow: hidden; height: 12px; display: inline-block; vertical-align: middle;">'
            '<div style="width: {}%; background: {}; height: 100%;"></div>'
            '</div> <span style="font-size: 11px; font-weight: bold; margin-left: 4px;">{}%</span>',
            pct,
            bar_color,
            pct,
        )
    fill_progress_bar.short_description = "Remplissage"

    def barcode_link(self, obj: StorageBin) -> str:
        if not obj.pk:
            return "-"
        return format_html(
            '<a href="/entrepot/bins/{}/barcode/" target="_blank" style="padding: 2px 6px; border-radius: 4px; background: #0f172a; color: white; text-decoration: none; font-size: 11px; font-weight: bold;">'
            '🏷️ Code-barres</a>',
            obj.pk,
        )
    barcode_link.short_description = "Étiquette"


@admin.register(BinTransfer)
class BinTransferAdmin(admin.ModelAdmin):
    list_display = [
        "reference",
        "product",
        "quantity",
        "source_bin",
        "destination_bin",
        "transferred_by",
        "created_at",
    ]
    list_filter = ["created_at", "source_bin__warehouse", "destination_bin__warehouse"]
    search_fields = ["reference", "product__nom_commercial", "source_bin__code", "destination_bin__code", "reason"]
    readonly_fields = ["reference", "created_at", "updated_at"]


class LigneFactureEntrepotInline(admin.TabularInline):
    model = LigneFactureEntrepot
    extra = 0
    readonly_fields = ["montant_ht"]


@admin.register(FactureEntrepot)
class FactureEntrepotAdmin(admin.ModelAdmin):
    list_display = [
        "numero_facture",
        "client",
        "date_emission",
        "montant_ht",
        "montant_ttc",
        "status",
        "view_invoice_link",
    ]
    list_filter = ["status", "date_emission"]
    search_fields = ["numero_facture", "client__name"]
    inlines = [LigneFactureEntrepotInline]

    def view_invoice_link(self, obj: FactureEntrepot) -> str:
        if not obj.pk:
            return "-"
        return format_html(
            '<a href="/entrepot/invoices/{}/" target="_blank" style="padding: 2px 6px; border-radius: 4px; background: #0284c7; color: white; text-decoration: none; font-size: 11px; font-weight: bold;">'
            '📄 Voir Facture</a>',
            obj.pk,
        )
    view_invoice_link.short_description = "Document"


@admin.register(BinBillingLog)
class BinBillingLogAdmin(admin.ModelAdmin):
    list_display = ["bin", "client", "start_date", "end_date", "billed_amount", "status", "invoice"]
    list_filter = ["status", "client"]
    search_fields = ["bin__code", "client__name", "details"]

