"""
Tests unitaires et d'intégration pour le module Gestion d'Entrepôt et Bacs (WMS).
Couvre :
- Création et règles de calcul des bacs (charges, statuts, capacités disponibles)
- Transfert de stock inter-bacs atomique (cas nominaux et cas d'erreur ACID)
- Génération d'étiquettes code-barres et QR codes SVG
- Moteur de facturation (calcul prorata/forfait et émission de factures WMS)
- Endpoints et vues du tableau de bord
"""

from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import Client, TestCase
from django.urls import reverse

from apps.core.models import UserRole
from apps.entrepot.models import (
    BillingLogStatus,
    BinBillingLog,
    BinInventory,
    BinTransfer,
    ClientEntrepot,
    FactureEntrepot,
    FactureEntrepotStatus,
    StorageBin,
    StorageBinStatus,
    Warehouse,
)
from apps.entrepot.services import (
    calculate_bin_billing_amount,
    create_or_update_billing_log,
    execute_bin_transfer,
    generate_barcode_svg,
    generate_invoice_for_billing_logs,
    generate_qrcode_svg,
)
from apps.pharmacie.models import CategorieProduitChoices, ProduitPharmaceutique

User = get_user_model()


class EntrepotWMSModuleTestCase(TestCase):
    """Suite de tests automatisés pour le module WMS."""

    def setUp(self):
        # 1. Utilisateur Opérateur WMS / Admin
        self.operator = User.objects.create_user(
            username="wms_samir",
            password="HospitalPass123!",
            role=UserRole.ADMIN,
            is_staff=True,
            first_name="Samir",
            last_name="Logistique",
        )

        # 2. Entrepôts
        self.wh_central = Warehouse.objects.create(
            name="Entrepôt Central Pharmacie",
            code="WH-01",
            address="Sous-sol Bâtiment Principal, Clinique Sidi Yahia 2",
            is_active=True,
        )
        self.wh_secondaire = Warehouse.objects.create(
            name="Dépôt Logistique Nord",
            code="WH-02",
            address="Annexe Logistique, Bir Mourad Rais",
            is_active=True,
        )

        # 3. Client Locataire
        self.client_biopharm = ClientEntrepot.objects.create(
            code="CLI-BIOPHARM",
            name="Laboratoires Biopharm Algérie",
            email="contact@biopharm.dz",
            phone="+213 21 00 11 22",
            is_active=True,
        )

        # 4. Bacs de rangement
        self.bin_source = StorageBin.objects.create(
            code="A-01-B1",
            warehouse=self.wh_central,
            capacity=Decimal("100.00"),
            daily_rate=Decimal("150.00"),
            monthly_rate=Decimal("3500.00"),
            client=self.client_biopharm,
            status=StorageBinStatus.AVAILABLE,
        )
        self.bin_dest = StorageBin.objects.create(
            code="A-01-B2",
            warehouse=self.wh_central,
            capacity=Decimal("80.00"),
            daily_rate=Decimal("120.00"),
            monthly_rate=Decimal("3000.00"),
            status=StorageBinStatus.AVAILABLE,
        )
        self.bin_maintenance = StorageBin.objects.create(
            code="M-99-X1",
            warehouse=self.wh_secondaire,
            capacity=Decimal("50.00"),
            status=StorageBinStatus.MAINTENANCE,
        )

        # 5. Produits pharmaceutiques
        self.produit_paracetamol = ProduitPharmaceutique.objects.create(
            code_cip_ean13="6131112223334",
            nom_commercial="Paracétamol Biocare",
            dci="Paracétamol",
            dosage="1000 mg",
            forme_galenique="Comprimé",
            categorie=CategorieProduitChoices.MEDICAMENT_REMBOURSABLE,
            prix_achat_ht=Decimal("120.00"),
            prix_vente_ttc=Decimal("150.00"),
        )
        self.produit_amoxicilline = ProduitPharmaceutique.objects.create(
            code_cip_ean13="6134445556667",
            nom_commercial="Amoxicilline Saidal",
            dci="Amoxicilline",
            dosage="500 mg",
            forme_galenique="Gélule",
            categorie=CategorieProduitChoices.MEDICAMENT_REMBOURSABLE,
            prix_achat_ht=Decimal("250.00"),
            prix_vente_ttc=Decimal("320.00"),
        )

        # Stocker initialement 50 unités de paracétamol dans le bac source
        BinInventory.objects.create(
            bin=self.bin_source,
            product=self.produit_paracetamol,
            quantity=50,
        )
        self.bin_source.update_load_and_status()

    # -------------------------------------------------------------------------
    # Tests Modèles & Calculs Bacs
    # -------------------------------------------------------------------------
    def test_bin_capacity_and_status_calculation(self):
        """Vérifie le calcul automatique de la charge, du taux de remplissage et du statut."""
        self.bin_source.refresh_from_db()
        self.assertEqual(self.bin_source.current_load, Decimal("50.00"))
        self.assertEqual(self.bin_source.available_capacity, Decimal("50.00"))
        self.assertEqual(self.bin_source.fill_rate_percent, 50)
        self.assertEqual(self.bin_source.status, StorageBinStatus.OCCUPIED)

        # Quand la charge atteint la capacité maximale
        self.bin_source.inventories.all().update(quantity=100)
        self.bin_source.update_load_and_status()
        self.assertEqual(self.bin_source.status, StorageBinStatus.FULL)
        self.assertEqual(self.bin_source.available_capacity, Decimal("0.00"))
        self.assertEqual(self.bin_source.fill_rate_percent, 100)

        # Quand le bac est vidé
        self.bin_source.inventories.all().delete()
        self.bin_source.update_load_and_status()
        self.assertEqual(self.bin_source.status, StorageBinStatus.AVAILABLE)
        self.assertEqual(self.bin_source.current_load, Decimal("0.00"))

    # -------------------------------------------------------------------------
    # Tests Transferts Inter-Bacs Atomiques
    # -------------------------------------------------------------------------
    def test_successful_transfer_between_bins(self):
        """Vérifie un transfert transactionnel valide avec mise à jour du stock et des statuts."""
        transfer = execute_bin_transfer(
            source_bin_id=self.bin_source.id,
            destination_bin_id=self.bin_dest.id,
            product_id=self.produit_paracetamol.id,
            quantity=20,
            user=self.operator,
            reason="Rééquilibrage picking",
        )

        self.assertIsNotNone(transfer)
        self.assertTrue(transfer.reference.startswith("TRF-"))
        self.assertEqual(transfer.quantity, 20)

        # Vérification des stocks après transfert
        inv_source = BinInventory.objects.get(bin=self.bin_source, product=self.produit_paracetamol)
        inv_dest = BinInventory.objects.get(bin=self.bin_dest, product=self.produit_paracetamol)
        self.assertEqual(inv_source.quantity, 30)
        self.assertEqual(inv_dest.quantity, 20)

        # Vérification des charges
        self.bin_source.refresh_from_db()
        self.bin_dest.refresh_from_db()
        self.assertEqual(self.bin_source.current_load, Decimal("30.00"))
        self.assertEqual(self.bin_dest.current_load, Decimal("20.00"))
        self.assertEqual(self.bin_dest.status, StorageBinStatus.OCCUPIED)

    def test_transfer_rejection_insufficient_stock(self):
        """Vérifie le rejet d'un transfert demandant plus que le stock disponible."""
        with self.assertRaises(ValidationError) as ctx:
            execute_bin_transfer(
                source_bin_id=self.bin_source.id,
                destination_bin_id=self.bin_dest.id,
                product_id=self.produit_paracetamol.id,
                quantity=100,  # Bac source n'a que 50
                user=self.operator,
            )
        self.assertIn("Stock insuffisant", str(ctx.exception))

    def test_transfer_rejection_insufficient_destination_capacity(self):
        """Vérifie le rejet d'un transfert dépassant la capacité disponible du bac cible."""
        # On remplit presque le bac de destination (capacité 80, on met 70)
        BinInventory.objects.create(
            bin=self.bin_dest,
            product=self.produit_amoxicilline,
            quantity=75,
        )
        self.bin_dest.update_load_and_status()
        self.assertEqual(self.bin_dest.available_capacity, Decimal("5.00"))

        with self.assertRaises(ValidationError) as ctx:
            execute_bin_transfer(
                source_bin_id=self.bin_source.id,
                destination_bin_id=self.bin_dest.id,
                product_id=self.produit_paracetamol.id,
                quantity=20,  # Dépasse les 5 places restantes
                user=self.operator,
            )
        self.assertIn("Capacité insuffisante", str(ctx.exception))

    def test_transfer_rejection_maintenance_bin(self):
        """Vérifie le blocage d'un transfert impliquant un bac en maintenance."""
        with self.assertRaises(ValidationError) as ctx:
            execute_bin_transfer(
                source_bin_id=self.bin_source.id,
                destination_bin_id=self.bin_maintenance.id,
                product_id=self.produit_paracetamol.id,
                quantity=5,
                user=self.operator,
            )
        self.assertIn("MAINTENANCE", str(ctx.exception))

    # -------------------------------------------------------------------------
    # Tests Génération Étiquettes Code-barres & QR Codes SVG
    # -------------------------------------------------------------------------
    def test_barcode_and_qrcode_generation(self):
        """Vérifie la génération de formats vectoriels SVG propres pour les bacs."""
        barcode_svg = generate_barcode_svg("A-01-B1")
        self.assertIn("<svg", barcode_svg)
        self.assertIn("A-01-B1", barcode_svg)

        qrcode_svg = generate_qrcode_svg("A-01-B1", "Bac A-01-B1")
        self.assertIn("<svg", qrcode_svg)
        self.assertIn("Bac A-01-B1", qrcode_svg)

    # -------------------------------------------------------------------------
    # Tests Moteur de Facturation des Bacs
    # -------------------------------------------------------------------------
    def test_billing_calculation_and_invoice_generation(self):
        """Vérifie le calcul au prorata / forfait et l'émission de facture commerciale WMS."""
        # Période de 10 jours au tarif journalier de 150 DA -> 10 x 150 = 1500 DA HT
        d_start = date(2026, 11, 1)
        d_end = date(2026, 11, 10)
        amount_daily, details_daily = calculate_bin_billing_amount(self.bin_source, d_start, d_end)
        self.assertEqual(amount_daily, Decimal("1500.00"))
        self.assertIn("10 jour(s)", details_daily)

        # Période de 30 jours au forfait mensuel de 3500 DA -> 3500 DA HT
        d_end_month = date(2026, 11, 30)
        amount_monthly, details_monthly = calculate_bin_billing_amount(self.bin_source, d_start, d_end_month)
        self.assertEqual(amount_monthly, Decimal("3500.00"))

        # Création d'une ligne de suivi
        log = create_or_update_billing_log(self.bin_source, self.client_biopharm, d_start, d_end)
        self.assertEqual(log.status, BillingLogStatus.PENDING)
        self.assertEqual(log.billed_amount, Decimal("1500.00"))

        # Génération de la facture commerciale WMS
        facture = generate_invoice_for_billing_logs(
            client=self.client_biopharm,
            billing_log_ids=[log.id],
            user=self.operator,
            notes="Facture mensuelle location bac",
        )
        self.assertIsNotNone(facture)
        self.assertTrue(facture.numero_facture.startswith("FAC-WMS-"))
        self.assertEqual(facture.status, FactureEntrepotStatus.VALIDEE)
        self.assertEqual(facture.montant_ht, Decimal("1500.00"))
        # TVA 19% : 1500 * 0.19 = 285.00 DA -> TTC = 1785.00 DA
        self.assertEqual(facture.montant_tva, Decimal("285.00"))
        self.assertEqual(facture.montant_ttc, Decimal("1785.00"))

        log.refresh_from_db()
        self.assertEqual(log.status, BillingLogStatus.INVOICED)
        self.assertEqual(log.invoice, facture)

    # -------------------------------------------------------------------------
    # Tests Endpoints & Vues Frontend
    # -------------------------------------------------------------------------
    def test_warehouse_views_and_api(self):
        """Vérifie l'accessibilité de l'interface et des endpoints API WMS."""
        client = Client()
        client.force_login(self.operator)

        # 1. Dashboard
        res_dash = client.get(reverse("entrepot:dashboard"))
        self.assertEqual(res_dash.status_code, 200)
        self.assertContains(res_dash, "A-01-B1")

        # 2. API inventaire bac
        res_inv = client.get(reverse("entrepot:api_bin_inventory", kwargs={"pk": self.bin_source.id}))
        self.assertEqual(res_inv.status_code, 200)
        data = res_inv.json()
        self.assertEqual(data["bin"]["code"], "A-01-B1")
        self.assertEqual(len(data["products"]), 1)
        self.assertEqual(data["products"][0]["quantity"], 50)

        # 3. API bacs disponibles pour 10 unités
        res_avail = client.get(f"{reverse('entrepot:api_available_bins')}?min_capacity=10&exclude_bin_id={self.bin_source.id}")
        self.assertEqual(res_avail.status_code, 200)
        avail_data = res_avail.json()
        self.assertTrue(any(b["code"] == "A-01-B2" for b in avail_data["bins"]))

        # 4. Exécution transfert via API POST
        res_trf = client.post(
            reverse("entrepot:transfer_execute"),
            {
                "source_bin_id": self.bin_source.id,
                "destination_bin_id": self.bin_dest.id,
                "product_id": self.produit_paracetamol.id,
                "quantity": 10,
                "reason": "Test transfert API",
            },
        )
        self.assertEqual(res_trf.status_code, 302)

        # 5. Historique des transferts
        res_list = client.get(reverse("entrepot:transfer_list"))
        self.assertEqual(res_list.status_code, 200)
        self.assertContains(res_list, "A-01-B1")
        self.assertContains(res_list, "A-01-B2")

        # 6. Étiquette code-barres SVG
        res_bc = client.get(reverse("entrepot:bin_barcode", kwargs={"pk": self.bin_source.id}))
        self.assertEqual(res_bc.status_code, 200)
        self.assertEqual(res_bc["Content-Type"], "image/svg+xml")

        # 7. Dashboard Facturation
        res_bill = client.get(reverse("entrepot:billing_dashboard"))
        self.assertEqual(res_bill.status_code, 200)
        self.assertContains(res_bill, "Moteur de Facturation")

