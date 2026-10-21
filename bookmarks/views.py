from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from bookmarks.forms import BookmarkForm
from bookmarks.models import Bookmark
from bookmarks.queries import query_bookmarks, query_tags
from bookmarks.services import bookmarks as bookmark_service
from bookmarks.services.reader import get_or_fetch_content
from bookmarks.services.tags import parse_tag_names


@login_required
def dashboard(request):
    bookmarks = Bookmark.objects.filter(owner=request.user)
    stats = bookmarks.aggregate(
        total=Count("id"),
        unread=Count("id", filter=Q(unread=True)),
        archived=Count("id", filter=Q(is_archived=True)),
    )
    recent = bookmarks.select_related("content").prefetch_related("tags")[:8]
    recent_tasks = request.user.research_tasks.all()[:5]
    return render(
        request,
        "dashboard.html",
        {
            "stats": stats,
            "recent": recent,
            "recent_tasks": recent_tasks,
            "task_total": request.user.research_tasks.count(),
        },
    )


@login_required
def bookmark_list(request):
    q = request.GET.get("q", "")
    tag_names = parse_tag_names(request.GET.get("tags", ""))
    archived = request.GET.get("archived") in {"1", "true", "yes"}
    bookmark_qs = query_bookmarks(
        request.user, q=q, tag_names=tag_names, archived=archived
    )
    context = {
        "bookmarks": bookmark_qs,
        "q": q,
        "tags": query_tags(request.user),
        "selected_tags": tag_names,
        "archived": archived,
        "form": BookmarkForm(),
    }
    if request.headers.get("HX-Request"):
        return render(request, "bookmarks/_bookmark_list.html", context)
    return render(request, "bookmarks/list.html", context)


@login_required
@require_POST
def bookmark_create(request):
    form = BookmarkForm(request.POST)
    if form.is_valid():
        data = form.cleaned_data
        bookmark_service.create_bookmark(
            owner=request.user,
            url=data["url"],
            title=data.get("title", ""),
            description=data.get("description", ""),
            notes=data.get("notes", ""),
            tag_names=parse_tag_names(data.get("tag_names", "")),
            unread=data.get("unread", False),
        )
        messages.success(request, "书签已保存")
    else:
        messages.error(request, "书签保存失败：检查 URL 格式")

    if request.headers.get("HX-Request"):
        context = {
            "bookmarks": query_bookmarks(request.user),
            "tags": query_tags(request.user),
            "selected_tags": [],
            "q": "",
            "archived": False,
            "form": BookmarkForm(),
        }
        return render(request, "bookmarks/_bookmark_list.html", context)
    return redirect("bookmark-list")


@login_required
def bookmark_detail(request, pk: int):
    bookmark = get_object_or_404(Bookmark, pk=pk, owner=request.user)
    content = get_or_fetch_content(bookmark)
    return render(
        request, "bookmarks/detail.html", {"bookmark": bookmark, "content": content}
    )


@login_required
@require_POST
def bookmark_archive(request, pk: int):
    bookmark = get_object_or_404(Bookmark, pk=pk, owner=request.user)
    bookmark_service.update_bookmark(bookmark, is_archived=not bookmark.is_archived)
    return redirect(request.META.get("HTTP_REFERER") or "bookmark-list")


@login_required
@require_POST
def bookmark_delete(request, pk: int):
    bookmark = get_object_or_404(Bookmark, pk=pk, owner=request.user)
    bookmark_service.delete_bookmark(bookmark)
    messages.success(request, "书签已删除")
    return redirect(request.META.get("HTTP_REFERER") or "bookmark-list")
