from django.urls import path

from . import views

urlpatterns = [
    path("health", views.HealthCheckView.as_view(), name="health-check"),
    path("users", views.UserRegisterView.as_view(), name="user-register"),
    path("auth/login", views.LoginView.as_view(), name="auth-login"),
    path("documents", views.DocumentListCreateView.as_view(), name="document-list-create"),
    path(
        "documents/<str:document_id>",
        views.DocumentDetailView.as_view(),
        name="document-detail",
    ),
    path(
        "documents/<str:document_id>/queries",
        views.DocumentQueryListCreateView.as_view(),
        name="document-queries",
    ),
]