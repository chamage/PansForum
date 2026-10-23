import uuid

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models import F, Q
from django.db.models.functions import Lower
from django.urls import reverse
from django.utils import timezone


def avatar_upload_to(instance, filename):
    return f"avatars/{uuid.uuid4().hex}.webp"


def banner_upload_to(instance, filename):
    return f"banners/{uuid.uuid4().hex}.webp"


class User(AbstractUser):
    class Year(models.IntegerChoices):
        FIRST = 1, "1st year"
        SECOND = 2, "2nd year"
        THIRD = 3, "3rd year"
        FOURTH = 4, "4th year"
        FIFTH = 5, "5th year"
        GRADUATE = 6, "Graduate / Master's"
        ALUMNI = 7, "Alumni"
        STAFF = 8, "Faculty / staff"

    class BannerTheme(models.TextChoices):
        SAGE = "sage", "Sage"
        SUNSET = "sunset", "Sunset"
        OCEAN = "ocean", "Ocean"
        LAVENDER = "lavender", "Lavender"
        SLATE = "slate", "Slate"

    email = models.EmailField("email address", unique=True)
    display_name = models.CharField(max_length=50, blank=True)
    bio = models.TextField(max_length=500, blank=True)
    field_of_study = models.CharField(max_length=80, blank=True)
    year_of_study = models.PositiveSmallIntegerField(choices=Year.choices, null=True, blank=True)
    avatar = models.ImageField(upload_to=avatar_upload_to, blank=True)
    banner = models.ImageField(upload_to=banner_upload_to, blank=True)
    banner_theme = models.CharField(max_length=20, choices=BannerTheme.choices, default=BannerTheme.SAGE)

    class Meta:
        constraints = [
            models.UniqueConstraint(Lower("username"), name="accounts_user_username_ci_unique"),
            models.UniqueConstraint(Lower("email"), name="accounts_user_email_ci_unique"),
        ]

    def __str__(self):
        return self.username

    @property
    def name(self):
        return self.display_name or self.username

    @property
    def initial(self):
        return (self.name[:1] or "?").upper()

    def get_absolute_url(self):
        return reverse("accounts:profile", args=[self.username])

    # --- friendships -------------------------------------------------------
    def friend_ids(self):
        rows = FriendRequest.objects.filter(
            Q(from_user=self) | Q(to_user=self), status=FriendRequest.Status.ACCEPTED
        ).values_list("from_user_id", "to_user_id")
        return {b if a == self.pk else a for a, b in rows}

    def friends(self):
        return User.objects.filter(pk__in=self.friend_ids(), is_active=True)


class FriendRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        ACCEPTED = "accepted", "Accepted"

    from_user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="sent_friend_requests")
    to_user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="received_friend_requests")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    responded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["from_user", "to_user"], name="unique_friend_request"),
            models.CheckConstraint(condition=~Q(from_user=F("to_user")), name="no_self_friend_request"),
        ]

    def __str__(self):
        return f"{self.from_user} -> {self.to_user} ({self.status})"

    def accept(self):
        self.status = self.Status.ACCEPTED
        self.responded_at = timezone.now()
        self.save(update_fields=["status", "responded_at"])
        u1, u2 = sorted([self.from_user_id, self.to_user_id])
        Conversation.objects.filter(user1_id=u1, user2_id=u2).update(status=Conversation.Status.ACTIVE)


def relationship(viewer, other):
    """Describe how ``viewer`` relates to ``other``.

    Returns a ``(state, request)`` tuple where state is one of
    ``anonymous``, ``self``, ``none``, ``friends``, ``outgoing``, ``incoming``.
    """
    if not viewer.is_authenticated:
        return "anonymous", None
    if viewer.pk == other.pk:
        return "self", None
    fr = FriendRequest.objects.filter(
        Q(from_user=viewer, to_user=other) | Q(from_user=other, to_user=viewer)
    ).first()
    if fr is None:
        return "none", None
    if fr.status == FriendRequest.Status.ACCEPTED:
        return "friends", fr
    return ("outgoing" if fr.from_user_id == viewer.pk else "incoming"), fr


