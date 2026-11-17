"""
Modèles de données du module de Gestion d'Entrepôt et Bacs (WMS Simplifié).
Gère les entrepôts, les bacs de rangement (StorageBin), l'inventaire par bac,
les transferts inter-bacs transactionnels et la facturation d'occupation/location des bacs.
"""

from decimal import Decimal
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Sum
from django.utils import timezone

from apps.core.models import AuditableModel
from apps.pharmacie.models import ProduitPharmaceutique


# -----------------------------------------------------------------------------
# Énumérations Métiers WMS
# -----------------------------------------------------------------------------
class StorageBinStatus(models.TextChoices):
    AVAILABLE = "AVAILABLE", "Disponible (Vide)"
    OCCUPIED = "OCCUPIED", "Occupé (Partiel)"
    FULL = "FULL", "Plein (Saturé)"
    MAINTENANCE = "MAINTENANCE", "En maintenance (Bloqué)"


class BillingLogStatus(models.TextChoices):
    PENDING = "PENDING", "En attente de facturation"
    INVOICED = "INVOICED", "Facturé"
    PAID = "PAID", "Réglé / Soldé"


class FactureEntrepotStatus(models.TextChoices):
    BROUILLON = "BROUILLON", "Brouillon"
    VALIDEE = "VALIDEE", "Validée & Émise"
    PAYEE = "PAYEE", "Payée"
    ANNULEE = "ANNULEE", "Annulée"


class ClientTypeChoices(models.TextChoices):
    ENTREPRISE = "ENTREPRISE", "Entreprise / Société"
    LABORATOIRE = "LABORATOIRE", "Laboratoire Partenaire"
    FOURNISSEUR = "FOURNISSEUR", "Fournisseur Dépositaire"
    SERVICE_INTERNE = "SERVICE_INTERNE", "Service / Pôle Clinique"
    PARTICULIER = "PARTICULIER", "Particulier / Professionnel"


# -----------------------------------------------------------------------------
# 1. Warehouse (Entrepôt)
# -----------------------------------------------------------------------------
class Warehouse(AuditableModel):
    """
    Entrepôt physique ou zone logistique de stockage.
    """

    name = models.CharField(
        max_length=150,
        unique=True,
        verbose_name="Nom de l'entrepôt",
    )
    code = models.CharField(
        max_length=30,
        unique=True,
        verbose_name="Code entrepôt (ex: WH-01, DEP-CENTRAL)",
    )
    address = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name="Adresse / Localisation",
    )
    description = models.TextField(
        blank=True,
        default="",
        verbose_name="Description / Remarques",
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name="Entrepôt actif",
    )

    class Meta:
        verbose_name = "Entrepôt"
        verbose_name_plural = "Entrepôts"
        ordering = ["name"]

    def __str__(self) -> str:
        return f"{self.name} [{self.code}]"

    # Alias en français/anglais pour cohérence totale
    @property
    def nom(self) -> str:
        return self.name

    @property
    def adresse(self) -> str:
        return self.address

    @property
    def isActive(self) -> bool:
        return self.is_active

    @property
    def total_bins(self) -> int:
        return self.bins.count()

    @property
    def active_bins(self) -> int:
        return self.bins.exclude(status=StorageBinStatus.MAINTENANCE).count()


# -----------------------------------------------------------------------------
# 2. Client (Client / Locataire / Déposant de Bacs)
# -----------------------------------------------------------------------------
class ClientEntrepot(AuditableModel):
    """
    Client, tiers ou service partenaire louant des bacs de stockage.
    """

    code = models.CharField(
        max_length=40,
        unique=True,
        verbose_name="Code client (ex: CLI-2026-001)",
    )
    name = models.CharField(
        max_length=200,
        verbose_name="Nom ou Raison sociale",
    )
    client_type = models.CharField(
        max_length=30,
        choices=ClientTypeChoices.choices,
        default=ClientTypeChoices.ENTREPRISE,
        verbose_name="Type de client",
    )
    contact_name = models.CharField(
        max_length=120,
        blank=True,
        default="",
        verbose_name="Nom du contact / Responsable",
    )
    email = models.EmailField(
        blank=True,
        default="",
        verbose_name="Email de contact / Facturation",
    )
    phone = models.CharField(
        max_length=40,
        blank=True,
        default="",
        verbose_name="Téléphone",
    )
    address = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name="Adresse complète",
    )
    nif = models.CharField(
        max_length=30,
        blank=True,
        default="",
        verbose_name="N.I.F (Identifiant fiscal)",
    )
    nis = models.CharField(
        max_length=30,
        blank=True,
        default="",
        verbose_name="N.I.S (Identifiant statistique)",
    )
    rc = models.CharField(
        max_length=30,
        blank=True,
        default="",
        verbose_name="Registre de Commerce",
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name="Client actif",
    )

    class Meta:
        verbose_name = "Client Entrepôt / Locataire"
        verbose_name_plural = "Clients Entrepôt / Locataires"
        ordering = ["name"]

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"

    @property
    def nom(self) -> str:
        return self.name


