from django.urls import path

from evaluation import views

urlpatterns = [
    path("", views.run_list, name="evaluation-list"),
    path("<int:pk>/", views.run_detail, name="evaluation-detail"),
]
