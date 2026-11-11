"""
Modèles de données du module Gestion de Stock Pharmaceutique et d'Achats.
Conforme aux normes HDS / RGPD et à la réglementation pharmaceutique
(traçabilité des lots, règle FEFO, stupéfiants/contrôlés, PMP et audit immuable).
"""

from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Sum
from django.utils import timezone

from apps.core.models import AuditableModel


# -----------------------------------------------------------------------------
# Énumérations Métiers Pharmaceutiques
# -----------------------------------------------------------------------------
class CategorieProduitChoices(models.TextChoices):
    MEDICAMENT_REMBOURSABLE = "MEDICAMENT_REMBOURSABLE", "Médicament remboursable"
    OTC = "OTC", "Médicament OTC (Sans ordonnance)"
    PARAPHARMACIE = "PARAPHARMACIE", "Parapharmacie & Dispositif Médical"
    STUPEFIANT_CONTROLE = "STUPEFIANT_CONTROLE", "Stupéfiant / Médicament contrôlé"


class MethodeRotationChoices(models.TextChoices):
    FEFO = "FEFO", "FEFO (First Expired, First Out - Premier périmé, premier sorti)"
    FIFO = "FIFO", "FIFO (First In, First Out - Premier entré, premier sorti)"


class StatutLotChoices(models.TextChoices):
    ACTIF = "ACTIF", "Actif (Disponible)"
    PROCHE_PEREMPTION = "PROCHE_PEREMPTION", "Proche péremption (< 3 mois)"
    PERIME = "PERIME", "Périmé (Bloqué)"
    QUARANTAINE = "QUARANTAINE", "En quarantaine (Isolé)"
    RAPPELE = "RAPPELE", "Rappel de lot (Retiré ANSM/Autorité)"


class StatutCommandeChoices(models.TextChoices):
    BROUILLON = "BROUILLON", "Brouillon"
    ENVOYEE = "ENVOYEE", "Envoyée au fournisseur"
    PARTIELLEMENT_RECUE = "PARTIELLEMENT_RECUE", "Partiellement reçue"
    RECUE = "RECUE", "Totalement reçue"
    ANNULEE = "ANNULEE", "Annulée"


class TypeMouvementStockChoices(models.TextChoices):
    ENTREE_ACHAT = "ENTREE_ACHAT", "Entrée sur achat / Réception livraison"
    SORTIE_VENTE = "SORTIE_VENTE", "Sortie dispensation / Soins (FEFO)"
    AJUSTEMENT_INVENTAIRE = "AJUSTEMENT_INVENTAIRE", "Ajustement d'inventaire tournant"
    PERTE_PEREMPTION = "PERTE_PEREMPTION", "Perte / Destruction pour péremption"
    RETOUR_FOURNISSEUR = "RETOUR_FOURNISSEUR", "Retour fournisseur / Rappel de lot"
    MISE_QUARANTAINE = "MISE_QUARANTAINE", "Mise en quarantaine sanitaire"


# -----------------------------------------------------------------------------
# 1. Fournisseur (Grossiste-Répartiteur ou Laboratoire)
# -----------------------------------------------------------------------------
class Fournisseur(AuditableModel):
    """Grossiste-répartiteur ou laboratoire pharmaceutique."""

    nom = models.CharField(
        max_length=150,
        unique=True,
        verbose_name="Nom du fournisseur (Grossiste / Laboratoire)",
    )
    contact = models.CharField(
        max_length=120,
        blank=True,
        verbose_name="Interlocuteur / Responsable Grands Comptes",
    )
    email = models.EmailField(
        blank=True,
        verbose_name="Email de commande EDI / Contact",
    )
    telephone = models.CharField(
        max_length=30,
        blank=True,
        verbose_name="Téléphone d'astreinte / Standard",
    )
    delai_livraison_moyen = models.PositiveIntegerField(
        default=1,
        verbose_name="Délai de livraison moyen (en jours)",
    )
    conditions_paiement = models.CharField(
        max_length=120,
        default="30 jours fin de mois",
        verbose_name="Conditions de paiement",
    )
    est_actif = models.BooleanField(
        default=True,
        verbose_name="Fournisseur actif",
    )

    class Meta:
        verbose_name = "Fournisseur Pharmaceutique"
        verbose_name_plural = "Fournisseurs Pharmaceutiques"
        ordering = ["nom"]

    def __str__(self) -> str:
        return f"{self.nom} (Livraison ~{self.delai_livraison_moyen}j)"


