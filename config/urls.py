from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.http import JsonResponse
from django.urls import include, path


def healthz(request):
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("admin/", admin.site.urls),
    path("healthz", healthz, name="healthz"),
    path("login/", auth_views.LoginView.as_view(template_name="login.html"), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("", include("bookmarks.urls")),
    path("research/", include("research.urls")),
    path("evaluation/", include("evaluation.urls")),
    path("api/", include("bookmarks.api.urls")),
    path("api/", include("research.api.urls")),
]
