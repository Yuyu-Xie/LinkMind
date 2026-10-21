from django.urls import path

from research import views

urlpatterns = [
    path("", views.task_list, name="research-list"),
    path("create/", views.task_create, name="research-create"),
    path("claims/", views.claim_list, name="research-claims"),
    path("<int:pk>/", views.task_detail, name="research-detail"),
    path("<int:pk>/status/", views.task_status, name="research-status"),
    path("<int:pk>/cancel/", views.task_cancel, name="research-cancel"),
    path("<int:pk>/retry/", views.task_retry, name="research-retry"),
]