# -----------------------------------------------------------------------------
# 2. Produit Pharmaceutique (Catalogue & Paramètres de Stock)
# -----------------------------------------------------------------------------
class ProduitPharmaceutique(AuditableModel):
    """
    Référentiel médicament ou dispositif médical avec seuils de réapprovisionnement
    et valorisation au Prix Moyen Pondéré (PMP).
    """

    code_cip_ean13 = models.CharField(
        max_length=20,
        unique=True,
        db_index=True,
        verbose_name="Code CIP / EAN13 (Code-barres)",
    )
    dci = models.CharField(
        max_length=200,
        db_index=True,
        verbose_name="DCI (Dénomination Commune Internationale)",
    )
    nom_commercial = models.CharField(
        max_length=200,
        db_index=True,
        verbose_name="Nom commercial",
    )
    dosage = models.CharField(
        max_length=100,
        verbose_name="Dosage (ex: 1000 mg, 10 mg/ml)",
    )
    forme_galenique = models.CharField(
        max_length=100,
        verbose_name="Forme galénique (Comprimé, Injectable, Flacon...)",
    )
    classe_therapeutique = models.CharField(
        max_length=150,
        blank=True,
        verbose_name="Classe thérapeutique (ATC)",
    )
    categorie = models.CharField(
        max_length=40,
        choices=CategorieProduitChoices.choices,
        default=CategorieProduitChoices.MEDICAMENT_REMBOURSABLE,
        verbose_name="Catégorie réglementaire",
    )
    fournisseur_prefere = models.ForeignKey(
        Fournisseur,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="produits_catalogue",
        verbose_name="Fournisseur principal",
    )

    # Tarification & PMP
    prix_achat_ht = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
        verbose_name="Prix d'achat catalogue HT (€ / DA)",
    )
    prix_moyen_pondere_ht = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
        verbose_name="Prix Moyen Pondéré (PMP) HT",
    )
    taux_tva = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("2.10"),
        validators=[MinValueValidator(Decimal("0.00"))],
        verbose_name="Taux de TVA (%)",
    )
    prix_vente_ttc = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
        verbose_name="Prix de cession / vente TTC",
    )

    # Seuils de pilotage des stocks
    stock_minimum = models.PositiveIntegerField(
        default=20,
        verbose_name="Stock minimum (Seuil d'alerte)",
    )
    stock_securite = models.PositiveIntegerField(
        default=10,
        verbose_name="Stock de sécurité critique",
    )
    stock_maximum = models.PositiveIntegerField(
        default=100,
        verbose_name="Stock maximum cible",
    )
    methode_rotation = models.CharField(
        max_length=10,
        choices=MethodeRotationChoices.choices,
        default=MethodeRotationChoices.FEFO,
        verbose_name="Méthode de rotation des lots",
    )
    rayon_par_defaut = models.CharField(
        max_length=100,
        default="Armoire Pharmacie Centrale - A1",
        verbose_name="Emplacement / Rayon par défaut",
    )

    class Meta:
        verbose_name = "Produit Pharmaceutique"
        verbose_name_plural = "Produits Pharmaceutiques"
        ordering = ["nom_commercial", "dosage"]

    def __str__(self) -> str:
        return f"{self.nom_commercial} {self.dosage} ({self.dci}) [{self.code_cip_ean13}]"

    def save(self, *args, **kwargs):
        if self.prix_moyen_pondere_ht <= Decimal("0.00") and self.prix_achat_ht > Decimal("0.00"):
            self.prix_moyen_pondere_ht = self.prix_achat_ht
        if self.prix_vente_ttc <= Decimal("0.00") and self.prix_achat_ht > Decimal("0.00"):
            coeff_tva = Decimal("1.00") + (self.taux_tva / Decimal("100.00"))
            self.prix_vente_ttc = (self.prix_achat_ht * coeff_tva * Decimal("1.25")).quantize(Decimal("0.01"))
        super().save(*args, **kwargs)

    @property
    def stock_actuel(self) -> int:
        """
        Quantité totale disponible sur les lots utilisables (ACTIF ou PROCHE_PEREMPTION)
        et dont la date de péremption n'est pas dépassée.
        """
        today = timezone.localdate()
        agg = self.lots.filter(
            statut__in=[StatutLotChoices.ACTIF, StatutLotChoices.PROCHE_PEREMPTION],
            date_peremption__gte=today,
            quantite_disponible__gt=0,
        ).aggregate(total=Sum("quantite_disponible"))
        return int(agg["total"] or 0)

    @property
    def valeur_stock_ht(self) -> Decimal:
        """Valorisation comptable du stock disponible au PMP HT (ou prix d'achat HT)."""
        pmp = self.prix_moyen_pondere_ht if self.prix_moyen_pondere_ht > 0 else self.prix_achat_ht
        return (Decimal(self.stock_actuel) * pmp).quantize(Decimal("0.01"))

    @property
    def est_en_alerte_rupture(self) -> bool:
        """Retourne True si Stock Actuel <= Seuil d'alerte (stock_minimum)."""
        return self.stock_actuel <= self.stock_minimum

    @property
    def est_en_rupture_totale(self) -> bool:
        """Retourne True si Stock Actuel == 0 ou sous le stock de sécurité."""
        return self.stock_actuel <= self.stock_securite

    @property
    def quantite_suggeree_commande(self) -> int:
        """
        Formule métier officielle de réapprovisionnement :
        (Stock Max - Stock Actuel) pour tout produit dont Stock Actuel <= Seuil d'alerte.
        """
        actuel = self.stock_actuel
        if actuel <= self.stock_minimum:
            return max(0, self.stock_maximum - actuel)
        return 0

    @property
    def statut_urgence_ui(self) -> str:
        """
        Retourne ROUGE (rupture / <= sécurité), ORANGE (<= seuil minimum), ou VERT (OK).
        """
        actuel = self.stock_actuel
        if actuel == 0 or actuel <= self.stock_securite:
            return "ROUGE"
        if actuel <= self.stock_minimum:
            return "ORANGE"
        return "VERT"


