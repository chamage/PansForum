from collections import defaultdict

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import F, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from pans_agora.utils import ratelimit, safe_next

from .forms import CommentForm, CommunityForm, ReportForm, ThreadEditForm, ThreadForm
from .models import Comment, CommentVote, Community, Membership, Report, Thread, ThreadVote

THREAD_SORTS = {
    "hot": ("-hot_rank",),
    "new": ("-created_at",),
    "top": ("-score", "-created_at"),
}
COMMENT_SORTS = {
    "best": ("-score", "created_at"),
    "new": ("-created_at",),
    "old": ("created_at",),
}
THREAD_SORT_OPTIONS = [("hot", "🔥 Hot"), ("new", "✨ New"), ("top", "⬆ Top")]
COMMENT_SORT_OPTIONS = [("best", "Best"), ("new", "Newest"), ("old", "Oldest")]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sort(request, options, default):
    value = request.GET.get("sort", default)
    return value if value in options else default


def _page(request, qs, per_page=20):
    return Paginator(qs, per_page).get_page(request.GET.get("page"))


def _thread_votes(user, threads):
    if not user.is_authenticated:
        return {}
    ids = [t.pk for t in threads]
    return dict(ThreadVote.objects.filter(user=user, thread_id__in=ids).values_list("thread_id", "value"))


def _joined_ids(user):
    if not user.is_authenticated:
        return set()
    return set(Membership.objects.filter(user=user).values_list("community_id", flat=True))


def _is_ajax(request):
    return request.headers.get("x-requested-with") == "XMLHttpRequest"


# ---------------------------------------------------------------------------
# Feeds
# ---------------------------------------------------------------------------


def home(request):
    sort = _sort(request, THREAD_SORTS, "hot")
    joined = _joined_ids(request.user)
    feed = "all" if request.GET.get("feed") == "all" or not joined else "mine"

    threads = Thread.objects.select_related("author", "community")
    if feed == "mine":
        threads = threads.filter(community_id__in=joined)
    page = _page(request, threads.order_by(*THREAD_SORTS[sort]))

    context = {
        "page": page,
        "sort": sort,
        "sort_options": THREAD_SORT_OPTIONS,
        "feed": feed,
        "has_joined": bool(joined),
        "votes": _thread_votes(request.user, page.object_list),
        "popular": Community.objects.order_by("-member_count", "name")[:8],
        "joined_ids": joined,
    }
    return render(request, "forum/home.html", context)


def search(request):
    q = " ".join(request.GET.get("q", "").split())[:100]
    threads = communities = users = None
    if len(q) >= 2:
        threads = (
            Thread.objects.filter(Q(title__icontains=q) | Q(body__icontains=q))
            .select_related("author", "community")
            .order_by("-hot_rank")
        )
        communities = Community.objects.filter(Q(name__icontains=q) | Q(description__icontains=q))[:6]
        users = get_user_model().objects.filter(
            Q(username__icontains=q) | Q(display_name__icontains=q), is_active=True
        )[:6]
        threads = _page(request, threads)
    return render(
        request,
        "forum/search.html",
        {
            "q": q,
            "page": threads,
            "communities": communities,
            "users": users,
            "votes": _thread_votes(request.user, threads.object_list) if threads else {},
        },
    )


def guidelines(request):
    return render(request, "forum/guidelines.html")


# ---------------------------------------------------------------------------
# Communities
# ---------------------------------------------------------------------------


def community_list(request):
    return render(
        request,
        "forum/community_list.html",
        {"communities": Community.objects.order_by("-member_count", "name"), "joined_ids": _joined_ids(request.user)},
    )


@login_required
@ratelimit("community", 3, 86400)
def community_create(request):
    form = CommunityForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        community = form.save(commit=False)
        community.slug = slugify(community.name)
        community.created_by = request.user
        community.member_count = 1
        community.save()
        community.moderators.add(request.user)
        Membership.objects.create(user=request.user, community=community)
        messages.success(request, f"c/{community.slug} is live! Start the first thread.")
        return redirect(community)
    return render(request, "forum/community_form.html", {"form": form})


def community_detail(request, slug):
    community = get_object_or_404(Community, slug=slug)
    sort = _sort(request, THREAD_SORTS, "hot")
    threads = community.threads.select_related("author", "community").order_by("-is_pinned", *THREAD_SORTS[sort])
    page = _page(request, threads)
    context = {
        "community": community,
        "page": page,
        "sort": sort,
        "sort_options": THREAD_SORT_OPTIONS,
        "votes": _thread_votes(request.user, page.object_list),
        "joined_ids": _joined_ids(request.user),
        "is_mod": community.is_moderator(request.user),
        "moderators": community.moderators.filter(is_active=True),
    }
    return render(request, "forum/community_detail.html", context)


@login_required
def community_edit(request, slug):
    community = get_object_or_404(Community, slug=slug)
    if not community.is_moderator(request.user):
        raise PermissionDenied
    form = CommunityForm(request.POST or None, instance=community)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Community updated.")
        return redirect(community)
    return render(request, "forum/community_form.html", {"form": form, "community": community})