# -----------------------------------------------------------------------------
# 3. StorageBin (Bac de Rangement)
# -----------------------------------------------------------------------------
class StorageBin(AuditableModel):
    """
    Bac ou alvéole de rangement dans un entrepôt.
    """

    code = models.CharField(
        max_length=50,
        unique=True,
        db_index=True,
        verbose_name="Code du bac (ex: A-01-B2)",
        help_text="Identifiant unique du bac, utilisé pour les code-barres et QR codes.",
    )
    warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.CASCADE,
        related_name="bins",
        verbose_name="Entrepôt de rattachement",
    )
    capacity = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
        verbose_name="Capacité maximale (Volume m³ ou Poids kg ou Unités)",
        help_text="Capacité limite du bac.",
    )
    current_load = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
        verbose_name="Charge / Occupation actuelle",
    )
    status = models.CharField(
        max_length=20,
        choices=StorageBinStatus.choices,
        default=StorageBinStatus.AVAILABLE,
        db_index=True,
        verbose_name="Statut du bac",
    )
    daily_rate = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
        verbose_name="Tarif journalier (DA HT / jour)",
    )
    monthly_rate = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
        verbose_name="Tarif mensuel forfaitaire (DA HT / mois)",
    )
    client = models.ForeignKey(
        ClientEntrepot,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="rented_bins",
        verbose_name="Client locataire / affecté",
    )
    zone_allee = models.CharField(
        max_length=50,
        blank=True,
        default="",
        verbose_name="Allée / Travée",
    )
    rack_niveau = models.CharField(
        max_length=50,
        blank=True,
        default="",
        verbose_name="Rack / Étagère / Niveau",
    )

    class Meta:
        verbose_name = "Bac de Rangement (StorageBin)"
        verbose_name_plural = "Bacs de Rangement (StorageBins)"
        ordering = ["warehouse", "code"]

    def __str__(self) -> str:
        return f"{self.code} — {self.warehouse.name} ({self.get_status_display()})"

    @property
    def warehouseId(self) -> int:
        return self.warehouse_id

    @property
    def clientId(self):
        return self.client_id

    @property
    def currentLoad(self) -> Decimal:
        return self.current_load

    @property
    def dailyRate(self) -> Decimal:
        return self.daily_rate

    @property
    def monthlyRate(self) -> Decimal:
        return self.monthly_rate

    @property
    def available_capacity(self) -> Decimal:
        """Capacité restante disponible dans le bac."""
        if self.status == StorageBinStatus.MAINTENANCE:
            return Decimal("0.00")
        dispo = self.capacity - self.current_load
        return max(Decimal("0.00"), dispo)

    @property
    def fill_rate_percent(self) -> int:
        """Pourcentage de remplissage du bac (0 à 100%)."""
        if self.capacity <= Decimal("0.00"):
            return 0
        pct = (self.current_load / self.capacity) * Decimal("100")
        return min(100, max(0, int(round(pct))))

    @property
    def badge_css_class(self) -> str:
        """Classe CSS pour l'affichage visuel en fonction du statut."""
        mapping = {
            StorageBinStatus.AVAILABLE: "bg-emerald-50 text-emerald-700 border-emerald-300",
            StorageBinStatus.OCCUPIED: "bg-sky-50 text-sky-700 border-sky-300",
            StorageBinStatus.FULL: "bg-rose-50 text-rose-700 border-rose-300",
            StorageBinStatus.MAINTENANCE: "bg-slate-100 text-slate-700 border-slate-300",
        }
        return mapping.get(self.status, "bg-slate-50 text-slate-600 border-slate-200")

    def update_load_and_status(self, save: bool = True) -> None:
        """
        Recalcule la charge actuelle à partir de la somme des quantités d'articles
        et ajuste automatiquement le statut (AVAILABLE, OCCUPIED, FULL).
        Si le bac est en MAINTENANCE, le statut est conservé.
        """
        total = self.inventories.aggregate(total_qte=Sum("quantity"))["total_qte"] or 0
        self.current_load = Decimal(str(total))
        if self.status != StorageBinStatus.MAINTENANCE:
            if self.current_load <= Decimal("0.00"):
                self.status = StorageBinStatus.AVAILABLE
            elif self.current_load >= self.capacity:
                self.status = StorageBinStatus.FULL
            else:
                self.status = StorageBinStatus.OCCUPIED
        if save:
            self.save(update_fields=["current_load", "status", "updated_at"])