# -----------------------------------------------------------------------------
# 3. Lot de Stock (Traçabilité Sanitaire & FEFO)
# -----------------------------------------------------------------------------
class LotStock(AuditableModel):
    """
    Lot physique identifié par son numéro de lot industriel et sa date de péremption.
    Ordonné par défaut selon la règle FEFO (date_peremption croissante).
    """

    produit = models.ForeignKey(
        ProduitPharmaceutique,
        on_delete=models.CASCADE,
        related_name="lots",
        verbose_name="Produit pharmaceutique",
    )
    numero_lot = models.CharField(
        max_length=80,
        db_index=True,
        verbose_name="Numéro de lot fabricant",
    )
    date_peremption = models.DateField(
        db_index=True,
        verbose_name="Date de péremption",
    )
    quantite_disponible = models.PositiveIntegerField(
        default=0,
        verbose_name="Quantité disponible en stock",
    )
    emplacement_physique = models.CharField(
        max_length=120,
        default="Rayon A1 - Pharmacie Centrale",
        verbose_name="Emplacement physique (Rayon / Armoire / Frigo)",
    )
    statut = models.CharField(
        max_length=25,
        choices=StatutLotChoices.choices,
        default=StatutLotChoices.ACTIF,
        db_index=True,
        verbose_name="Statut sanitaire du lot",
    )
    motif_quarantaine_rappel = models.CharField(
        max_length=255,
        blank=True,
        verbose_name="Motif de quarantaine ou de rappel ANSM",
    )

    class Meta:
        verbose_name = "Lot de Stock"
        verbose_name_plural = "Lots de Stock (FEFO)"
        # Tri FEFO strict : les lots qui périment le plus tôt sortent en premier
        ordering = ["date_peremption", "id"]
        unique_together = [("produit", "numero_lot")]

    def __str__(self) -> str:
        return (
            f"Lot {self.numero_lot} - {self.produit.nom_commercial} "
            f"(Exp: {self.date_peremption.strftime('%d/%m/%Y')}, Qté: {self.quantite_disponible})"
        )

    @property
    def jours_avant_peremption(self) -> int:
        return (self.date_peremption - timezone.localdate()).days

    def actualiser_statut_peremption(self, delai_alerte_jours: int = 90, save: bool = True) -> str:
        """
        Met à jour automatiquement le statut du lot selon sa date de péremption
        (sauf s'il est déjà isolé en QUARANTAINE ou RAPPELE).
        """
        if self.statut in (StatutLotChoices.QUARANTAINE, StatutLotChoices.RAPPELE):
            return self.statut

        jours = self.jours_avant_peremption
        nouveau_statut = StatutLotChoices.ACTIF
        if jours < 0:
            nouveau_statut = StatutLotChoices.PERIME
        elif jours <= delai_alerte_jours:
            nouveau_statut = StatutLotChoices.PROCHE_PEREMPTION

        if nouveau_statut != self.statut:
            self.statut = nouveau_statut
            if save and self.pk:
                self.save(update_fields=["statut", "updated_at"])
        return self.statut


