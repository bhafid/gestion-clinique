"""
Vues et API Backend pour le module de Gestion d'Entrepôt et Bacs (WMS).
Comprend le tableau de bord, les endpoints AJAX de transfert et de consultation,
l'historique des transferts, la génération d'étiquettes code-barres/QR codes
et la facturation d'occupation/location des bacs.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal
import json
from typing import Any, Dict

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, F, Q, Sum
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.generic import DetailView, ListView, TemplateView

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
    create_or_update_billing_log,
    execute_bin_transfer,
    generate_barcode_svg,
    generate_invoice_for_billing_logs,
    generate_qrcode_svg,
)
from apps.pharmacie.models import ProduitPharmaceutique


# =============================================================================
# 1. Vue d'ensemble de l'Entrepôt & Grille des Bacs
# =============================================================================
class WarehouseDashboardView(LoginRequiredMixin, TemplateView):
    """
    Vue principale WMS :
    - KPIs d'occupation des entrepôts et des bacs
    - Grille visuelle des bacs filtrable (Entrepôt, Statut, Client, Recherche)
    - Modal de transfert rapide et raccourcis d'étiquetage
    """

    template_name = "entrepot/dashboard_entrepot.html"

    def get_context_data(self, **kwargs) -> Dict[str, Any]:
        context = super().get_context_data(**kwargs)
        req = self.request

        # Filtres
        warehouse_id = req.GET.get("warehouse_id", "").strip()
        status_filter = req.GET.get("status", "").strip().upper()
        client_id = req.GET.get("client_id", "").strip()
        search_query = req.GET.get("q", "").strip()

        # Queryset principal des bacs
        bins_qs = (
            StorageBin.objects.select_related("warehouse", "client")
            .prefetch_related("inventories__product")
            .order_by("warehouse__name", "code")
        )

        if warehouse_id.isdigit():
            bins_qs = bins_qs.filter(warehouse_id=int(warehouse_id))
        if status_filter in StorageBinStatus.values:
            bins_qs = bins_qs.filter(status=status_filter)
        if client_id.isdigit():
            bins_qs = bins_qs.filter(client_id=int(client_id))
        if search_query:
            bins_qs = bins_qs.filter(
                Q(code__icontains=search_query)
                | Q(warehouse__name__icontains=search_query)
                | Q(inventories__product__nom_commercial__icontains=search_query)
                | Q(client__name__icontains=search_query)
            ).distinct()

        # KPIs globaux (non filtrés pour vision globale)
        all_bins = StorageBin.objects.all()
        total_bins = all_bins.count()
        available_bins_count = all_bins.filter(status=StorageBinStatus.AVAILABLE).count()
        occupied_bins_count = all_bins.filter(status=StorageBinStatus.OCCUPIED).count()
        full_bins_count = all_bins.filter(status=StorageBinStatus.FULL).count()
        maintenance_bins_count = all_bins.filter(status=StorageBinStatus.MAINTENANCE).count()
        total_units_stored = (
            BinInventory.objects.aggregate(total=Sum("quantity"))["total"] or 0
        )

        global_capacity = all_bins.aggregate(total=Sum("capacity"))["total"] or Decimal("0.00")
        global_load = all_bins.aggregate(total=Sum("current_load"))["total"] or Decimal("0.00")
        global_fill_percent = (
            int(round((global_load / global_capacity) * 100))
            if global_capacity > 0
            else 0
        )

        context.update({
            "warehouses": Warehouse.objects.filter(is_active=True).order_by("name"),
            "clients": ClientEntrepot.objects.filter(is_active=True).order_by("name"),
            "all_products": ProduitPharmaceutique.objects.order_by("nom_commercial")[:100],
            "bins": bins_qs,
            "selected_warehouse_id": warehouse_id,
            "selected_status": status_filter,
            "selected_client_id": client_id,
            "search_query": search_query,
            "total_bins": total_bins,
            "available_bins_count": available_bins_count,
            "occupied_bins_count": occupied_bins_count,
            "full_bins_count": full_bins_count,
            "maintenance_bins_count": maintenance_bins_count,
            "total_units_stored": total_units_stored,
            "global_fill_percent": global_fill_percent,
            "statuses": StorageBinStatus.choices,
        })
        return context


# =============================================================================
# 2. Exécution du Transfert Inter-Bacs (Action Formulaire & API)
# =============================================================================
class BinTransferActionView(LoginRequiredMixin, View):
    """
    Endpoint POST pour exécuter un transfert atomique entre deux bacs.
    Supporte les requêtes HTML classiques (redirection) et JSON / AJAX.
    """

    def post(self, request: HttpRequest) -> HttpResponse:
        is_json = (
            request.content_type == "application/json"
            or request.headers.get("Accept") == "application/json"
        )
        if request.content_type == "application/json":
            try:
                data = json.loads(request.body.decode("utf-8") or "{}")
            except json.JSONDecodeError:
                return JsonResponse({"success": False, "error": "Données JSON invalides."}, status=400)
            source_bin_id = data.get("source_bin_id")
            destination_bin_id = data.get("destination_bin_id")
            product_id = data.get("product_id")
            quantity = data.get("quantity")
            reason = data.get("reason", "")
        else:
            source_bin_id = request.POST.get("source_bin_id")
            destination_bin_id = request.POST.get("destination_bin_id")
            product_id = request.POST.get("product_id")
            quantity = request.POST.get("quantity")
            reason = request.POST.get("reason", "")

        try:
            source_bin_id = int(source_bin_id)
            destination_bin_id = int(destination_bin_id)
            product_id = int(product_id)
            quantity = int(quantity)
        except (TypeError, ValueError):
            err_msg = "Paramètres de transfert invalides (identifiants ou quantité numériques requis)."
            if is_json:
                return JsonResponse({"success": False, "error": err_msg}, status=400)
            messages.error(request, err_msg)
            return redirect(request.META.get("HTTP_REFERER", reverse("entrepot:dashboard")))

        try:
            transfer = execute_bin_transfer(
                source_bin_id=source_bin_id,
                destination_bin_id=destination_bin_id,
                product_id=product_id,
                quantity=quantity,
                user=request.user,
                reason=reason,
            )
            success_msg = (
                f"Transfert {transfer.reference} effectué avec succès : "
                f"{transfer.product.nom_commercial} x{transfer.quantity} "
                f"transféré(s) de {transfer.source_bin.code} vers {transfer.destination_bin.code}."
            )
            if is_json:
                return JsonResponse({
                    "success": True,
                    "message": success_msg,
                    "reference": transfer.reference,
                    "source_bin": {
                        "id": transfer.source_bin.id,
                        "code": transfer.source_bin.code,
                        "current_load": float(transfer.source_bin.current_load),
                        "status": transfer.source_bin.status,
                    },
                    "destination_bin": {
                        "id": transfer.destination_bin.id,
                        "code": transfer.destination_bin.code,
                        "current_load": float(transfer.destination_bin.current_load),
                        "status": transfer.destination_bin.status,
                    },
                })
            messages.success(request, success_msg)
            return redirect(request.META.get("HTTP_REFERER", reverse("entrepot:dashboard")))
        except ValidationError as exc:
            err_msg = exc.message if hasattr(exc, "message") else "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc)
            if is_json:
                return JsonResponse({"success": False, "error": err_msg}, status=400)
            messages.error(request, f"Échec du transfert : {err_msg}")
            return redirect(request.META.get("HTTP_REFERER", reverse("entrepot:dashboard")))


# =============================================================================
# 3. Endpoints AJAX pour la sélection dynamique dans les modals
# =============================================================================
class BinInventoryAPIView(LoginRequiredMixin, View):
    """
    GET /entrepot/api/bins/<int:pk>/inventory/
    Renvoie le contenu actuel d'un bac pour charger les produits dans la modal de transfert.
    """

    def get(self, request: HttpRequest, pk: int) -> HttpResponse:
        bin_obj = get_object_or_404(StorageBin.objects.select_related("warehouse"), pk=pk)
        inventories = (
            BinInventory.objects.filter(bin=bin_obj, quantity__gt=0)
            .select_related("product")
            .order_by("product__nom_commercial")
        )
        data = {
            "bin": {
                "id": bin_obj.id,
                "code": bin_obj.code,
                "warehouse": bin_obj.warehouse.name,
                "capacity": float(bin_obj.capacity),
                "current_load": float(bin_obj.current_load),
                "available_capacity": float(bin_obj.available_capacity),
                "status": bin_obj.status,
            },
            "products": [
                {
                    "id": inv.product.id,
                    "name": inv.product.nom_commercial,
                    "code_cip": inv.product.code_cip_ean13,
                    "dosage": inv.product.dosage,
                    "quantity": inv.quantity,
                }
                for inv in inventories
            ],
        }
        return JsonResponse(data)


class AvailableDestinationBinsAPIView(LoginRequiredMixin, View):
    """
    GET /entrepot/api/bins/available/?min_capacity=X&exclude_bin_id=Y
    Renvoie la liste des bacs cibles ayant une capacité disponible >= min_capacity.
    """

    def get(self, request: HttpRequest) -> HttpResponse:
        min_capacity_raw = request.GET.get("min_capacity", "1")
        exclude_bin_id = request.GET.get("exclude_bin_id", "")
        warehouse_id = request.GET.get("warehouse_id", "")

        try:
            min_cap = Decimal(min_capacity_raw)
        except Exception:
            min_cap = Decimal("1.00")

        qs = StorageBin.objects.exclude(status=StorageBinStatus.MAINTENANCE).select_related("warehouse")
        if exclude_bin_id.isdigit():
            qs = qs.exclude(id=int(exclude_bin_id))
        if warehouse_id.isdigit():
            qs = qs.filter(warehouse_id=int(warehouse_id))

        results = []
        for b in qs:
            if b.available_capacity >= min_cap:
                results.append({
                    "id": b.id,
                    "code": b.code,
                    "warehouse": b.warehouse.name,
                    "available_capacity": float(b.available_capacity),
                    "capacity": float(b.capacity),
                    "current_load": float(b.current_load),
                    "fill_rate_percent": b.fill_rate_percent,
                    "status": b.status,
                })

        return JsonResponse({"bins": results})


# =============================================================================
# 4. Étiquettes Code-barres & QR Codes SVG
# =============================================================================
class StorageBinBarcodeView(LoginRequiredMixin, View):
    """GET /entrepot/bins/<int:pk>/barcode/ : SVG du code-barres pour impression."""

    def get(self, request: HttpRequest, pk: int) -> HttpResponse:
        bin_obj = get_object_or_404(StorageBin, pk=pk)
        svg_content = generate_barcode_svg(bin_obj.code)
        response = HttpResponse(svg_content, content_type="image/svg+xml")
        response["Content-Disposition"] = f'inline; filename="barcode_{bin_obj.code}.svg"'
        return response


class StorageBinQRCodeView(LoginRequiredMixin, View):
    """GET /entrepot/bins/<int:pk>/qrcode/ : SVG du QR code pour impression."""

    def get(self, request: HttpRequest, pk: int) -> HttpResponse:
        bin_obj = get_object_or_404(StorageBin, pk=pk)
        svg_content = generate_qrcode_svg(bin_obj.code, title=f"{bin_obj.code} ({bin_obj.warehouse.name})")
        response = HttpResponse(svg_content, content_type="image/svg+xml")
        response["Content-Disposition"] = f'inline; filename="qrcode_{bin_obj.code}.svg"'
        return response


# =============================================================================
# 5. Historique des Mouvements et Transferts
# =============================================================================
class BinTransferListView(LoginRequiredMixin, ListView):
    """
    Tableau complet de l'historique des transferts inter-bacs avec filtres :
    date de début, date de fin, bac source/dest, produit, utilisateur.
    """

    model = BinTransfer
    template_name = "entrepot/transfer_list.html"
    context_object_name = "transfers"
    paginate_by = 25

    def get_queryset(self):
        qs = (
            BinTransfer.objects.select_related(
                "source_bin__warehouse",
                "destination_bin__warehouse",
                "product",
                "transferred_by",
            )
            .order_by("-created_at")
        )
        req = self.request
        search = req.GET.get("q", "").strip()
        date_from = req.GET.get("date_from", "").strip()
        date_to = req.GET.get("date_to", "").strip()
        product_id = req.GET.get("product_id", "").strip()
        source_bin_id = req.GET.get("source_bin_id", "").strip()
        destination_bin_id = req.GET.get("destination_bin_id", "").strip()

        if search:
            qs = qs.filter(
                Q(reference__icontains=search)
                | Q(source_bin__code__icontains=search)
                | Q(destination_bin__code__icontains=search)
                | Q(product__nom_commercial__icontains=search)
                | Q(reason__icontains=search)
                | Q(transferred_by__username__icontains=search)
            )
        if date_from:
            try:
                dt_from = datetime.strptime(date_from, "%Y-%m-%d")
                qs = qs.filter(created_at__date__gte=dt_from.date())
            except ValueError:
                pass
        if date_to:
            try:
                dt_to = datetime.strptime(date_to, "%Y-%m-%d")
                qs = qs.filter(created_at__date__lte=dt_to.date())
            except ValueError:
                pass
        if product_id.isdigit():
            qs = qs.filter(product_id=int(product_id))
        if source_bin_id.isdigit():
            qs = qs.filter(source_bin_id=int(source_bin_id))
        if destination_bin_id.isdigit():
            qs = qs.filter(destination_bin_id=int(destination_bin_id))

        return qs

    def get_context_data(self, **kwargs) -> Dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context.update({
            "products": ProduitPharmaceutique.objects.order_by("nom_commercial")[:100],
            "bins": StorageBin.objects.select_related("warehouse").order_by("code"),
            "search_query": self.request.GET.get("q", ""),
            "date_from": self.request.GET.get("date_from", ""),
            "date_to": self.request.GET.get("date_to", ""),
            "selected_product_id": self.request.GET.get("product_id", ""),
            "selected_source_bin_id": self.request.GET.get("source_bin_id", ""),
            "selected_dest_bin_id": self.request.GET.get("destination_bin_id", ""),
        })
        return context


# =============================================================================
# 6. Tableau de bord Facturation des Bacs (Moteur de calcul & facturation)
# =============================================================================
class BinBillingDashboardView(LoginRequiredMixin, TemplateView):
    """
    Tableau de bord de facturation des bacs loués :
    - Récapitulatif par client
    - Calcul de facturation au prorata journalier ou mensuel
    - Génération en un clic des factures commerciales WMS
    """

    template_name = "entrepot/billing_dashboard.html"

    def get_context_data(self, **kwargs) -> Dict[str, Any]:
        context = super().get_context_data(**kwargs)
        today = timezone.localdate()
        first_of_month = today.replace(day=1)

        # Clients ayant des bacs attribués
        clients = (
            ClientEntrepot.objects.filter(is_active=True)
            .prefetch_related("rented_bins__warehouse")
            .order_by("name")
        )

        # Lignes de facturation en attente
        pending_logs = (
            BinBillingLog.objects.filter(status=BillingLogStatus.PENDING)
            .select_related("bin__warehouse", "client")
            .order_by("client__name", "-start_date")
        )

        # Dernières factures WMS émises
        invoices = (
            FactureEntrepot.objects.select_related("client", "cree_par")
            .prefetch_related("lignes")
            .order_by("-date_emission")[:20]
        )

        total_pending_amount = (
            pending_logs.aggregate(total=Sum("billed_amount"))["total"] or Decimal("0.00")
        )
        total_invoiced_amount = (
            FactureEntrepot.objects.exclude(status=FactureEntrepotStatus.ANNULEE)
            .aggregate(total=Sum("montant_ttc"))["total"] or Decimal("0.00")
        )

        context.update({
            "clients": clients,
            "pending_logs": pending_logs,
            "invoices": invoices,
            "total_pending_amount": total_pending_amount,
            "total_invoiced_amount": total_invoiced_amount,
            "default_start_date": first_of_month.strftime("%Y-%m-%d"),
            "default_end_date": today.strftime("%Y-%m-%d"),
            "all_rented_bins": StorageBin.objects.filter(client__isnull=False).select_related("warehouse", "client"),
        })
        return context


class BinBillingCalculateActionView(LoginRequiredMixin, View):
    """POST /entrepot/billing/calculate/ : Crée ou met à jour les lignes de calcul de facturation."""

    def post(self, request: HttpRequest) -> HttpResponse:
        bin_id = request.POST.get("bin_id", "").strip()
        client_id = request.POST.get("client_id", "").strip()
        start_date_raw = request.POST.get("start_date", "").strip()
        end_date_raw = request.POST.get("end_date", "").strip()

        if not (bin_id.isdigit() and client_id.isdigit() and start_date_raw and end_date_raw):
            messages.error(request, "Veuillez renseigner le bac, le client et les dates de période valides.")
            return redirect("entrepot:billing_dashboard")

        try:
            start_date = datetime.strptime(start_date_raw, "%Y-%m-%d").date()
            end_date = datetime.strptime(end_date_raw, "%Y-%m-%d").date()
            if end_date < start_date:
                raise ValidationError("La date de fin ne peut pas être antérieure à la date de début.")
        except (ValueError, ValidationError) as exc:
            messages.error(request, f"Dates invalides : {exc}")
            return redirect("entrepot:billing_dashboard")

        bin_obj = get_object_or_404(StorageBin, pk=int(bin_id))
        client = get_object_or_404(ClientEntrepot, pk=int(client_id))

        log = create_or_update_billing_log(
            bin_obj=bin_obj,
            client=client,
            start_date=start_date,
            end_date=end_date,
            force_recalculate=True,
        )
        messages.success(
            request,
            f"Ligne de facturation calculée pour le bac {bin_obj.code} ({client.name}) : "
            f"{log.billed_amount} DA HT ({log.details}).",
        )
        return redirect("entrepot:billing_dashboard")


class BinBillingGenerateInvoiceActionView(LoginRequiredMixin, View):
    """POST /entrepot/billing/generate-invoice/ : Génère la facture WMS pour les lignes sélectionnées."""

    def post(self, request: HttpRequest) -> HttpResponse:
        client_id = request.POST.get("client_id", "").strip()
        log_ids = request.POST.getlist("billing_log_ids")
        notes = request.POST.get("notes", "").strip()

        if not client_id.isdigit() or not log_ids:
            messages.error(request, "Veuillez sélectionner au moins une ligne de facturation à facturer.")
            return redirect("entrepot:billing_dashboard")

        client = get_object_or_404(ClientEntrepot, pk=int(client_id))
        clean_log_ids = [int(i) for i in log_ids if i.isdigit()]

        try:
            facture = generate_invoice_for_billing_logs(
                client=client,
                billing_log_ids=clean_log_ids,
                user=request.user,
                notes=notes,
            )
            messages.success(
                request,
                f"Facture WMS {facture.numero_facture} générée avec succès pour {client.name} : "
                f"{facture.montant_ttc} DA TTC ({len(clean_log_ids)} bac(s)).",
            )
            return redirect("entrepot:invoice_detail", pk=facture.id)
        except ValidationError as exc:
            messages.error(request, f"Impossible d'émettre la facture : {exc}")
            return redirect("entrepot:billing_dashboard")


class FactureEntrepotDetailView(LoginRequiredMixin, DetailView):
    """Visualisation officielle et imprimable de la facture d'entreposage WMS."""

    model = FactureEntrepot
    template_name = "entrepot/invoice_detail.html"
    context_object_name = "facture"

    def get_context_data(self, **kwargs) -> Dict[str, Any]:
        context = super().get_context_data(**kwargs)
        from apps.facturation.models import EtablissementFiscal
        etab = EtablissementFiscal.objects.first()
        context["etablissement"] = etab
        return context