# -----------------------------------------------------------------------------
# 4. BinInventory (Contenu du bac)
# -----------------------------------------------------------------------------
class BinInventory(AuditableModel):
    """
    Contenu stocké dans un bac : relation (StorageBin, ProduitPharmaceutique).
    """

    bin = models.ForeignKey(
        StorageBin,
        on_delete=models.CASCADE,
        related_name="inventories",
        verbose_name="Bac de rangement",
    )
    product = models.ForeignKey(
        ProduitPharmaceutique,
        on_delete=models.PROTECT,
        related_name="bin_locations",
        verbose_name="Produit / Article stocké",
    )
    quantity = models.PositiveIntegerField(
        default=0,
        verbose_name="Quantité stockée",
    )

    class Meta:
        verbose_name = "Contenu du Bac (BinInventory)"
        verbose_name_plural = "Contenus des Bacs (BinInventories)"
        constraints = [
            models.UniqueConstraint(fields=["bin", "product"], name="unique_product_per_bin")
        ]
        ordering = ["bin", "product__nom_commercial"]

    def __str__(self) -> str:
        return f"{self.bin.code} : {self.product.nom_commercial} x{self.quantity}"

    @property
    def binId(self) -> int:
        return self.bin_id

    @property
    def productId(self) -> int:
        return self.product_id


# -----------------------------------------------------------------------------
# 5. BinTransfer (Historique des Transferts de Stock entre Bacs)
# -----------------------------------------------------------------------------
class BinTransfer(AuditableModel):
    """
    Enregistrement immuable d'un transfert de stock entre deux bacs.
    """

    reference = models.CharField(
        max_length=60,
        unique=True,
        db_index=True,
        verbose_name="Référence du transfert (ex: TRF-202611-0001)",
    )
    source_bin = models.ForeignKey(
        StorageBin,
        on_delete=models.PROTECT,
        related_name="transfers_out",
        verbose_name="Bac Source",
    )
    destination_bin = models.ForeignKey(
        StorageBin,
        on_delete=models.PROTECT,
        related_name="transfers_in",
        verbose_name="Bac Destination",
    )
    product = models.ForeignKey(
        ProduitPharmaceutique,
        on_delete=models.PROTECT,
        related_name="bin_transfers",
        verbose_name="Produit / Article transféré",
    )
    quantity = models.PositiveIntegerField(
        validators=[MinValueValidator(1)],
        verbose_name="Quantité transférée",
    )
    transferred_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="warehouse_transfers",
        verbose_name="Opérateur / Transféré par",
    )
    reason = models.TextField(
        blank=True,
        default="",
        verbose_name="Motif / Justification du transfert",
    )

    class Meta:
        verbose_name = "Transfert entre Bacs (BinTransfer)"
        verbose_name_plural = "Transferts entre Bacs (BinTransfers)"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return (
            f"[{self.reference}] {self.product.nom_commercial} x{self.quantity} : "
            f"{self.source_bin.code} -> {self.destination_bin.code}"
        )

    @property
    def sourceBinId(self) -> int:
        return self.source_bin_id

    @property
    def destinationBinId(self) -> int:
        return self.destination_bin_id

    @property
    def productId(self) -> int:
        return self.product_id

    @property
    def transferredBy(self) -> int:
        return self.transferred_by_id


