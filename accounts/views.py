from collections import defaultdict

from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Count, Max, Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_POST

from forum.models import Comment, CommentVote, Community, CommunitySanction, Membership, Report, Thread, ThreadVote
from forum.templatetags.forum_extras import render_body
from pans_agora.utils import ratelimit, safe_next

from .forms import (
    DeleteAccountForm,
    DirectMessageForm,
    EmailChangeForm,
    LoginForm,
    ProfileForm,
    RegistrationForm,
)
from .models import Conversation, DirectMessage, FriendRequest, User, relationship

# ---------------------------------------------------------------------------
# Registration & authentication
# ---------------------------------------------------------------------------


@ratelimit("register", 10, 3600, by_user=False)
def register(request):
    if request.user.is_authenticated:
        return redirect("forum:home")
    form = RegistrationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user, backend="accounts.backends.UsernameOrEmailBackend")
        messages.success(request, f"Welcome to the Agora, {user.username}! Join a few communities to fill your feed.")
        return redirect("forum:community_list")
    return render(request, "accounts/register.html", {"form": form})


@method_decorator(ratelimit("login", 15, 600, by_user=False), name="dispatch")
class LoginView(auth_views.LoginView):
    template_name = "accounts/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True


class LogoutView(auth_views.LogoutView):
    pass


@method_decorator(ratelimit("password_reset", 5, 3600, by_user=False), name="dispatch")
class PasswordResetView(auth_views.PasswordResetView):
    template_name = "registration/password_reset_form.html"
    email_template_name = "registration/password_reset_email.txt"
    subject_template_name = "registration/password_reset_subject.txt"
    success_url = reverse_lazy("accounts:password_reset_done")


class PasswordResetConfirmView(auth_views.PasswordResetConfirmView):
    template_name = "registration/password_reset_confirm.html"
    success_url = reverse_lazy("accounts:password_reset_complete")


class PasswordChangeView(auth_views.PasswordChangeView):
    template_name = "accounts/settings_password.html"
    success_url = reverse_lazy("accounts:settings_password")

    def form_valid(self, form):
        messages.success(self.request, "Your password has been changed.")
        return super().form_valid(form)


# ---------------------------------------------------------------------------
# Profiles
# ---------------------------------------------------------------------------


def profile(request, username):
    profile_user = get_object_or_404(User, username__iexact=username, is_active=True)
    if profile_user.username != username:
        return redirect(profile_user)

    tab = request.GET.get("tab", "threads")
    if tab == "comments":
        items = (
            Comment.objects.filter(author=profile_user, is_deleted=False)
            .select_related("thread__community")
            .order_by("-created_at")
        )
    elif tab == "friends":
        items = profile_user.friends().order_by("username")
    else:
        tab = "threads"
        items = Thread.objects.filter(author=profile_user).select_related("community", "author").order_by("-created_at")

    state, friend_request = relationship(request.user, profile_user)
    context = {
        "profile_user": profile_user,
        "tab": tab,
        "page": Paginator(items, 20).get_page(request.GET.get("page")),
        "rel": state,
        "friend_request": friend_request,
        "stats": {
            "threads": Thread.objects.filter(author=profile_user).count(),
            "comments": Comment.objects.filter(author=profile_user, is_deleted=False).count(),
            "friends": len(profile_user.friend_ids()),
        },
        "votes": {},
    }
    return render(request, "accounts/profile.html", context)


def _cleanup_file(old_name, field_file):
    if old_name and old_name != field_file.name:
        field_file.storage.delete(old_name)


@login_required
def settings_profile(request):
    # Work on a fresh copy so a failed form never mutates request.user.
    user = User.objects.get(pk=request.user.pk)
    old_avatar, old_banner = user.avatar.name, user.banner.name
    if request.method == "POST":
        form = ProfileForm(request.POST, request.FILES, instance=user)
        if form.is_valid():
            user = form.save()
            _cleanup_file(old_avatar, user.avatar)
            _cleanup_file(old_banner, user.banner)
            messages.success(request, "Profile updated.")
            return redirect("accounts:settings_profile")
    else:
        form = ProfileForm(instance=user)
    return render(request, "accounts/settings_profile.html", {"form": form, "section": "profile", "preview_user": request.user})