@login_required
@require_POST
def community_join(request, slug):
    community = get_object_or_404(Community, slug=slug)
    try:
        with transaction.atomic():
            Membership.objects.create(user=request.user, community=community)
            Community.objects.filter(pk=community.pk).update(member_count=F("member_count") + 1)
        messages.success(request, f"You joined c/{community.slug}.")
    except IntegrityError:
        pass
    return safe_next(request, community.get_absolute_url())


@login_required
@require_POST
def community_leave(request, slug):
    community = get_object_or_404(Community, slug=slug)
    with transaction.atomic():
        deleted, _ = Membership.objects.filter(user=request.user, community=community).delete()
        if deleted:
            Community.objects.filter(pk=community.pk, member_count__gt=0).update(member_count=F("member_count") - 1)
    if deleted:
        messages.info(request, f"You left c/{community.slug}.")
    return safe_next(request, community.get_absolute_url())


# ---------------------------------------------------------------------------
# Threads
# ---------------------------------------------------------------------------


@login_required
@ratelimit("thread", 5, 600)
def thread_create(request, slug=None):
    community = get_object_or_404(Community, slug=slug) if slug else None
    initial = {}
    if community is None and request.GET.get("community"):
        initial["community"] = Community.objects.filter(slug=request.GET["community"]).first()
    form = ThreadForm(request.POST or None, community=community, initial=initial)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            thread = form.save(commit=False)
            if community is not None:
                thread.community = community
            thread.author = request.user
            thread.score = 1
            thread.save()
            ThreadVote.objects.create(user=request.user, thread=thread, value=1)
        return redirect(thread)
    return render(request, "forum/thread_form.html", {"form": form, "community": community})


def thread_detail(request, slug, pk, thread_slug=None):
    thread = get_object_or_404(Thread.objects.select_related("author", "community"), pk=pk)
    if slug != thread.community.slug or thread_slug != thread.slug:
        return redirect(thread, permanent=True)

    csort = _sort(request, COMMENT_SORTS, "best")
    comments = list(thread.comments.select_related("author").order_by(*COMMENT_SORTS[csort]))
    children = defaultdict(list)
    for c in comments:
        children[c.parent_id].append(c)
    for c in comments:
        c.children = children.get(c.pk, [])

    comment_votes = {}
    if request.user.is_authenticated and comments:
        comment_votes = dict(
            CommentVote.objects.filter(user=request.user, comment__thread=thread).values_list("comment_id", "value")
        )

    context = {
        "thread": thread,
        "community": thread.community,
        "comments": children.get(None, []),
        "csort": csort,
        "comment_sort_options": COMMENT_SORT_OPTIONS,
        "votes": _thread_votes(request.user, [thread]),
        "comment_votes": comment_votes,
        "form": CommentForm(),
        "is_mod": thread.community.is_moderator(request.user),
        "joined_ids": _joined_ids(request.user),
    }
    if request.headers.get("x-quick-view") == "1" or request.GET.get("drawer") == "1":
        return render(request, "forum/_thread_drawer.html", context)
    return render(request, "forum/thread_detail.html", context)


@login_required
def thread_edit(request, pk):
    thread = get_object_or_404(Thread.objects.select_related("community"), pk=pk)
    if thread.author_id != request.user.pk:
        raise PermissionDenied
    form = ThreadEditForm(request.POST or None, instance=thread)
    if request.method == "POST" and form.is_valid():
        thread = form.save(commit=False)
        thread.edited_at = timezone.now()
        thread.save()
        messages.success(request, "Thread updated.")
        return redirect(thread)
    return render(request, "forum/thread_edit.html", {"form": form, "thread": thread})


@login_required
@require_POST
def thread_delete(request, pk):
    thread = get_object_or_404(Thread.objects.select_related("community"), pk=pk)
    if thread.author_id != request.user.pk and not thread.community.is_moderator(request.user):
        raise PermissionDenied
    community = thread.community
    thread.delete()
    messages.info(request, "Thread deleted.")
    return redirect(community)


@login_required
@require_POST
def thread_moderate(request, pk, action):
    thread = get_object_or_404(Thread.objects.select_related("community"), pk=pk)
    if not thread.community.is_moderator(request.user):
        raise PermissionDenied
    if action == "pin":
        thread.is_pinned = not thread.is_pinned
        messages.info(request, "Thread pinned." if thread.is_pinned else "Thread unpinned.")
    elif action == "lock":
        thread.is_locked = not thread.is_locked
        messages.info(request, "Thread locked." if thread.is_locked else "Thread unlocked.")
    thread.save(update_fields=["is_pinned", "is_locked"])
    return redirect(thread)


@login_required
@require_POST
@ratelimit("vote", 120, 60)
def thread_vote(request, pk):
    thread = get_object_or_404(Thread.objects.select_related("community"), pk=pk)
    new = _apply_vote(ThreadVote, Thread, request.user, thread, "thread", request.POST.get("value"))
    thread.refresh_rank()
    if _is_ajax(request):
        return JsonResponse({"score": thread.score, "vote": new})
    return safe_next(request, thread.get_absolute_url())