# -----------------------------------------------------------------------------
# 6. FactureEntrepot & BinBillingLog (Facturation des Bacs)
# -----------------------------------------------------------------------------
class FactureEntrepot(AuditableModel):
    """
    Facture commerciale de location ou prestation d'entreposage WMS.
    """

    numero_facture = models.CharField(
        max_length=60,
        unique=True,
        db_index=True,
        verbose_name="N° Facture WMS (ex: FAC-WMS-2026-0001)",
    )
    client = models.ForeignKey(
        ClientEntrepot,
        on_delete=models.PROTECT,
        related_name="factures_wms",
        verbose_name="Client facturé",
    )
    date_emission = models.DateTimeField(
        default=timezone.now,
        verbose_name="Date d'émission",
    )
    date_echeance = models.DateField(
        null=True,
        blank=True,
        verbose_name="Date d'échéance",
    )
    montant_ht = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        verbose_name="Montant Total HT (DA)",
    )
    taux_tva = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("19.00"),
        verbose_name="Taux de TVA (%)",
    )
    montant_tva = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        verbose_name="Montant TVA (DA)",
    )
    montant_ttc = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        verbose_name="Montant Total TTC (DA)",
    )
    status = models.CharField(
        max_length=25,
        choices=FactureEntrepotStatus.choices,
        default=FactureEntrepotStatus.BROUILLON,
        verbose_name="Statut de la facture",
    )
    cree_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="factures_wms_creees",
        verbose_name="Créé par",
    )
    notes = models.TextField(
        blank=True,
        default="",
        verbose_name="Notes / Conditions de règlement",
    )

    class Meta:
        verbose_name = "Facture d'Entreposage (WMS)"
        verbose_name_plural = "Factures d'Entreposage (WMS)"
        ordering = ["-date_emission"]

    def __str__(self) -> str:
        return f"{self.numero_facture} — {self.client.name} ({self.montant_ttc} DA TTC)"

    def recalculer_totaux(self) -> None:
        total_ht = self.lignes.aggregate(total=Sum("montant_ht"))["total"] or Decimal("0.00")
        self.montant_ht = total_ht
        self.montant_tva = (total_ht * (self.taux_tva / Decimal("100.00"))).quantize(Decimal("0.01"))
        self.montant_ttc = (self.montant_ht + self.montant_tva).quantize(Decimal("0.01"))
        self.save(update_fields=["montant_ht", "montant_tva", "montant_ttc", "updated_at"])


class BinBillingLog(AuditableModel):
    """
    Ligne de journalisation / suivi de facturation d'un bac loué à un client.
    """

    bin = models.ForeignKey(
        StorageBin,
        on_delete=models.PROTECT,
        related_name="billing_logs",
        verbose_name="Bac loué",
    )
    client = models.ForeignKey(
        ClientEntrepot,
        on_delete=models.PROTECT,
        related_name="billing_logs",
        verbose_name="Client débiteur",
    )
    start_date = models.DateField(
        verbose_name="Date de début d'occupation",
    )
    end_date = models.DateField(
        verbose_name="Date de fin d'occupation",
    )
    billed_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
        verbose_name="Montant facturé / calculé (HT)",
    )
    status = models.CharField(
        max_length=20,
        choices=BillingLogStatus.choices,
        default=BillingLogStatus.PENDING,
        db_index=True,
        verbose_name="Statut de la ligne de facturation",
    )
    invoice = models.ForeignKey(
        FactureEntrepot,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="billing_items",
        verbose_name="Facture associée",
    )
    details = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name="Détails du calcul (jours ou forfait)",
    )

    class Meta:
        verbose_name = "Suivi Facturation Bac (BinBillingLog)"
        verbose_name_plural = "Suivis Facturation Bacs (BinBillingLogs)"
        ordering = ["-start_date"]

    def __str__(self) -> str:
        return (
            f"Bac {self.bin.code} / {self.client.name} : "
            f"{self.start_date} -> {self.end_date} ({self.billed_amount} DA)"
        )

    @property
    def binId(self) -> int:
        return self.bin_id

    @property
    def clientId(self) -> int:
        return self.client_id

    @property
    def startDate(self):
        return self.start_date

    @property
    def endDate(self):
        return self.end_date

    @property
    def billedAmount(self) -> Decimal:
        return self.billed_amount

    @property
    def invoiceId(self):
        return self.invoice_id


class LigneFactureEntrepot(AuditableModel):
    """Ligne de détail sur une facture d'entrepôt."""

    facture = models.ForeignKey(
        FactureEntrepot,
        on_delete=models.CASCADE,
        related_name="lignes",
        verbose_name="Facture WMS",
    )
    billing_log = models.ForeignKey(
        BinBillingLog,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="facture_lignes",
        verbose_name="Ligne journal de facturation liée",
    )
    bin = models.ForeignKey(
        StorageBin,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="Bac de rangement",
    )
    designation = models.CharField(
        max_length=255,
        verbose_name="Désignation de la prestation",
    )
    quantite = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=Decimal("1.00"),
        verbose_name="Quantité (Jours ou Mois)",
    )
    prix_unitaire_ht = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name="Tarif unitaire HT (DA)",
    )
    montant_ht = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        verbose_name="Montant Total HT (DA)",
    )

    class Meta:
        verbose_name = "Ligne de Facture WMS"
        verbose_name_plural = "Lignes de Factures WMS"

    def __str__(self) -> str:
        return f"{self.designation} : {self.montant_ht} DA HT"

    def save(self, *args, **kwargs):
        self.montant_ht = (self.quantite * self.prix_unitaire_ht).quantize(Decimal("0.01"))
        super().save(*args, **kwargs)
        if self.facture_id:
            self.facture.recalculer_totaux()