# =============================================================================
# 7. Actions CRUD rapides sur les Bacs (Création, Édition, Maintenance)
# =============================================================================
class StorageBinCreateOrEditView(LoginRequiredMixin, View):
    """POST /entrepot/bins/save/ : Création ou modification rapide d'un bac."""

    def post(self, request: HttpRequest) -> HttpResponse:
        bin_id = request.POST.get("bin_id", "").strip()
        code = request.POST.get("code", "").strip().upper()
        warehouse_id = request.POST.get("warehouse_id", "").strip()
        capacity = request.POST.get("capacity", "").strip()
        daily_rate = request.POST.get("daily_rate", "0").strip()
        monthly_rate = request.POST.get("monthly_rate", "0").strip()
        client_id = request.POST.get("client_id", "").strip()
        status_code = request.POST.get("status", StorageBinStatus.AVAILABLE).strip().upper()
        zone_allee = request.POST.get("zone_allee", "").strip()
        rack_niveau = request.POST.get("rack_niveau", "").strip()

        if not (code and warehouse_id.isdigit() and capacity):
            messages.error(request, "Code, entrepôt et capacité sont obligatoires.")
            return redirect(request.META.get("HTTP_REFERER", reverse("entrepot:dashboard")))

        warehouse = get_object_or_404(Warehouse, pk=int(warehouse_id))
        client = ClientEntrepot.objects.filter(pk=int(client_id)).first() if client_id.isdigit() else None

        try:
            cap_dec = Decimal(capacity)
            daily_dec = Decimal(daily_rate or "0")
            monthly_dec = Decimal(monthly_rate or "0")
            if cap_dec <= 0:
                raise ValueError
        except Exception:
            messages.error(request, "Les valeurs numériques (capacité, tarifs) sont invalides.")
            return redirect(request.META.get("HTTP_REFERER", reverse("entrepot:dashboard")))

        if bin_id.isdigit():
            bin_obj = get_object_or_404(StorageBin, pk=int(bin_id))
            bin_obj.code = code
            bin_obj.warehouse = warehouse
            bin_obj.capacity = cap_dec
            bin_obj.daily_rate = daily_dec
            bin_obj.monthly_rate = monthly_dec
            bin_obj.client = client
            bin_obj.zone_allee = zone_allee
            bin_obj.rack_niveau = rack_niveau
            if status_code in StorageBinStatus.values:
                bin_obj.status = status_code
            bin_obj.save()
            bin_obj.update_load_and_status()
            messages.success(request, f"Bac {bin_obj.code} mis à jour avec succès.")
        else:
            if StorageBin.objects.filter(code=code).exists():
                messages.error(request, f"Un bac portant le code {code} existe déjà.")
                return redirect(request.META.get("HTTP_REFERER", reverse("entrepot:dashboard")))

            bin_obj = StorageBin.objects.create(
                code=code,
                warehouse=warehouse,
                capacity=cap_dec,
                daily_rate=daily_dec,
                monthly_rate=monthly_dec,
                client=client,
                status=status_code if status_code in StorageBinStatus.values else StorageBinStatus.AVAILABLE,
                zone_allee=zone_allee,
                rack_niveau=rack_niveau,
            )
            messages.success(request, f"Nouveau bac {bin_obj.code} créé avec succès.")

        return redirect(request.META.get("HTTP_REFERER", reverse("entrepot:dashboard")))


class StorageBinToggleMaintenanceView(LoginRequiredMixin, View):
    """POST /entrepot/bins/<int:pk>/toggle-maintenance/ : Bascule en maintenance."""

    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        bin_obj = get_object_or_404(StorageBin, pk=pk)
        if bin_obj.status == StorageBinStatus.MAINTENANCE:
            bin_obj.status = StorageBinStatus.AVAILABLE
            bin_obj.update_load_and_status(save=True)
            messages.success(request, f"Le bac {bin_obj.code} a été réactivé (Statut: {bin_obj.get_status_display()}).")
        else:
            bin_obj.status = StorageBinStatus.MAINTENANCE
            bin_obj.save(update_fields=["status", "updated_at"])
            messages.warning(request, f"Le bac {bin_obj.code} a été basculé en MAINTENANCE (Bloqué pour les transferts).")

        return redirect(request.META.get("HTTP_REFERER", reverse("entrepot:dashboard")))

