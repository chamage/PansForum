from django.conf import settings
from django.db.models import F, Q

from .models import Conversation, DirectMessage, FriendRequest, GroupMessage


def count_unread_messages(user):
    if user is None or not user.is_authenticated:
        return 0
    dm_unread = (
        DirectMessage.objects.filter(
            Q(conversation__user1=user) | Q(conversation__user2=user),
            is_read=False,
        )
        .exclude(sender=user)
        .exclude(conversation__status=Conversation.Status.IGNORED)
        .count()
    )
    group_unread = (
        GroupMessage.objects.filter(
            group__memberships__user=user,
            created_at__gt=F("group__memberships__last_read_at"),
            is_deleted=False,
        )
        .exclude(sender=user)
        .count()
    )
    return dm_unread + group_unread


def site(request):
    ctx = {"SITE_NAME": settings.SITE_NAME}
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        ctx["pending_friend_requests"] = FriendRequest.objects.filter(
            to_user=user, status=FriendRequest.Status.PENDING
        ).count()
        ctx["unread_messages_count"] = count_unread_messages(user)
    return ctx

