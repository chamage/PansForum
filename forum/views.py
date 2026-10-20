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
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from pans_agora.utils import ratelimit, safe_next

from .forms import CommentForm, CommunityForm, ReportForm, ThreadEditForm, ThreadForm
from .models import Comment, CommentVote, Community, CommunitySanction, Membership, Report, Thread, ThreadVote

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


def _banned_community_ids(user):
    if not user.is_authenticated or user.is_staff:
        return set()
    return set(
        CommunitySanction.objects.filter(user=user, kind=CommunitySanction.Kind.BAN)
        .exclude(community__moderators=user)
        .values_list("community_id", flat=True)
    )


def _render_banned(request, community, sanction=None):
    return render(
        request,
        "forum/community_banned.html",
        {
            "community": community,
            "sanction": sanction,
            "is_drawer": request.headers.get("x-quick-view") == "1" or request.GET.get("drawer") == "1",
        },
        status=403,
    )


def _is_ajax(request):
    return request.headers.get("x-requested-with") == "XMLHttpRequest"


# ---------------------------------------------------------------------------
# Feeds
# ---------------------------------------------------------------------------


def home(request):
    sort = _sort(request, THREAD_SORTS, "hot")
    joined = _joined_ids(request.user)
    banned = _banned_community_ids(request.user)
    joined -= banned
    feed = "all" if request.GET.get("feed") == "all" or not joined else "mine"

    threads = Thread.objects.select_related("author", "community")
    if banned:
        threads = threads.exclude(community_id__in=banned)
    if feed == "mine":
        threads = threads.filter(community_id__in=joined)
    page = _page(request, threads.order_by(*THREAD_SORTS[sort]))

    popular_qs = Community.objects.order_by("-member_count", "name")
    if banned:
        popular_qs = popular_qs.exclude(pk__in=banned)

    context = {
        "page": page,
        "sort": sort,
        "sort_options": THREAD_SORT_OPTIONS,
        "feed": feed,
        "has_joined": bool(joined),
        "votes": _thread_votes(request.user, page.object_list),
        "popular": popular_qs[:8],
        "joined_ids": joined,
    }
    return render(request, "forum/home.html", context)


