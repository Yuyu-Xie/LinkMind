from django.urls import path

from bookmarks import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("bookmarks/", views.bookmark_list, name="bookmark-list"),
    path("bookmarks/create/", views.bookmark_create, name="bookmark-create"),
    path("bookmarks/<int:pk>/", views.bookmark_detail, name="bookmark-detail"),
    path("bookmarks/<int:pk>/archive/", views.bookmark_archive, name="bookmark-archive"),
    path("bookmarks/<int:pk>/delete/", views.bookmark_delete, name="bookmark-delete"),
]
