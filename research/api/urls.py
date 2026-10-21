from django.urls import include, path
from rest_framework.routers import DefaultRouter

from research.api.views import ResearchTaskViewSet

router = DefaultRouter()
router.register("research/tasks", ResearchTaskViewSet, basename="research-task")

urlpatterns = [
    path("", include(router.urls)),
]
