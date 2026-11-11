"""
Administration Django du module de Facturation Hospitalière Algérienne.
"""

from django.contrib import admin

from apps.facturation.models import (
    ActeMedicalNGAP,
    BordereauTiersPayant,
    ConventionPriseEnCharge,
    EtablissementFiscal,
    FacturePatient,
    LigneFactureActe,
    LigneFacturePharmacie,
    OrganismeTiersPayant,
    PaiementFacture,
)


class LigneFactureActeInline(admin.TabularInline):
    model = LigneFactureActe
    extra = 0


class LigneFacturePharmacieInline(admin.TabularInline):
    model = LigneFacturePharmacie
    extra = 0


class PaiementFactureInline(admin.TabularInline):
    model = PaiementFacture
    extra = 0


@admin.register(EtablissementFiscal)
class EtablissementFiscalAdmin(admin.ModelAdmin):
    list_display = (
        "raison_sociale",
        "type_etablissement",
        "nif",
        "nis",
        "rc",
        "article_imposition",
        "exercice_fiscal_courant",
        "dernier_numero_sequentiel",
    )


@admin.register(ActeMedicalNGAP)
class ActeMedicalNGAPAdmin(admin.ModelAdmin):
    list_display = (
        "code_ngap",
        "libelle",
        "lettre_cle",
        "coefficient",
        "tarif_reference_cnas_da",
        "tarif_clinique_ht_da",
        "taux_tva",
        "taux_retrocession_praticien_defaut",
        "est_remboursable_cnas",
    )
    list_filter = ("lettre_cle", "type_acte", "taux_tva", "est_remboursable_cnas")
    search_fields = ("code_ngap", "libelle")


@admin.register(OrganismeTiersPayant)
class OrganismeTiersPayantAdmin(admin.ModelAdmin):
    list_display = (
        "code_organisme",
        "nom",
        "type_organisme",
        "taux_couverture_defaut_pct",
        "base_calcul",
        "est_actif",
    )
    list_filter = ("type_organisme", "base_calcul", "est_actif")


@admin.register(ConventionPriseEnCharge)
class ConventionPriseEnChargeAdmin(admin.ModelAdmin):
    list_display = (
        "patient",
        "organisme",
        "numero_immatriculation_assure",
        "numero_accord_pec",
        "taux_prise_en_charge_pct",
        "est_active",
    )
    list_filter = ("organisme", "est_active")
    search_fields = ("patient__last_name", "numero_immatriculation_assure", "numero_accord_pec")


@admin.register(BordereauTiersPayant)
class BordereauTiersPayantAdmin(admin.ModelAdmin):
    list_display = (
        "numero_bordereau",
        "organisme",
        "periode_debut",
        "periode_fin",
        "nombre_factures",
        "montant_total_tiers_payant_da",
        "statut",
    )
    list_filter = ("statut", "organisme")


@admin.register(FacturePatient)
class FacturePatientAdmin(admin.ModelAdmin):
    list_display = (
        "numero_facture",
        "patient",
        "statut",
        "montant_total_ttc_da",
        "part_organisme_tiers_payant_da",
        "part_patient_ticket_moderateur_da",
        "droit_timbre_da",
        "net_a_payer_patient_da",
        "date_emission",
    )
    list_filter = ("statut", "type_prise_en_charge", "exercice_fiscal")
    search_fields = ("numero_facture", "patient__last_name", "patient__ipp")
    inlines = [LigneFactureActeInline, LigneFacturePharmacieInline, PaiementFactureInline]