# -----------------------------------------------------------------------------
# 4. Commande d'Achat (Bon de Commande Fournisseur)
# -----------------------------------------------------------------------------
class CommandeAchat(AuditableModel):
    """Bon de commande adressé à un grossiste-répartiteur ou laboratoire."""

    numero_commande = models.CharField(
        max_length=50,
        unique=True,
        db_index=True,
        verbose_name="N° de Bon de Commande",
    )
    fournisseur = models.ForeignKey(
        Fournisseur,
        on_delete=models.PROTECT,
        related_name="commandes",
        verbose_name="Fournisseur",
    )
    date_creation = models.DateTimeField(
        default=timezone.now,
        verbose_name="Date de création",
    )
    date_livraison_prevue = models.DateField(
        null=True,
        blank=True,
        verbose_name="Date de livraison prévue",
    )
    statut = models.CharField(
        max_length=25,
        choices=StatutCommandeChoices.choices,
        default=StatutCommandeChoices.BROUILLON,
        db_index=True,
        verbose_name="Statut de la commande",
    )
    montant_total_ht = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        verbose_name="Montant total HT",
    )
    montant_total_ttc = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        verbose_name="Montant total TTC",
    )
    cree_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="commandes_pharmacie_creees",
        verbose_name="Créée par",
    )
    notes = models.TextField(
        blank=True,
        verbose_name="Observations / Référence EDI",
    )

    class Meta:
        verbose_name = "Commande d'Achat (Bon de Commande)"
        verbose_name_plural = "Commandes d'Achat (Bons de Commande)"
        ordering = ["-date_creation", "-id"]

    def __str__(self) -> str:
        return f"{self.numero_commande} - {self.fournisseur.nom} ({self.get_statut_display()})"

    def recalculer_totaux(self, save: bool = True) -> None:
        total_ht = Decimal("0.00")
        total_ttc = Decimal("0.00")
        for ligne in self.lignes.select_related("produit").all():
            total_ht += ligne.montant_ligne_ht
            total_ttc += ligne.montant_ligne_ttc
        self.montant_total_ht = total_ht.quantize(Decimal("0.01"))
        self.montant_total_ttc = total_ttc.quantize(Decimal("0.01"))
        if save and self.pk:
            self.save(update_fields=["montant_total_ht", "montant_total_ttc", "updated_at"])


