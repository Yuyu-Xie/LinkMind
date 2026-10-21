from django.urls import include, path
from rest_framework.authtoken.views import obtain_auth_token
from rest_framework.routers import DefaultRouter

from bookmarks.api.views import BookmarkViewSet

router = DefaultRouter()
router.register("bookmarks", BookmarkViewSet, basename="bookmark")

urlpatterns = [
    path("", include(router.urls)),
    path("api-token-auth/", obtain_auth_token, name="api-token-auth"),
]
