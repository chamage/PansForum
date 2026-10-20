from django.conf import settings
from django.db.models import Q

from .models import Conversation, DirectMessage, FriendRequest


def site(request):
    ctx = {"SITE_NAME": settings.SITE_NAME}
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        ctx["pending_friend_requests"] = FriendRequest.objects.filter(
            to_user=user, status=FriendRequest.Status.PENDING
        ).count()
        ctx["unread_messages_count"] = (
            DirectMessage.objects.filter(
                Q(conversation__user1=user) | Q(conversation__user2=user),
                is_read=False,
            )
            .exclude(sender=user)
            .exclude(conversation__status=Conversation.Status.IGNORED)
            .count()
        )
    return ctx