# -----------------------------------------------------------------------------
# 5. Ligne de Commande d'Achat
# -----------------------------------------------------------------------------
class LigneCommandeAchat(AuditableModel):
    """Ligne détaillée d'un bon de commande avec suivi des reliquats de livraison."""

    commande = models.ForeignKey(
        CommandeAchat,
        on_delete=models.CASCADE,
        related_name="lignes",
        verbose_name="Bon de commande",
    )
    produit = models.ForeignKey(
        ProduitPharmaceutique,
        on_delete=models.PROTECT,
        related_name="lignes_commandes",
        verbose_name="Produit commandé",
    )
    quantite_commandee = models.PositiveIntegerField(
        validators=[MinValueValidator(1)],
        verbose_name="Quantité commandée",
    )
    quantite_recue = models.PositiveIntegerField(
        default=0,
        verbose_name="Quantité déjà reçue",
    )
    prix_unitaire_achat_negocie = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
        verbose_name="Prix unitaire d'achat négocié HT",
    )

    class Meta:
        verbose_name = "Ligne de Commande d'Achat"
        verbose_name_plural = "Lignes de Commande d'Achat"
        ordering = ["id"]

    def __str__(self) -> str:
        return (
            f"{self.produit.nom_commercial} : {self.quantite_recue}/{self.quantite_commandee} "
            f"({self.commande.numero_commande})"
        )

    @property
    def reliquat_a_recevoir(self) -> int:
        return max(0, self.quantite_commandee - self.quantite_recue)

    @property
    def montant_ligne_ht(self) -> Decimal:
        return (Decimal(self.quantite_commandee) * self.prix_unitaire_achat_negocie).quantize(
            Decimal("0.01")
        )

    @property
    def montant_ligne_ttc(self) -> Decimal:
        coeff_tva = Decimal("1.00") + (self.produit.taux_tva / Decimal("100.00"))
        return (self.montant_ligne_ht * coeff_tva).quantize(Decimal("0.01"))


# -----------------------------------------------------------------------------
# 6. Mouvement de Stock (Journal d'Audit Immuable HDS / Stupéfiants)
# -----------------------------------------------------------------------------
class MouvementStock(models.Model):
    """
    Journal d'audit inaltérable retraçant chaque entrée, sortie FEFO, ajustement
    d'inventaire, mise en quarantaine ou perte par péremption.
    Aucune suppression n'est autorisée (conformité HDS & registre des stupéfiants).
    """

    lot = models.ForeignKey(
        LotStock,
        on_delete=models.PROTECT,
        related_name="mouvements",
        verbose_name="Lot concerné",
    )
    produit = models.ForeignKey(
        ProduitPharmaceutique,
        on_delete=models.PROTECT,
        related_name="mouvements",
        verbose_name="Produit pharmaceutique",
    )
    type_mouvement = models.CharField(
        max_length=30,
        choices=TypeMouvementStockChoices.choices,
        db_index=True,
        verbose_name="Type de mouvement",
    )
    quantite = models.IntegerField(
        verbose_name="Quantité mouvementée (+ entrée / - sortie)",
    )
    stock_lot_avant = models.PositiveIntegerField(
        default=0,
        verbose_name="Stock du lot avant opération",
    )
    stock_lot_apres = models.PositiveIntegerField(
        default=0,
        verbose_name="Stock du lot après opération",
    )
    date_mouvement = models.DateTimeField(
        default=timezone.now,
        db_index=True,
        verbose_name="Horodatage du mouvement",
    )
    utilisateur = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="mouvements_stock_pharmacie",
        verbose_name="Opérateur / Pharmacien",
    )
    motif_reference = models.CharField(
        max_length=255,
        verbose_name="Motif justificatif / Référence (BL, Ordonnance, Inventaire)",
    )

    class Meta:
        verbose_name = "Mouvement de Stock (Audit)"
        verbose_name_plural = "Mouvements de Stock (Journal d'Audit Immuable)"
        ordering = ["-date_mouvement", "-id"]

    def __str__(self) -> str:
        signe = "+" if self.quantite > 0 else ""
        return (
            f"[{self.date_mouvement.strftime('%d/%m/%Y %H:%M')}] "
            f"{self.get_type_mouvement_display()} | {self.produit.nom_commercial} "
            f"(Lot {self.lot.numero_lot}) : {signe}{self.quantite}"
        )

    def clean(self) -> None:
        if not self.motif_reference or not self.motif_reference.strip():
            raise ValidationError(
                "Le motif ou la référence justificative est strictement obligatoire pour tout mouvement de stock."
            )

    def delete(self, *args, **kwargs):
        raise PermissionDenied(
            "SÉCURITÉ HDS / PHARMACOVIGILANCE : Les mouvements de stock constituent un journal d'audit "
            "inaltérable et ne peuvent jamais être supprimés."
        )