class Conversation(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Message request"
        ACTIVE = "active", "Active"
        IGNORED = "ignored", "Ignored"

    user1 = models.ForeignKey(User, on_delete=models.CASCADE, related_name="conversations_as_user1")
    user2 = models.ForeignKey(User, on_delete=models.CASCADE, related_name="conversations_as_user2")
    initiated_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name="initiated_conversations")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-updated_at"]
        constraints = [
            models.UniqueConstraint(fields=["user1", "user2"], name="unique_conversation_pair"),
            models.CheckConstraint(condition=Q(user1__lt=F("user2")), name="canonical_conversation_order"),
        ]

    def __str__(self):
        return f"Chat: {self.user1} & {self.user2} ({self.status})"

    @classmethod
    def pair_users(cls, u_a, u_b):
        return (u_a, u_b) if u_a.pk < u_b.pk else (u_b, u_a)

    @classmethod
    def between(cls, u_a, u_b):
        u1, u2 = cls.pair_users(u_a, u_b)
        return cls.objects.filter(user1=u1, user2=u2).first()

    def other_participant(self, user):
        return self.user2 if self.user1_id == user.pk else self.user1

    def get_absolute_url(self):
        return reverse("accounts:chat_thread", args=[self.pk])


def chat_media_upload_to(instance, filename):
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "webp"
    if ext not in ("webp", "gif", "png", "jpg", "jpeg"):
        ext = "webp"
    return f"chat/{uuid.uuid4().hex}.{ext}"


class DirectMessage(models.Model):
    EDIT_WINDOW_SECONDS = 15 * 60  # 15 minutes after sending

    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="messages")
    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name="sent_messages")
    body = models.TextField(max_length=4000, blank=True)
    attachment = models.FileField(upload_to=chat_media_upload_to, blank=True)
    is_read = models.BooleanField(default=False, db_index=True)
    is_deleted = models.BooleanField(default=False)
    edited_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["created_at", "pk"]
        indexes = [models.Index(fields=["conversation", "created_at"])]

    def __str__(self):
        return f"DM {self.pk} from {self.sender}"

    @property
    def can_edit(self):
        if self.is_deleted:
            return False
        return (timezone.now() - self.created_at).total_seconds() <= self.EDIT_WINDOW_SECONDS

    @property
    def can_delete(self):
        return not self.is_deleted

    def preview_text(self):
        if self.is_deleted:
            return "Message deleted"
        if self.body:
            return self.body
        if self.attachment:
            return "Image attachment"
        return "Message"


class ChatGroup(models.Model):
    name = models.CharField(max_length=80)
    created_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="created_chat_groups"
    )
    members = models.ManyToManyField(User, through="ChatGroupMember", related_name="chat_groups")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return f"Group: {self.name}"

    @property
    def initial(self):
        return (self.name[:1] or "#").upper()

    def get_absolute_url(self):
        return reverse("accounts:chat_group", args=[self.pk])

    def is_member(self, user):
        if not user.is_authenticated:
            return False
        return self.memberships.filter(user=user).exists()


class ChatGroupMember(models.Model):
    group = models.ForeignKey(ChatGroup, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="chat_group_memberships")
    joined_at = models.DateTimeField(auto_now_add=True)
    last_read_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["joined_at"]
        constraints = [
            models.UniqueConstraint(fields=["group", "user"], name="unique_chat_group_member"),
        ]

    def __str__(self):
        return f"{self.user} in {self.group}"


class GroupMessage(models.Model):
    EDIT_WINDOW_SECONDS = 15 * 60  # 15 minutes after sending

    group = models.ForeignKey(ChatGroup, on_delete=models.CASCADE, related_name="messages")
    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name="sent_group_messages")
    body = models.TextField(max_length=4000, blank=True)
    attachment = models.FileField(upload_to=chat_media_upload_to, blank=True)
    is_deleted = models.BooleanField(default=False)
    edited_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["created_at", "pk"]
        indexes = [models.Index(fields=["group", "created_at"])]

    def __str__(self):
        return f"GroupMsg {self.pk} in {self.group_id} from {self.sender}"

    @property
    def can_edit(self):
        if self.is_deleted:
            return False
        return (timezone.now() - self.created_at).total_seconds() <= self.EDIT_WINDOW_SECONDS

    @property
    def can_delete(self):
        return not self.is_deleted

    def preview_text(self):
        if self.is_deleted:
            return "Message deleted"
        if self.body:
            return self.body
        if self.attachment:
            return "Image attachment"
        return "Message"



