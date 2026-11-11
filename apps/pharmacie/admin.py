"""
Interface d'Administration Django pour le module Pharmacie & Achats.
"""

from django.contrib import admin

from apps.pharmacie.models import (
    CommandeAchat,
    Fournisseur,
    LigneCommandeAchat,
    LotStock,
    MouvementStock,
    ProduitPharmaceutique,
)


class LotStockInline(admin.TabularInline):
    model = LotStock
    extra = 0
    fields = (
        "numero_lot",
        "date_peremption",
        "quantite_disponible",
        "emplacement_physique",
        "statut",
        "motif_quarantaine_rappel",
    )


class LigneCommandeAchatInline(admin.TabularInline):
    model = LigneCommandeAchat
    extra = 1
    fields = (
        "produit",
        "quantite_commandee",
        "quantite_recue",
        "prix_unitaire_achat_negocie",
    )


@admin.register(Fournisseur)
class FournisseurAdmin(admin.ModelAdmin):
    list_display = (
        "nom",
        "contact",
        "email",
        "telephone",
        "delai_livraison_moyen",
        "conditions_paiement",
        "est_actif",
    )
    list_filter = ("est_actif",)
    search_fields = ("nom", "contact", "email")


@admin.register(ProduitPharmaceutique)
class ProduitPharmaceutiqueAdmin(admin.ModelAdmin):
    list_display = (
        "code_cip_ean13",
        "nom_commercial",
        "dosage",
        "dci",
        "categorie",
        "stock_actuel_display",
        "stock_minimum",
        "stock_maximum",
        "prix_moyen_pondere_ht",
        "prix_vente_ttc",
        "methode_rotation",
    )
    list_filter = ("categorie", "methode_rotation", "fournisseur_prefere")
    search_fields = ("code_cip_ean13", "nom_commercial", "dci", "classe_therapeutique")
    inlines = [LotStockInline]

    @admin.display(description="Stock Actuel (FEFO)")
    def stock_actuel_display(self, obj: ProduitPharmaceutique) -> int:
        return obj.stock_actuel


@admin.register(LotStock)
class LotStockAdmin(admin.ModelAdmin):
    list_display = (
        "numero_lot",
        "produit",
        "date_peremption",
        "quantite_disponible",
        "emplacement_physique",
        "statut",
    )
    list_filter = ("statut", "date_peremption")
    search_fields = ("numero_lot", "produit__nom_commercial", "produit__code_cip_ean13")


@admin.register(CommandeAchat)
class CommandeAchatAdmin(admin.ModelAdmin):
    list_display = (
        "numero_commande",
        "fournisseur",
        "date_creation",
        "date_livraison_prevue",
        "statut",
        "montant_total_ht",
        "montant_total_ttc",
    )
    list_filter = ("statut", "fournisseur")
    search_fields = ("numero_commande", "fournisseur__nom")
    inlines = [LigneCommandeAchatInline]


@admin.register(MouvementStock)
class MouvementStockAdmin(admin.ModelAdmin):
    list_display = (
        "date_mouvement",
        "type_mouvement",
        "produit",
        "lot",
        "quantite",
        "stock_lot_avant",
        "stock_lot_apres",
        "utilisateur",
        "motif_reference",
    )
    list_filter = ("type_mouvement", "date_mouvement")
    search_fields = ("produit__nom_commercial", "lot__numero_lot", "motif_reference")
    readonly_fields = (
        "lot",
        "produit",
        "type_mouvement",
        "quantite",
        "stock_lot_avant",
        "stock_lot_apres",
        "date_mouvement",
        "utilisateur",
        "motif_reference",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

