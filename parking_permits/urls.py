from django.urls import path

from parking_permits import graphql, views

app_name = "parking_permits"
urlpatterns = [
    path("graphql/", graphql.view, name="graphql"),
    path("admin-graphql/", graphql.admin_view, name="admin-graphql"),
    path(
        "api/talpa/resolve-availability/",
        views.TalpaResolveAvailability.as_view(),
        name="talpa-availability",
    ),
    path(
        "api/talpa/resolve-price/",
        views.TalpaResolvePrice.as_view(),
        name="talpa-price",
    ),
    path(
        "api/talpa/resolve-right-of-purchase/",
        views.TalpaResolveRightOfPurchase.as_view(),
        name="talpa-right-of-purchase",
    ),
    path(
        "api/talpa/order/",
        views.OrderView.as_view(),
        name="order-notify",
    ),
    path(
        "gdpr-api/v1/profiles/<str:id>",
        views.ParkingPermitsGDPRAPIView.as_view(),
        name="gdpr_v1",
    ),
    path("export/<str:data_type>", views.csv_export, name="export"),
    path("export_pdf", views.pdf_export, name="export_pdf"),
]