@login_required
def settings_account(request):
    form = EmailChangeForm(request.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        request.user.email = form.cleaned_data["email"]
        request.user.save(update_fields=["email"])
        messages.success(request, "Email address updated.")
        return redirect("accounts:settings_account")
    return render(request, "accounts/settings_account.html", {"form": form, "section": "account"})


@login_required
def settings_delete(request):
    form = DeleteAccountForm(request.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = request.user
        avatar, banner = user.avatar, user.banner
        logout(request)
        for f in (avatar, banner):
            if f:
                f.storage.delete(f.name)
        user.delete()
        messages.info(request, "Your account has been deleted. Take care!")
        return redirect("forum:home")
    return render(request, "accounts/settings_delete.html", {"form": form, "section": "delete"})


# ---------------------------------------------------------------------------
# Friends
# ---------------------------------------------------------------------------


@login_required
def friends(request):
    incoming = FriendRequest.objects.filter(to_user=request.user, status=FriendRequest.Status.PENDING).select_related("from_user")
    outgoing = FriendRequest.objects.filter(from_user=request.user, status=FriendRequest.Status.PENDING).select_related("to_user")
    context = {
        "incoming": incoming,
        "outgoing": outgoing,
        "friend_list": request.user.friends().order_by("username"),
    }
    return render(request, "accounts/friends.html", context)


def _target(username):
    return get_object_or_404(User, username__iexact=username, is_active=True)


def _is_live(request):
    return request.headers.get("x-live-action") == "1"


@login_required
@require_POST
@ratelimit("friend", 30, 3600)
def friend_add(request, username):
    other = _target(username)
    state, fr = relationship(request.user, other)
    toast = ""
    if state == "self":
        toast = "You can't send a friend request to yourself."
        if not _is_live(request):
            messages.error(request, toast)
    elif state == "none":
        try:
            with transaction.atomic():
                FriendRequest.objects.create(from_user=request.user, to_user=other)
            toast = f"Friend request sent to {other.name}."
            if not _is_live(request):
                messages.success(request, toast)
        except IntegrityError:
            toast = "A friend request already exists."
            if not _is_live(request):
                messages.info(request, toast)
    elif state == "incoming":
        fr.accept()
        toast = f"You and {other.name} are now friends."
        if not _is_live(request):
            messages.success(request, toast)
    elif state == "friends":
        toast = f"You're already friends with {other.name}."
        if not _is_live(request):
            messages.info(request, toast)
    else:
        toast = "Your friend request is still pending."
        if not _is_live(request):
            messages.info(request, toast)
    if _is_live(request):
        return JsonResponse({"ok": True, "toast": toast})
    return safe_next(request, other.get_absolute_url())


@login_required
@require_POST
def friend_cancel(request, username):
    other = _target(username)
    FriendRequest.objects.filter(from_user=request.user, to_user=other, status=FriendRequest.Status.PENDING).delete()
    if _is_live(request):
        return JsonResponse({"ok": True, "toast": "Friend request cancelled."})
    messages.info(request, "Friend request cancelled.")
    return safe_next(request, other.get_absolute_url())


@login_required
@require_POST
def friend_remove(request, username):
    other = _target(username)
    FriendRequest.objects.filter(
        Q(from_user=request.user, to_user=other) | Q(from_user=other, to_user=request.user),
        status=FriendRequest.Status.ACCEPTED,
    ).delete()
    if _is_live(request):
        return JsonResponse({"ok": True, "toast": f"{other.name} was removed from your friends."})
    messages.info(request, f"{other.name} was removed from your friends.")
    return safe_next(request, other.get_absolute_url())


@login_required
@require_POST
def friend_accept(request, pk):
    fr = get_object_or_404(FriendRequest, pk=pk, to_user=request.user, status=FriendRequest.Status.PENDING)
    fr.accept()
    if _is_live(request):
        return JsonResponse({"ok": True, "toast": f"You and {fr.from_user.name} are now friends."})
    messages.success(request, f"You and {fr.from_user.name} are now friends.")
    return safe_next(request, "accounts:friends")


@login_required
@require_POST
def friend_decline(request, pk):
    fr = get_object_or_404(FriendRequest, pk=pk, to_user=request.user, status=FriendRequest.Status.PENDING)
    fr.delete()
    if _is_live(request):
        return JsonResponse({"ok": True, "toast": "Friend request declined."})
    messages.info(request, "Friend request declined.")
    return safe_next(request, "accounts:friends")


# ---------------------------------------------------------------------------
# Direct Messages & Message Requests
# ---------------------------------------------------------------------------


def _build_conversation_lists(user):
    """Return (inbox_conversations, incoming_requests) decorated with partner & unread info."""
    friend_ids = user.friend_ids()
    convs = list(
        Conversation.objects.filter(Q(user1=user) | Q(user2=user))
        .select_related("user1", "user2", "initiated_by")
        .order_by("-updated_at")
    )
    inbox = []
    requests = []
    for conv in convs:
        partner = conv.other_participant(user)
        if not partner.is_active:
            continue
        if partner.pk in friend_ids and conv.status != Conversation.Status.ACTIVE:
            conv.status = Conversation.Status.ACTIVE
            Conversation.objects.filter(pk=conv.pk).update(status=Conversation.Status.ACTIVE)

        if conv.status == Conversation.Status.IGNORED and conv.initiated_by_id != user.pk:
            continue

        conv.partner = partner
        conv.is_friend = partner.pk in friend_ids
        conv.last_message = conv.messages.order_by("-created_at", "-pk").first()
        conv.unread_count = conv.messages.filter(is_read=False).exclude(sender=user).count()

        if conv.status == Conversation.Status.PENDING and conv.initiated_by_id != user.pk:
            requests.append(conv)
        else:
            inbox.append(conv)
    return inbox, requests


CHAT_GAP_SECONDS = 15 * 60  # 15-minute gap triggers a Messenger-style time separator


def _annotate_chat_separators(msgs, conv=None):
    if not msgs:
        return msgs
    prev_dt = None
    if conv is not None:
        prev_dt = (
            conv.messages.filter(pk__lt=msgs[0].pk)
            .order_by("-created_at", "-pk")
            .values_list("created_at", flat=True)
            .first()
        )
    for m in msgs:
        if prev_dt is None or (m.created_at - prev_dt).total_seconds() >= CHAT_GAP_SECONDS:
            m.show_time_sep = True
        else:
            m.show_time_sep = False
        prev_dt = m.created_at
    return msgs


def _chat_partner_flags(user, other):
    rel_state, _ = relationship(user, other)
    is_friends = rel_state == "friends"
    conv = Conversation.between(user, other)
    if conv and is_friends and conv.status != Conversation.Status.ACTIVE:
        conv.status = Conversation.Status.ACTIVE
        conv.save(update_fields=["status"])

    can_send = True
    waiting_for_response = False
    is_incoming_request = False
    is_ignored_by_me = False

    if conv:
        if conv.status == Conversation.Status.PENDING:
            if conv.initiated_by_id == user.pk:
                can_send = False
                waiting_for_response = True
            else:
                is_incoming_request = True
        elif conv.status == Conversation.Status.IGNORED:
            if conv.initiated_by_id == user.pk:
                can_send = False
                waiting_for_response = True
            else:
                is_ignored_by_me = True

    return {
        "rel_state": rel_state,
        "is_friends": is_friends,
        "conversation": conv,
        "can_send": can_send,
        "waiting_for_response": waiting_for_response,
        "is_incoming_request": is_incoming_request,
        "is_ignored_by_me": is_ignored_by_me,
    }


@login_required
def chat_inbox(request):
    inbox, requests = _build_conversation_lists(request.user)
    tab = "requests" if request.GET.get("tab") == "requests" else "inbox"
    return render(
        request,
        "accounts/chat.html",
        {
            "inbox": inbox,
            "requests": requests,
            "tab": tab,
            "active_partner": None,
            "conversation": None,
            "friends_without_chat": request.user.friends().order_by("username"),
        },
    )


@login_required
def chat_dock(request, username=None):
    """Render the Messenger/Reddit-style floating quick-chat popup (inbox list or active thread)."""
    inbox, requests_list = _build_conversation_lists(request.user)
    if username:
        other = _target(username)
        if other.pk == request.user.pk:
            return redirect("accounts:chat_dock")
        flags = _chat_partner_flags(request.user, other)
        conv = flags["conversation"]
        chat_messages = []
        if conv:
            conv.messages.filter(is_read=False).exclude(sender=request.user).update(is_read=True)
            chat_messages = _annotate_chat_separators(list(conv.messages.select_related("sender").all()), conv=None)
        tab = "requests" if flags["is_incoming_request"] else "inbox"
        return render(
            request,
            "accounts/_chat_dock.html",
            {
                "inbox": inbox,
                "requests": requests_list,
                "tab": tab,
                "active_partner": other,
                **flags,
                "chat_messages": chat_messages,
                "friends_without_chat": request.user.friends().order_by("username"),
            },
        )

    tab = "requests" if request.GET.get("tab") == "requests" else "inbox"
    return render(
        request,
        "accounts/_chat_dock.html",
        {
            "inbox": inbox,
            "requests": requests_list,
            "tab": tab,
            "active_partner": None,
            "conversation": None,
            "friends_without_chat": request.user.friends().order_by("username"),
        },
    )


@login_required
@ratelimit("chat", 60, 60)
def chat_thread(request, username):
    other = _target(username)
    if other.pk == request.user.pk:
        return redirect("accounts:chat_inbox")
    if other.username != username:
        return redirect("accounts:chat_thread", username=other.username)

    flags = _chat_partner_flags(request.user, other)
    conv = flags["conversation"]
    is_friends = flags["is_friends"]
    can_send = flags["can_send"]

    form = DirectMessageForm(request.POST or None, request.FILES or None)
    if request.method == "POST":
        if not can_send:
            err = f"Please wait for {other.name} to respond to your message request."
            if _is_live(request):
                return JsonResponse({"ok": False, "toast": err}, status=400)
            messages.error(request, err)
            return redirect("accounts:chat_thread", username=other.username)

        if request.FILES.get("attachment") and not is_friends:
            err = "Only friends can send media attachments."
            if _is_live(request):
                return JsonResponse({"ok": False, "toast": err}, status=400)
            messages.error(request, err)
            return redirect("accounts:chat_thread", username=other.username)

        if form.is_valid():
            now = timezone.now()
            with transaction.atomic():
                if conv is None:
                    u1, u2 = Conversation.pair_users(request.user, other)
                    conv = Conversation.objects.create(
                        user1=u1,
                        user2=u2,
                        initiated_by=request.user,
                        status=Conversation.Status.ACTIVE if is_friends else Conversation.Status.PENDING,
                        updated_at=now,
                    )
                else:
                    if conv.status != Conversation.Status.ACTIVE and conv.initiated_by_id != request.user.pk:
                        conv.status = Conversation.Status.ACTIVE
                    conv.updated_at = now
                    conv.save(update_fields=["status", "updated_at"])

                msg = DirectMessage.objects.create(
                    conversation=conv,
                    sender=request.user,
                    body=form.cleaned_data["body"],
                    attachment=form.cleaned_data.get("attachment"),
                    created_at=now,
                )
            _set_typing(request.user.pk, other.pk, False)
            if _is_live(request):
                _annotate_chat_separators([msg], conv=conv)
                msg_html = render_to_string(
                    "accounts/_chat_bubbles.html",
                    {"chat_messages": [msg], "user": request.user},
                    request=request,
                )
                return JsonResponse({"ok": True, "message_html": msg_html, "msg_id": msg.pk})
            return redirect("accounts:chat_thread", username=other.username)
        elif _is_live(request):
            first_err = next((errs[0] for errs in form.errors.values() if errs), "Invalid message.")
            return JsonResponse({"ok": False, "toast": str(first_err)}, status=400)

    chat_messages = []
    if conv:
        conv.messages.filter(is_read=False).exclude(sender=request.user).update(is_read=True)
        chat_messages = _annotate_chat_separators(list(conv.messages.select_related("sender").all()), conv=None)

    inbox, requests = _build_conversation_lists(request.user)
    tab = "requests" if flags["is_incoming_request"] else "inbox"

    return render(
        request,
        "accounts/chat.html",
        {
            "inbox": inbox,
            "requests": requests,
            "tab": tab,
            "active_partner": other,
            **flags,
            "chat_messages": chat_messages,
            "form": form,
            "friends_without_chat": request.user.friends().order_by("username"),
        },
    )


@login_required
@require_POST
def chat_accept(request, pk):
    conv = get_object_or_404(
        Conversation.objects.filter(Q(user1=request.user) | Q(user2=request.user)),
        pk=pk,
    )
    other = conv.other_participant(request.user)
    toast = ""
    if conv.initiated_by_id != request.user.pk:
        conv.status = Conversation.Status.ACTIVE
        conv.updated_at = timezone.now()
        conv.save(update_fields=["status", "updated_at"])
        toast = f"Message request from {other.name} accepted. You can now chat freely."
        if not _is_live(request):
            messages.success(request, toast)
    if _is_live(request):
        return JsonResponse({"ok": True, "toast": toast})
    return redirect("accounts:chat_thread", username=other.username)


@login_required
@require_POST
def chat_ignore(request, pk):
    conv = get_object_or_404(
        Conversation.objects.filter(Q(user1=request.user) | Q(user2=request.user)),
        pk=pk,
    )
    other = conv.other_participant(request.user)
    if conv.initiated_by_id != request.user.pk and relationship(request.user, other)[0] != "friends":
        conv.status = Conversation.Status.IGNORED
        conv.save(update_fields=["status"])
        conv.messages.filter(is_read=False).exclude(sender=request.user).update(is_read=True)
        if not _is_live(request):
            messages.info(request, f"Message request from {other.name} ignored.")
    if _is_live(request):
        return JsonResponse({"ok": True, "redirect": reverse("accounts:chat_inbox")})
    return redirect("accounts:chat_inbox")


@login_required
@require_POST
def chat_message_edit(request, pk):
    """Edit own message within the short 15-minute window after sending."""
    msg = get_object_or_404(
        DirectMessage.objects.select_related("conversation", "sender"),
        pk=pk,
        sender=request.user,
    )
    other = msg.conversation.other_participant(request.user)
    if not msg.can_edit:
        err = "Messages can only be edited within 15 minutes of sending."
        if _is_live(request):
            return JsonResponse({"ok": False, "toast": err}, status=400)
        messages.error(request, err)
        return redirect("accounts:chat_thread", username=other.username)

    new_body = (request.POST.get("body") or "").strip()[:4000]
    if not new_body and not msg.attachment:
        err = "Message cannot be empty."
        if _is_live(request):
            return JsonResponse({"ok": False, "toast": err}, status=400)
        messages.error(request, err)
        return redirect("accounts:chat_thread", username=other.username)

    msg.body = new_body
    msg.edited_at = timezone.now()
    msg.save(update_fields=["body", "edited_at"])
    msg.show_time_sep = False

    if _is_live(request):
        bubble_html = render_to_string(
            "accounts/_chat_bubbles.html",
            {"chat_messages": [msg], "user": request.user},
            request=request,
        )
        return JsonResponse({"ok": True, "msg_id": msg.pk, "bubble_html": bubble_html})
    return redirect("accounts:chat_thread", username=other.username)


@login_required
@require_POST
def chat_message_delete(request, pk):
    """Delete own chat message."""
    msg = get_object_or_404(
        DirectMessage.objects.select_related("conversation", "sender"),
        pk=pk,
        sender=request.user,
    )
    other = msg.conversation.other_participant(request.user)
    if not msg.is_deleted:
        if msg.attachment:
            msg.attachment.delete(save=False)
        msg.is_deleted = True
        msg.body = ""
        msg.attachment = None
        msg.edited_at = timezone.now()
        msg.save(update_fields=["is_deleted", "body", "attachment", "edited_at"])
    msg.show_time_sep = False

    if _is_live(request):
        bubble_html = render_to_string(
            "accounts/_chat_bubbles.html",
            {"chat_messages": [msg], "user": request.user},
            request=request,
        )
        return JsonResponse({"ok": True, "msg_id": msg.pk, "bubble_html": bubble_html})
    return redirect("accounts:chat_thread", username=other.username)


# ---------------------------------------------------------------------------
# Live Typing Indicator & Real-Time Sync Endpoint
# ---------------------------------------------------------------------------

_TYPING_MEM = {}
TYPING_TTL_SECONDS = 5.0


def _typing_key(sender_id, recipient_id):
    return f"chat_typing:{sender_id}:{recipient_id}"


def _set_typing(sender_id, recipient_id, is_typing):
    key = _typing_key(sender_id, recipient_id)
    now_ts = timezone.now().timestamp()
    if is_typing:
        _TYPING_MEM[key] = now_ts + TYPING_TTL_SECONDS
    else:
        _TYPING_MEM.pop(key, None)
    try:
        if is_typing:
            cache.set(key, True, timeout=int(TYPING_TTL_SECONDS))
        else:
            cache.delete(key)
    except Exception:
        pass


def _is_typing(sender_id, recipient_id):
    key = _typing_key(sender_id, recipient_id)
    exp = _TYPING_MEM.get(key)
    if exp is not None:
        if exp > timezone.now().timestamp():
            return True
        _TYPING_MEM.pop(key, None)
    try:
        return bool(cache.get(key))
    except Exception:
        return False


@login_required
@require_POST
def chat_typing(request, username):
    """Lightweight endpoint to broadcast whether the current user is typing to ``username``."""
    other = _target(username)
    if other.pk != request.user.pk:
        flags = _chat_partner_flags(request.user, other)
        is_typing = request.POST.get("typing") == "1" and flags["can_send"]
        _set_typing(request.user.pk, other.pk, is_typing)
    return JsonResponse({"ok": True})


def live_poll(request):
    """Lightweight real-time sync endpoint for badges, chat, friends, feeds and threads."""
    data = {"auth": request.user.is_authenticated}
    user = request.user

    if user.is_authenticated:
        # 1. Active chat thread & sidebar
        chat_partner_name = request.GET.get("chat_partner", "").strip()
        chat_shell = request.GET.get("chat_shell") == "1"
        active_partner = None

        if chat_partner_name:
            active_partner = User.objects.filter(username__iexact=chat_partner_name, is_active=True).first()
            if active_partner and active_partner.pk != user.pk:
                flags = _chat_partner_flags(user, active_partner)
                if request.GET.get("typing") == "1" and flags["can_send"]:
                    _set_typing(user.pk, active_partner.pk, True)
                conv = flags["conversation"]
                try:
                    last_msg_id = int(request.GET.get("last_msg_id") or 0)
                except ValueError:
                    last_msg_id = 0

                new_msgs = []
                msg_sig = "0:0"
                updated_bubbles = {}
                if conv:
                    conv.messages.filter(is_read=False).exclude(sender=user).update(is_read=True)
                    new_msgs = _annotate_chat_separators(
                        list(conv.messages.filter(pk__gt=last_msg_id).select_related("sender")),
                        conv=conv,
                    )
                    msg_agg = conv.messages.aggregate(
                        max_edit=Max("edited_at"),
                        del_cnt=Count("id", filter=Q(is_deleted=True)),
                    )
                    msg_sig = (
                        f"{msg_agg['del_cnt'] or 0}:"
                        f"{int(msg_agg['max_edit'].timestamp()) if msg_agg['max_edit'] else 0}"
                    )
                    client_msg_sig = request.GET.get("chat_msg_sig", "")
                    if client_msg_sig and client_msg_sig != msg_sig and last_msg_id > 0:
                        modified_msgs = list(
                            conv.messages.filter(pk__lte=last_msg_id)
                            .filter(Q(edited_at__isnull=False) | Q(is_deleted=True))
                            .select_related("sender")
                        )
                        for m in modified_msgs:
                            m.show_time_sep = False
                            updated_bubbles[str(m.pk)] = render_to_string(
                                "accounts/_chat_bubbles.html",
                                {"chat_messages": [m], "user": user},
                                request=request,
                            )

                conv_state = (
                    f"{conv.status if conv else 'none'}:"
                    f"{int(flags['can_send'])}:{int(flags['waiting_for_response'])}:"
                    f"{int(flags['is_incoming_request'])}:{int(flags['is_ignored_by_me'])}:"
                    f"{int(flags['is_friends'])}"
                )
                ctx = {"user": user, "active_partner": active_partner, **flags}
                data["chat"] = {
                    "conv_state": conv_state,
                    "msg_sig": msg_sig,
                    "updated_bubbles": updated_bubbles,
                    "is_friends": flags["is_friends"],
                    "partner_typing": _is_typing(active_partner.pk, user.pk),
                    "new_messages_html": (
                        render_to_string("accounts/_chat_bubbles.html", {"chat_messages": new_msgs, "user": user}, request=request)
                        if new_msgs
                        else ""
                    ),
                    "banner_html": render_to_string("accounts/_chat_banner.html", ctx, request=request),
                    "foot_html": render_to_string("accounts/_chat_foot.html", ctx, request=request),
                }

        if chat_shell:
            inbox, requests_list = _build_conversation_lists(user)
            tab = "requests" if request.GET.get("chat_tab") == "requests" else "inbox"
            data["chat_sidebar_html"] = render_to_string(
                "accounts/_chat_sidebar.html",
                {
                    "inbox": inbox,
                    "requests": requests_list,
                    "tab": tab,
                    "active_partner": active_partner,
                    "friends_without_chat": user.friends().order_by("username"),
                    "user": user,
                },
                request=request,
            )

        # 2. Navbar badge counts (calculated after marking open chat messages read)
        data["pending_friends"] = FriendRequest.objects.filter(
            to_user=user, status=FriendRequest.Status.PENDING
        ).count()
        data["unread_messages"] = (
            DirectMessage.objects.filter(
                Q(conversation__user1=user) | Q(conversation__user2=user),
                is_read=False,
            )
            .exclude(sender=user)
            .exclude(conversation__status=Conversation.Status.IGNORED)
            .count()
        )

        # 3. Friends page live region
        if request.GET.get("friends_page") == "1":
            incoming = FriendRequest.objects.filter(to_user=user, status=FriendRequest.Status.PENDING).select_related("from_user")
            outgoing = FriendRequest.objects.filter(from_user=user, status=FriendRequest.Status.PENDING).select_related("to_user")
            data["friends_html"] = render_to_string(
                "accounts/_friends_region.html",
                {
                    "incoming": incoming,
                    "outgoing": outgoing,
                    "friend_list": user.friends().order_by("username"),
                    "user": user,
                },
                request=request,
            )

        # 4. Profile page friend actions & stats live region
        profile_username = request.GET.get("profile_user", "").strip()
        if profile_username:
            p_user = User.objects.filter(username__iexact=profile_username, is_active=True).first()
            if p_user:
                rel_state, fr = relationship(user, p_user)
                data["profile_actions_html"] = render_to_string(
                    "accounts/_friend_actions.html",
                    {"profile_user": p_user, "rel": rel_state, "friend_request": fr},
                    request=request,
                )
                p_friend_ids = p_user.friend_ids()
                data["profile_friends_count"] = len(p_friend_ids)
                data["profile_threads_count"] = p_user.threads.count()
                data["profile_comments_count"] = p_user.comments.filter(is_deleted=False).count()
                if request.GET.get("profile_friends_grid") == "1":
                    p_friends = list(User.objects.filter(pk__in=p_friend_ids, is_active=True).order_by("username")[:20])
                    if p_friends:
                        data["profile_friends_grid_html"] = "".join(
                            render_to_string("accounts/_user_card.html", {"person": f}, request=request)
                            for f in p_friends
                        )
                    else:
                        data["profile_friends_grid_html"] = '<div class="empty card"><p class="muted">No friends yet.</p></div>'

    # 5. Live thread scores, comment counts, titles, excerpts & pin/lock states for visible cards
    raw_ids = request.GET.get("thread_ids", "")
    if raw_ids:
        ids = [int(x) for x in raw_ids.split(",") if x.strip().isdigit()][:40]
        if ids:
            found_threads = list(
                Thread.objects.filter(pk__in=ids).values(
                    "id", "score", "comment_count", "title", "body", "edited_at", "is_pinned", "is_locked"
                )
            )
            found_ids = {t["id"] for t in found_threads}
            data["threads"] = {
                str(t["id"]): {
                    "score": t["score"],
                    "comment_count": t["comment_count"],
                    "title": t["title"],
                    "excerpt": (t["body"][:239] + "…") if len(t["body"]) > 240 else t["body"],
                    "is_edited": bool(t["edited_at"]),
                    "is_pinned": t["is_pinned"],
                    "is_locked": t["is_locked"],
                }
                for t in found_threads
            }
            deleted_ids = [str(tid) for tid in ids if tid not in found_ids]
            if deleted_ids:
                data["deleted_thread_ids"] = deleted_ids

    # 5b. Live community member counts for any visible community cards / sidebars
    raw_cslugs = request.GET.get("community_slugs", "")
    if raw_cslugs:
        cslugs = [s.strip() for s in raw_cslugs.split(",") if s.strip()][:30]
        if cslugs:
            data["communities_counts"] = {
                c["slug"]: c["member_count"]
                for c in Community.objects.filter(slug__in=cslugs).values("slug", "member_count")
            }

    # 5c. Communities directory grid (/communities/)
    if request.GET.get("communities_grid") == "1":
        banned_cids = set()
        if user.is_authenticated and not user.is_staff:
            banned_cids = set(
                CommunitySanction.objects.filter(user=user, kind=CommunitySanction.Kind.BAN)
                .exclude(community__moderators=user)
                .values_list("community_id", flat=True)
            )
        c_qs = Community.objects.order_by("-member_count", "name")
        if banned_cids:
            c_qs = c_qs.exclude(pk__in=banned_cids)
        c_agg = c_qs.aggregate(cnt=Count("id"), max_id=Max("id"), sum_m=Sum("member_count"))
        joined_set = (
            set(Membership.objects.filter(user=user).values_list("community_id", flat=True)) - banned_cids
            if user.is_authenticated
            else set()
        )
        j_sig = ",".join(str(x) for x in sorted(joined_set))
        c_sig = f"{c_agg['cnt'] or 0}:{c_agg['max_id'] or 0}:{c_agg['sum_m'] or 0}:{j_sig}"
        data["communities_sig"] = c_sig
        client_csig = request.GET.get("communities_sig", "")
        if client_csig and client_csig != c_sig:
            data["communities_grid_html"] = render_to_string(
                "forum/_community_cards.html",
                {"communities": list(c_qs), "joined_ids": joined_set, "user": user},
                request=request,
            )

    # 6. Live community detail & new threads in feed (when on page 1)
    c_slug = request.GET.get("community", "").strip()
    if c_slug:
        comm_obj = Community.objects.filter(slug=c_slug).first()
        if comm_obj:
            sanction = comm_obj.get_sanction(user)
            is_banned = bool(sanction and sanction.kind == CommunitySanction.Kind.BAN)
            is_ghosted = bool(sanction and sanction.kind == CommunitySanction.Kind.GHOST)
            is_mod = comm_obj.is_moderator(user)
            open_reports_count = 0
            if is_mod:
                open_reports_count = (
                    Report.objects.filter(resolved=False)
                    .filter(Q(thread__community=comm_obj) | Q(comment__thread__community=comm_obj))
                    .count()
                )
            data["community_info"] = {
                "slug": comm_obj.slug,
                "member_count": comm_obj.member_count,
                "description": comm_obj.description or "No description yet.",
                "is_banned": is_banned,
                "is_ghosted": is_ghosted,
                "open_reports_count": open_reports_count,
            }

    # 6b. Live Community Management Dashboard (/c/<slug>/manage/)
    manage_slug = request.GET.get("manage_community", "").strip()
    if manage_slug and user.is_authenticated:
        m_comm = Community.objects.filter(slug=manage_slug).first()
        if m_comm and m_comm.is_moderator(user):
            moderators = list(m_comm.moderators.filter(is_active=True).order_by("username"))
            bans = list(m_comm.sanctions.filter(kind=CommunitySanction.Kind.BAN).select_related("user", "created_by"))
            ghosts = list(
                m_comm.sanctions.filter(kind=CommunitySanction.Kind.GHOST).select_related("user", "created_by")
            )
            reports = list(
                Report.objects.filter(resolved=False)
                .filter(Q(thread__community=m_comm) | Q(comment__thread__community=m_comm))
                .select_related("reporter", "thread", "comment", "thread__author", "comment__author", "comment__thread")[:50]
            )
            data["manage"] = {
                "slug": m_comm.slug,
                "member_count": m_comm.member_count,
                "mod_count": len(moderators),
                "sanctions_html": render_to_string(
                    "forum/_mod_sanctions_lists.html",
                    {"community": m_comm, "bans": bans, "ghosts": ghosts, "user": user},
                    request=request,
                ),
                "reports_html": render_to_string(
                    "forum/_mod_reports_list.html",
                    {"community": m_comm, "reports": reports, "user": user},
                    request=request,
                ),
                "team_html": render_to_string(
                    "forum/_mod_team_list.html",
                    {"community": m_comm, "moderators": moderators, "user": user},
                    request=request,
                ),
            }

    feed = request.GET.get("feed", "")
    max_tid_raw = request.GET.get("max_thread_id", "")
    if feed and max_tid_raw.isdigit() and request.GET.get("page", "1") == "1":
        max_tid = int(max_tid_raw)
        qs = Thread.objects.filter(pk__gt=max_tid).select_related("author", "community").order_by("-created_at")
        if user.is_authenticated and not user.is_staff:
            banned_cids = set(
                CommunitySanction.objects.filter(user=user, kind=CommunitySanction.Kind.BAN)
                .exclude(community__moderators=user)
                .values_list("community_id", flat=True)
            )
            if banned_cids:
                qs = qs.exclude(community_id__in=banned_cids)
        if feed == "community":
            qs = qs.filter(community__slug=c_slug)
        elif feed == "profile":
            feed_profile = request.GET.get("feed_profile", "").strip()
            qs = qs.filter(author__username__iexact=feed_profile)
        elif feed == "mine" and user.is_authenticated:
            joined = set(Membership.objects.filter(user=user).values_list("community_id", flat=True))
            qs = qs.filter(community_id__in=joined)
        new_threads = list(qs[:10])
        if new_threads:
            votes = {}
            if user.is_authenticated:
                votes = dict(
                    ThreadVote.objects.filter(user=user, thread__in=new_threads).values_list("thread_id", "value")
                )
            cards_html = "".join(
                render_to_string(
                    "forum/_thread_card.html",
                    {"thread": t, "votes": votes, "user": user, "show_pins": feed == "community"},
                    request=request,
                )
                for t in new_threads
            )
            data["new_threads_html"] = cards_html

    # 7. Live comments tree & thread state for an open thread (full page or quick-view drawer)
    open_tid_raw = request.GET.get("open_thread_id", "")
    if open_tid_raw.isdigit():
        open_thread = Thread.objects.select_related("community", "author").filter(pk=int(open_tid_raw)).first()
        if not open_thread:
            data["open_thread_deleted"] = True
        elif open_thread.community.is_banned(user):
            data["open_thread_banned"] = True
        else:
            is_mod = open_thread.community.is_moderator(user)
            is_ghosted = open_thread.community.is_ghosted(user)
            box_state = "ghost" if is_ghosted else ("locked" if open_thread.is_locked else "open")
            data["open_thread_meta"] = {
                "id": open_thread.pk,
                "community_url": open_thread.community.get_absolute_url(),
                "community_slug": open_thread.community.slug,
                "has_body": bool(open_thread.body),
                "body_html": str(render_body(open_thread.body)) if open_thread.body else "",
                "is_edited": bool(open_thread.edited_at),
                "is_pinned": open_thread.is_pinned,
                "is_locked": open_thread.is_locked,
                "is_ghosted": is_ghosted,
                "box_state": box_state,
            }
            data["comment_scores"] = {
                str(c["id"]): c["score"]
                for c in open_thread.comments.values("id", "score")
            }
            agg = open_thread.comments.aggregate(
                max_id=Max("id"),
                sum_score=Sum("score"),
                max_edit=Max("edited_at"),
                deleted_cnt=Count("id", filter=Q(is_deleted=True)),
            )
            sanc_cnt = open_thread.community.sanctions.count() if is_mod else 0
            sig = (
                f"{open_thread.comment_count}:{agg['max_id'] or 0}:"
                f"{agg['sum_score'] or 0}:{agg['deleted_cnt'] or 0}:"
                f"{int(agg['max_edit'].timestamp()) if agg['max_edit'] else 0}:"
                f"{int(open_thread.is_locked)}:{int(is_ghosted)}:{sanc_cnt}"
            )
            client_sig = request.GET.get("comments_sig", "")
            data["comments_sig"] = sig
            if client_sig and client_sig != sig:
                from forum.views import COMMENT_SORT_OPTIONS, COMMENT_SORTS

                csort = request.GET.get("csort", "best")
                if csort not in COMMENT_SORTS:
                    csort = "best"
                comments = list(open_thread.comments.select_related("author").order_by(*COMMENT_SORTS[csort]))
                children = defaultdict(list)
                for c in comments:
                    children[c.parent_id].append(c)
                for c in comments:
                    c.children = children.get(c.pk, [])
                comment_votes = {}
                if user.is_authenticated and comments:
                    comment_votes = dict(
                        CommentVote.objects.filter(user=user, comment__thread=open_thread).values_list(
                            "comment_id", "value"
                        )
                    )
                sanctioned_map = {}
                mod_ids = set()
                if is_mod:
                    sanctioned_map = dict(open_thread.community.sanctions.values_list("user_id", "kind"))
                    mod_ids = set(open_thread.community.moderators.values_list("id", flat=True))
                    if open_thread.community.created_by_id:
                        mod_ids.add(open_thread.community.created_by_id)
                data["comments_html"] = render_to_string(
                    "forum/_comments_section.html",
                    {
                        "thread": open_thread,
                        "community": open_thread.community,
                        "comments": children.get(None, []),
                        "csort": csort,
                        "comment_sort_options": COMMENT_SORT_OPTIONS,
                        "comment_votes": comment_votes,
                        "is_mod": is_mod,
                        "is_ghosted": is_ghosted,
                        "sanctioned_map": sanctioned_map,
                        "mod_ids": mod_ids,
                        "user": user,
                    },
                    request=request,
                )

    return JsonResponse(data)


