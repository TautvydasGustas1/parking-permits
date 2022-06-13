import csv
import json
import logging

from django.conf import settings
from django.db import transaction
from django.http import (
    Http404,
    HttpResponse,
    HttpResponseBadRequest,
    HttpResponseNotFound,
)
from django.views.decorators.http import require_safe
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from helsinki_gdpr.views import DeletionNotAllowed, DryRunSerializer, GDPRAPIView
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .decorators import require_ad_admin
from .exporters import DataExporter, PdfExporter
from .forms import DataExportForm, PdfExportForm
from .models import Customer, Order
from .models.common import SourceSystem
from .models.order import OrderStatus
from .models.parking_permit import ParkingPermit, ParkingPermitStatus
from .serializers import (
    MessageResponseSerializer,
    OrderSerializer,
    ResolveAvailabilityResponseSerializer,
    ResolveAvailabilitySerializer,
    ResolvePriceResponseSerializer,
    RightOfPurchaseResponseSerializer,
    TalpaPayloadSerializer,
)
from .services.mail import PermitEmailType, send_permit_email
from .utils import get_meta_value, snake_to_camel_dict

logger = logging.getLogger("db")


class TalpaResolveAvailability(APIView):
    @swagger_auto_schema(
        operation_description="Resolve product availability.",
        request_body=ResolveAvailabilitySerializer,
        responses={
            200: openapi.Response(
                "Product is always available for purchase.",
                ResolveAvailabilityResponseSerializer,
            )
        },
        tags=["ResolveAvailability"],
    )
    def post(self, request, format=None):
        logger.info(
            f"Data received for resolve availability = {json.dumps(request.data)}"
        )
        shared_product_id = request.data.get("productId")
        res = snake_to_camel_dict({"product_id": shared_product_id, "value": True})
        logger.info(f"Resolve availability response = {json.dumps(res)}")
        return Response(res)