def _apply_vote(vote_model, target_model, user, obj, field, raw_value):
    """Toggle/flip a vote and keep the denormalised score in sync. Returns the user's new vote."""
    try:
        requested = int(raw_value)
    except (TypeError, ValueError):
        requested = 0
    if requested not in (1, -1):
        requested = 0
    with transaction.atomic():
        existing = vote_model.objects.select_for_update().filter(user=user, **{field: obj}).first()
        old = existing.value if existing else 0
        new = 0 if requested == old else requested
        if new == 0 and existing:
            existing.delete()
        elif new and existing:
            existing.value = new
            existing.save(update_fields=["value"])
        elif new:
            vote_model.objects.create(user=user, value=new, **{field: obj})
        if new != old:
            target_model.objects.filter(pk=obj.pk).update(score=F("score") + (new - old))
    obj.refresh_from_db(fields=["score"])
    return new


# ---------------------------------------------------------------------------
# Comments
# ---------------------------------------------------------------------------


@login_required
@require_POST
@ratelimit("comment", 20, 300)
def comment_create(request, pk):
    thread = get_object_or_404(Thread.objects.select_related("community"), pk=pk)
    if thread.is_locked:
        messages.error(request, "This thread is locked — new comments are disabled.")
        return redirect(thread)
    form = CommentForm(request.POST)
    if not form.is_valid():
        for errors in form.errors.values():
            for e in errors:
                messages.error(request, e)
        return redirect(thread)

    parent = None
    parent_id = form.cleaned_data.get("parent")
    if parent_id:
        parent = get_object_or_404(Comment, pk=parent_id, thread=thread)
        if not parent.can_reply:
            messages.error(request, "You can't reply to that comment.")
            return redirect(thread)

    with transaction.atomic():
        comment = form.save(commit=False)
        comment.thread = thread
        comment.author = request.user
        comment.parent = parent
        comment.depth = parent.depth + 1 if parent else 0
        comment.score = 1
        comment.save()
        CommentVote.objects.create(user=request.user, comment=comment, value=1)
        Thread.objects.filter(pk=thread.pk).update(comment_count=F("comment_count") + 1)
    if request.headers.get("x-live-action") == "1":
        return JsonResponse({"ok": True, "comment_id": comment.pk})
    if request.headers.get("x-quick-view") == "1":
        return redirect(f"{thread.get_absolute_url()}?drawer=1")
    return redirect(f"{thread.get_absolute_url()}#c{comment.pk}")


@login_required
def comment_edit(request, pk):
    comment = get_object_or_404(Comment.objects.select_related("thread__community"), pk=pk, is_deleted=False)
    if comment.author_id != request.user.pk:
        raise PermissionDenied
    form = CommentForm(request.POST or None, instance=comment)
    if request.method == "POST" and form.is_valid():
        comment = form.save(commit=False)
        comment.edited_at = timezone.now()
        comment.save()
        messages.success(request, "Comment updated.")
        return redirect(comment.get_absolute_url())
    return render(request, "forum/comment_edit.html", {"form": form, "comment": comment})


@login_required
@require_POST
def comment_delete(request, pk):
    comment = get_object_or_404(Comment.objects.select_related("thread__community"), pk=pk)
    if comment.author_id != request.user.pk and not comment.thread.community.is_moderator(request.user):
        raise PermissionDenied
    # Soft delete keeps reply chains readable.
    comment.is_deleted = True
    comment.body = ""
    comment.save(update_fields=["is_deleted", "body"])
    if request.headers.get("x-live-action") == "1":
        return JsonResponse({"ok": True, "toast": "Comment deleted."})
    messages.info(request, "Comment deleted.")
    return redirect(comment.get_absolute_url())


@login_required
@require_POST
@ratelimit("vote", 120, 60)
def comment_vote(request, pk):
    comment = get_object_or_404(Comment.objects.select_related("thread__community"), pk=pk, is_deleted=False)
    new = _apply_vote(CommentVote, Comment, request.user, comment, "comment", request.POST.get("value"))
    if _is_ajax(request):
        return JsonResponse({"score": comment.score, "vote": new})
    return safe_next(request, comment.get_absolute_url())


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------


@login_required
@ratelimit("report", 10, 3600)
def report(request, kind, pk):
    if kind == "thread":
        target = get_object_or_404(Thread.objects.select_related("community"), pk=pk)
        back = target.get_absolute_url()
    else:
        target = get_object_or_404(Comment.objects.select_related("thread__community"), pk=pk, is_deleted=False)
        back = target.get_absolute_url()
    form = ReportForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        r = form.save(commit=False)
        r.reporter = request.user
        setattr(r, kind, target)
        r.save()
        messages.success(request, "Thanks — the moderators will take a look.")
        return redirect(back)
    return render(request, "forum/report_form.html", {"form": form, "target": target, "kind": kind, "back": back})