def search(request):
    q = " ".join(request.GET.get("q", "").split())[:100]
    banned = _banned_community_ids(request.user)
    threads = communities = users = None
    if len(q) >= 2:
        threads = (
            Thread.objects.filter(Q(title__icontains=q) | Q(body__icontains=q))
            .select_related("author", "community")
            .order_by("-hot_rank")
        )
        if banned:
            threads = threads.exclude(community_id__in=banned)
        communities = Community.objects.filter(Q(name__icontains=q) | Q(description__icontains=q))
        if banned:
            communities = communities.exclude(pk__in=banned)
        communities = communities[:6]
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
    banned = _banned_community_ids(request.user)
    qs = Community.objects.order_by("-member_count", "name")
    if banned:
        qs = qs.exclude(pk__in=banned)
    return render(
        request,
        "forum/community_list.html",
        {"communities": qs, "joined_ids": _joined_ids(request.user) - banned},
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
    sanction = community.get_sanction(request.user)
    if sanction and sanction.kind == CommunitySanction.Kind.BAN:
        return _render_banned(request, community, sanction)

    is_mod = community.is_moderator(request.user)
    is_ghosted = bool(sanction and sanction.kind == CommunitySanction.Kind.GHOST)
    sort = _sort(request, THREAD_SORTS, "hot")
    threads = community.threads.select_related("author", "community").order_by("-is_pinned", *THREAD_SORTS[sort])
    page = _page(request, threads)
    open_reports_count = 0
    if is_mod:
        open_reports_count = (
            Report.objects.filter(resolved=False)
            .filter(Q(thread__community=community) | Q(comment__thread__community=community))
            .count()
        )
    context = {
        "community": community,
        "page": page,
        "sort": sort,
        "sort_options": THREAD_SORT_OPTIONS,
        "votes": _thread_votes(request.user, page.object_list),
        "joined_ids": _joined_ids(request.user),
        "is_mod": is_mod,
        "is_ghosted": is_ghosted,
        "sanction": sanction,
        "open_reports_count": open_reports_count,
        "moderators": community.moderators.filter(is_active=True),
    }
    return render(request, "forum/community_detail.html", context)


@login_required
def community_manage(request, slug):
    community = get_object_or_404(Community, slug=slug)
    if not community.is_moderator(request.user):
        raise PermissionDenied
    form = CommunityForm(request.POST or None, instance=community)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Community details updated.")
        return redirect("forum:community_manage", slug=community.slug)

    moderators = list(community.moderators.filter(is_active=True).order_by("username"))
    bans = list(
        community.sanctions.filter(kind=CommunitySanction.Kind.BAN).select_related("user", "created_by")
    )
    ghosts = list(
        community.sanctions.filter(kind=CommunitySanction.Kind.GHOST).select_related("user", "created_by")
    )
    reports = list(
        Report.objects.filter(resolved=False)
        .filter(Q(thread__community=community) | Q(comment__thread__community=community))
        .select_related("reporter", "thread", "comment", "thread__author", "comment__author", "comment__thread")[:50]
    )
    return render(
        request,
        "forum/community_manage.html",
        {
            "form": form,
            "community": community,
            "moderators": moderators,
            "bans": bans,
            "ghosts": ghosts,
            "reports": reports,
        },
    )


community_edit = community_manage


@login_required
@require_POST
def community_mod_add(request, slug):
    community = get_object_or_404(Community, slug=slug)
    if not community.is_moderator(request.user):
        raise PermissionDenied
    username = request.POST.get("username", "").strip().lstrip("@")
    User = get_user_model()
    target = User.objects.filter(username__iexact=username, is_active=True).first()
    if not target:
        err = f"Could not find an active user named '{username}'."
        if request.headers.get("x-live-action") == "1":
            return JsonResponse({"ok": False, "error": err}, status=400)
        messages.error(request, err)
        return safe_next(request, reverse("forum:community_manage", args=[community.slug]))

    with transaction.atomic():
        community.moderators.add(target)
        CommunitySanction.objects.filter(community=community, user=target).delete()
        _, created = Membership.objects.get_or_create(user=target, community=community)
        if created:
            Community.objects.filter(pk=community.pk).update(member_count=F("member_count") + 1)
    toast = f"@{target.username} is now a moderator of c/{community.slug}."
    if request.headers.get("x-live-action") == "1":
        return JsonResponse({"ok": True, "toast": toast})
    messages.success(request, toast)
    return safe_next(request, reverse("forum:community_manage", args=[community.slug]))


@login_required
@require_POST
def community_mod_remove(request, slug, username):
    community = get_object_or_404(Community, slug=slug)
    if not community.is_moderator(request.user):
        raise PermissionDenied
    User = get_user_model()
    target = get_object_or_404(User, username__iexact=username)
    if community.created_by_id == target.pk:
        err = "The community founder cannot be removed from the moderator team."
        if request.headers.get("x-live-action") == "1":
            return JsonResponse({"ok": False, "error": err}, status=400)
        messages.error(request, err)
        return safe_next(request, reverse("forum:community_manage", args=[community.slug]))

    community.moderators.remove(target)
    toast = f"@{target.username} was removed from the moderator team."
    if target.pk == request.user.pk and not request.user.is_staff:
        if request.headers.get("x-live-action") == "1":
            return JsonResponse({"ok": True, "redirect": community.get_absolute_url()})
        messages.info(request, toast)
        return redirect(community)
    if request.headers.get("x-live-action") == "1":
        return JsonResponse({"ok": True, "toast": toast})
    messages.info(request, toast)
    return safe_next(request, reverse("forum:community_manage", args=[community.slug]))


@login_required
@require_POST
def community_sanction_set(request, slug):
    community = get_object_or_404(Community, slug=slug)
    if not community.is_moderator(request.user):
        raise PermissionDenied
    username = request.POST.get("username", "").strip().lstrip("@")
    kind = request.POST.get("kind", "").strip()
    reason = " ".join(request.POST.get("reason", "").split())[:240]

    if kind not in (CommunitySanction.Kind.BAN, CommunitySanction.Kind.GHOST):
        if request.headers.get("x-live-action") == "1":
            return JsonResponse({"ok": False, "error": "Choose either Ban or Ghost."}, status=400)
        messages.error(request, "Choose either Ban or Ghost.")
        return safe_next(request, reverse("forum:community_manage", args=[community.slug]))

    User = get_user_model()
    target = User.objects.filter(username__iexact=username, is_active=True).first()
    if not target:
        err = f"Could not find an active user named '{username}'."
        if request.headers.get("x-live-action") == "1":
            return JsonResponse({"ok": False, "error": err}, status=400)
        messages.error(request, err)
        return safe_next(request, reverse("forum:community_manage", args=[community.slug]))

    if target.pk == request.user.pk or target.pk == community.created_by_id or community.is_moderator(target):
        err = "Moderators and the community founder cannot be banned or ghosted."
        if request.headers.get("x-live-action") == "1":
            return JsonResponse({"ok": False, "error": err}, status=400)
        messages.error(request, err)
        return safe_next(request, reverse("forum:community_manage", args=[community.slug]))

    with transaction.atomic():
        CommunitySanction.objects.update_or_create(
            community=community,
            user=target,
            defaults={"kind": kind, "reason": reason, "created_by": request.user},
        )
        if kind == CommunitySanction.Kind.BAN:
            deleted, _ = Membership.objects.filter(user=target, community=community).delete()
            if deleted:
                Community.objects.filter(pk=community.pk, member_count__gt=0).update(
                    member_count=F("member_count") - 1
                )

    toast = (
        f"@{target.username} has been banned from c/{community.slug}."
        if kind == CommunitySanction.Kind.BAN
        else f"@{target.username} has been ghosted in c/{community.slug}."
    )
    if request.headers.get("x-live-action") == "1":
        return JsonResponse({"ok": True, "toast": toast})
    messages.info(request, toast)
    return safe_next(request, reverse("forum:community_manage", args=[community.slug]))


@login_required
@require_POST
def community_sanction_remove(request, slug, username):
    community = get_object_or_404(Community, slug=slug)
    if not community.is_moderator(request.user):
        raise PermissionDenied
    User = get_user_model()
    target = get_object_or_404(User, username__iexact=username)
    deleted, _ = CommunitySanction.objects.filter(community=community, user=target).delete()
    toast = f"Restrictions lifted for @{target.username} in c/{community.slug}."
    if request.headers.get("x-live-action") == "1":
        return JsonResponse({"ok": True, "toast": toast if deleted else ""})
    if deleted:
        messages.success(request, toast)
    return safe_next(request, reverse("forum:community_manage", args=[community.slug]))


@login_required
@require_POST
def community_report_resolve(request, slug, pk):
    community = get_object_or_404(Community, slug=slug)
    if not community.is_moderator(request.user):
        raise PermissionDenied
    rep = get_object_or_404(
        Report.objects.select_related("thread", "comment", "comment__thread"),
        pk=pk,
    )
    rep_comm_id = rep.thread.community_id if rep.thread_id else (rep.comment.thread.community_id if rep.comment_id else None)
    if rep_comm_id != community.pk:
        raise PermissionDenied

    if request.POST.get("delete_content") == "1":
        if rep.thread_id and rep.thread:
            rep.thread.delete()
            toast = "Reported thread deleted and report resolved."
            if request.headers.get("x-live-action") == "1":
                return JsonResponse({"ok": True, "toast": toast})
            messages.info(request, toast)
            return safe_next(request, reverse("forum:community_manage", args=[community.slug]))
        elif rep.comment_id and rep.comment:
            rep.comment.is_deleted = True
            rep.comment.body = ""
            rep.comment.save(update_fields=["is_deleted", "body"])
            rep.resolved = True
            rep.save(update_fields=["resolved"])
            toast = "Reported comment deleted and report resolved."
            if request.headers.get("x-live-action") == "1":
                return JsonResponse({"ok": True, "toast": toast})
            messages.info(request, toast)
            return safe_next(request, reverse("forum:community_manage", args=[community.slug]))

    rep.resolved = True
    rep.save(update_fields=["resolved"])
    toast = "Report marked as resolved."
    if request.headers.get("x-live-action") == "1":
        return JsonResponse({"ok": True, "toast": toast})
    messages.success(request, toast)
    return safe_next(request, reverse("forum:community_manage", args=[community.slug]))


@login_required
@require_POST
def community_join(request, slug):
    community = get_object_or_404(Community, slug=slug)
    sanction = community.get_sanction(request.user)
    if sanction and sanction.kind == CommunitySanction.Kind.BAN:
        if request.headers.get("x-live-action") == "1":
            return JsonResponse({"ok": False, "error": f"You are banned from c/{community.slug}."}, status=403)
        return _render_banned(request, community, sanction)
    if sanction and sanction.kind == CommunitySanction.Kind.GHOST:
        err = f"You are in read-only mode in c/{community.slug} and cannot join."
        if request.headers.get("x-live-action") == "1":
            return JsonResponse({"ok": False, "error": err}, status=403)
        messages.error(request, err)
        return safe_next(request, community.get_absolute_url())
    try:
        with transaction.atomic():
            Membership.objects.create(user=request.user, community=community)
            Community.objects.filter(pk=community.pk).update(member_count=F("member_count") + 1)
        if request.headers.get("x-live-action") != "1":
            messages.success(request, f"You joined c/{community.slug}.")
    except IntegrityError:
        pass
    if request.headers.get("x-live-action") == "1":
        community.refresh_from_db(fields=["member_count"])
        join_html = render_to_string(
            "forum/_join_button.html",
            {"community": community, "joined_ids": {community.pk}, "user": request.user},
            request=request,
        )
        return JsonResponse(
            {
                "ok": True,
                "slug": community.slug,
                "member_count": community.member_count,
                "join_html": join_html,
            }
        )
    return safe_next(request, community.get_absolute_url())


@login_required
@require_POST
def community_leave(request, slug):
    community = get_object_or_404(Community, slug=slug)
    with transaction.atomic():
        deleted, _ = Membership.objects.filter(user=request.user, community=community).delete()
        if deleted:
            Community.objects.filter(pk=community.pk, member_count__gt=0).update(member_count=F("member_count") - 1)
    if request.headers.get("x-live-action") == "1":
        community.refresh_from_db(fields=["member_count"])
        join_html = render_to_string(
            "forum/_join_button.html",
            {"community": community, "joined_ids": set(), "user": request.user},
            request=request,
        )
        return JsonResponse(
            {
                "ok": True,
                "slug": community.slug,
                "member_count": community.member_count,
                "join_html": join_html,
            }
        )
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
    if community is not None:
        sanction = community.get_sanction(request.user)
        if sanction and sanction.kind == CommunitySanction.Kind.BAN:
            return _render_banned(request, community, sanction)
        if sanction and sanction.kind == CommunitySanction.Kind.GHOST:
            messages.error(request, f"You are in read-only mode in c/{community.slug} and cannot create threads.")
            return redirect(community)

    initial = {}
    if community is None and request.GET.get("community"):
        initial["community"] = Community.objects.filter(slug=request.GET["community"]).first()
    form = ThreadForm(request.POST or None, community=community, user=request.user, initial=initial)
    if request.method == "POST" and form.is_valid():
        target_community = community if community is not None else form.cleaned_data.get("community")
        if target_community is not None and target_community.get_sanction(request.user) is not None:
            messages.error(request, f"You cannot post in c/{target_community.slug}.")
            return redirect(target_community)
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

    sanction = thread.community.get_sanction(request.user)
    if sanction and sanction.kind == CommunitySanction.Kind.BAN:
        return _render_banned(request, thread.community, sanction)

    is_mod = thread.community.is_moderator(request.user)
    is_ghosted = bool(sanction and sanction.kind == CommunitySanction.Kind.GHOST)

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

    sanctioned_map = {}
    mod_ids = set()
    if is_mod:
        sanctioned_map = dict(
            thread.community.sanctions.values_list("user_id", "kind")
        )
        mod_ids = set(thread.community.moderators.values_list("id", flat=True))
        if thread.community.created_by_id:
            mod_ids.add(thread.community.created_by_id)

    context = {
        "thread": thread,
        "community": thread.community,
        "comments": children.get(None, []),
        "csort": csort,
        "comment_sort_options": COMMENT_SORT_OPTIONS,
        "votes": _thread_votes(request.user, [thread]),
        "comment_votes": comment_votes,
        "form": CommentForm(),
        "is_mod": is_mod,
        "is_ghosted": is_ghosted,
        "sanction": sanction,
        "sanctioned_map": sanctioned_map,
        "mod_ids": mod_ids,
        "joined_ids": _joined_ids(request.user),
    }
    if request.headers.get("x-quick-view") == "1" or request.GET.get("drawer") == "1":
        return render(request, "forum/_thread_drawer.html", context)
    return render(request, "forum/thread_detail.html", context)


@login_required
def thread_edit(request, pk):
    thread = get_object_or_404(Thread.objects.select_related("community"), pk=pk)
    if thread.author_id != request.user.pk or thread.community.get_sanction(request.user) is not None:
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
    is_mod = thread.community.is_moderator(request.user)
    if not is_mod and (thread.author_id != request.user.pk or thread.community.is_banned(request.user)):
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
    toast = ""
    if action == "pin":
        thread.is_pinned = not thread.is_pinned
        toast = "Thread pinned." if thread.is_pinned else "Thread unpinned."
    elif action == "lock":
        thread.is_locked = not thread.is_locked
        toast = "Thread locked." if thread.is_locked else "Thread unlocked."
    thread.save(update_fields=["is_pinned", "is_locked"])
    if request.headers.get("x-live-action") == "1":
        return JsonResponse(
            {
                "ok": True,
                "toast": toast,
                "thread_id": thread.pk,
                "is_pinned": thread.is_pinned,
                "is_locked": thread.is_locked,
            }
        )
    if toast:
        messages.info(request, toast)
    return redirect(thread)


@login_required
@require_POST
@ratelimit("vote", 120, 60)
def thread_vote(request, pk):
    thread = get_object_or_404(Thread.objects.select_related("community"), pk=pk)
    if thread.community.get_sanction(request.user) is not None:
        if _is_ajax(request):
            return JsonResponse({"error": "You cannot vote in this community."}, status=403)
        messages.error(request, "You cannot vote in this community.")
        return safe_next(request, thread.get_absolute_url())
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
    sanction = thread.community.get_sanction(request.user)
    if sanction is not None:
        msg = (
            f"You are banned from c/{thread.community.slug}."
            if sanction.kind == CommunitySanction.Kind.BAN
            else f"You are in read-only mode in c/{thread.community.slug} and cannot comment."
        )
        if request.headers.get("x-live-action") == "1":
            return JsonResponse({"ok": False, "error": msg}, status=403)
        messages.error(request, msg)
        return redirect(thread)
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
    if comment.author_id != request.user.pk or comment.thread.community.get_sanction(request.user) is not None:
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
    is_mod = comment.thread.community.is_moderator(request.user)
    if not is_mod and (comment.author_id != request.user.pk or comment.thread.community.is_banned(request.user)):
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
    if comment.thread.community.get_sanction(request.user) is not None:
        if _is_ajax(request):
            return JsonResponse({"error": "You cannot vote in this community."}, status=403)
        messages.error(request, "You cannot vote in this community.")
        return safe_next(request, comment.get_absolute_url())
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