class TalpaResolvePrice(APIView):
    @swagger_auto_schema(
        operation_description="Resolve price of product from an order item.",
        request_body=TalpaPayloadSerializer,
        responses={
            200: openapi.Response("Resolve price", ResolvePriceResponseSerializer)
        },
        tags=["ResolvePrice"],
    )
    def post(self, request, format=None):
        logger.info(f"Data received for resolve price = {json.dumps(request.data)}")
        meta = request.data.get("orderItem").get("meta")
        permit_id = get_meta_value(meta, "permitId")

        if permit_id is None:
            return Response(
                {
                    "message": "No permitId key available in meta list of key-value pairs"
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            permit = ParkingPermit.objects.get(pk=permit_id)
            products_with_quantity = permit.get_products_with_quantities()
            product, quantity, date_range = products_with_quantity[0]
            price = product.get_modified_unit_price(
                permit.vehicle.is_low_emission, permit.is_secondary_vehicle
            )
            vat = product.vat
            price_vat = price * vat
        except Exception as e:
            logger.error(f"Resolve price error = {str(e)}")
            return Response({"message": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        response = snake_to_camel_dict(
            {
                "row_price_net": float(price - price_vat),
                "row_price_vat": float(price_vat),
                "row_price_total": float(price),
                "price_net": float(price - price_vat),
                "price_vat": float(price_vat),
                "price_gross": float(price),
                "vat_percentage": float(product.vat_percentage),
            }
        )
        logger.info(f"Resolve price response = {json.dumps(response)}")
        return Response(response)


class TalpaResolveRightOfPurchase(APIView):
    @swagger_auto_schema(
        operation_description="Used as an webhook by Talpa in order to send an order notification.",
        request_body=TalpaPayloadSerializer,
        responses={
            200: openapi.Response(
                "Right of purchase response", RightOfPurchaseResponseSerializer
            )
        },
        tags=["RightOfPurchase"],
    )
    def post(self, request):
        logger.info(
            f"Data received for resolve right of purchase = {json.dumps(request.data)}"
        )
        meta = request.data.get("orderItem").get("meta")
        permit_id = get_meta_value(meta, "permitId")
        user_id = request.data.get("userId")

        try:
            permit = ParkingPermit.objects.get(pk=permit_id)
            customer = permit.customer
            customer.fetch_driving_licence_detail()
            vehicle = customer.fetch_vehicle_detail(permit.vehicle.registration_number)
            is_user_of_vehicle = customer.is_user_of_vehicle(vehicle)
            has_valid_driving_licence = customer.has_valid_driving_licence_for_vehicle(
                vehicle
            )
            right_of_purchase = (
                is_user_of_vehicle
                and customer.driving_licence.active
                and has_valid_driving_licence
                and not vehicle.is_due_for_inspection()
            )
            res = snake_to_camel_dict(
                {
                    "error_message": "",
                    "right_of_purchase": right_of_purchase,
                    "user_id": user_id,
                }
            )
        except Exception as e:
            res = snake_to_camel_dict(
                {
                    "error_message": str(e),
                    "right_of_purchase": False,
                    "user_id": user_id,
                }
            )

        logger.info(f"Resolve right of purchase response = {json.dumps(res)}")
        return Response(res)


class OrderView(APIView):
    @swagger_auto_schema(
        operation_description="Used as an webhook by Talpa in order to send an order notification.",
        request_body=OrderSerializer,
        security=[],
        responses={
            200: openapi.Response("Order received response", MessageResponseSerializer)
        },
        tags=["Order"],
    )
    @transaction.atomic
    def post(self, request, format=None):
        logger.info(f"Order received. Data = {json.dumps(request.data)}")
        talpa_order_id = request.data.get("orderId")
        event_type = request.data.get("eventType")
        if not talpa_order_id:
            logger.error("Talpa order id is missing from request data")
            return Response({"message": "No order id is provided"}, status=400)

        if event_type == "PAYMENT_PAID":
            order = Order.objects.get(talpa_order_id=talpa_order_id)
            order.status = OrderStatus.CONFIRMED
            order.save()
            for permit in order.permits.all():
                permit.status = ParkingPermitStatus.VALID
                permit.save()
                send_permit_email(PermitEmailType.CREATED, permit)
                if not settings.DEBUG:
                    permit.create_parkkihubi_permit()

        logger.info(f"{order} is confirmed and order permits are set to VALID ")
        return Response({"message": "Order received"}, status=200)


class ParkingPermitsGDPRAPIView(GDPRAPIView):
    def get_object(self) -> Customer:
        try:
            customer = Customer.objects.get(
                source_system=SourceSystem.HELSINKI_PROFILE, source_id=self.kwargs["id"]
            )
        except Customer.DoesNotExist:
            raise Http404
        else:
            self.check_object_permissions(self.request, customer)
            return customer

    def _delete(self):
        customer = self.get_object()
        if not customer.can_be_deleted:
            raise DeletionNotAllowed()
        customer.delete_all_data()

    def delete(self, request, *args, **kwargs):
        dry_run_serializer = DryRunSerializer(data=request.data)
        dry_run_serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            self._delete()
            if dry_run_serializer.data["dry_run"]:
                transaction.set_rollback(True)
        return Response(status=status.HTTP_204_NO_CONTENT)


@require_ad_admin
@require_safe
def csv_export(request):
    form = DataExportForm(request.GET)
    if not form.is_valid():
        return HttpResponseBadRequest()

    filename = form.cleaned_data["data_type"]
    response = HttpResponse(
        content_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}.csv"'},
    )
    data_exporter = DataExporter(
        form.cleaned_data["data_type"],
        form.cleaned_data["order_by"],
        form.cleaned_data["search_items"],
    )
    writer = csv.writer(response)
    writer.writerow(data_exporter.get_headers())
    writer.writerows(data_exporter.get_rows())
    return response


@require_ad_admin
@require_safe
def pdf_export(request):
    form = PdfExportForm(request.GET)
    if not form.is_valid():
        return HttpResponseBadRequest()

    pdf_exporter = PdfExporter(
        form.cleaned_data["data_type"],
        form.cleaned_data["object_id"],
    )

    pdf = pdf_exporter.get_pdf()
    if not pdf:
        return HttpResponseNotFound()

    filename = f'{form.cleaned_data["data_type"]}_{form.cleaned_data["object_id"]}'
    response = HttpResponse(
        content_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}.pdf"'},
        content=pdf.output(dest="S").encode("latin-1"),
    )
    return response
