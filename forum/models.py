import math

from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify

MAX_COMMENT_DEPTH = 8
EPOCH = 1_700_000_000  # arbitrary fixed epoch for hot ranking


def hot_score(score, created):
    """Reddit-style 'hot' ranking: votes matter logarithmically, recency linearly."""
    order = math.log10(max(abs(score), 1))
    sign = 1 if score > 0 else -1 if score < 0 else 0
    seconds = created.timestamp() - EPOCH
    return round(sign * order + seconds / 45000, 7)


class Community(models.Model):
    name = models.CharField(max_length=50, unique=True)
    slug = models.SlugField(max_length=50, unique=True)
    description = models.TextField(max_length=500, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="created_communities"
    )
    moderators = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="moderated_communities")
    member_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "communities"

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("forum:community_detail", args=[self.slug])

    def is_moderator(self, user):
        if not user.is_authenticated:
            return False
        return user.is_staff or self.moderators.filter(pk=user.pk).exists()

    def get_sanction(self, user):
        if not user.is_authenticated or self.is_moderator(user):
            return None
        return self.sanctions.filter(user=user).first()

    def is_banned(self, user):
        if not user.is_authenticated or self.is_moderator(user):
            return False
        return self.sanctions.filter(user=user, kind=CommunitySanction.Kind.BAN).exists()

    def is_ghosted(self, user):
        if not user.is_authenticated or self.is_moderator(user):
            return False
        return self.sanctions.filter(user=user, kind=CommunitySanction.Kind.GHOST).exists()


class CommunitySanction(models.Model):
    class Kind(models.TextChoices):
        BAN = "ban", "Banned (cannot enter community)"
        GHOST = "ghost", "Ghosted (can view, cannot interact)"

    community = models.ForeignKey(Community, on_delete=models.CASCADE, related_name="sanctions")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="community_sanctions")
    kind = models.CharField(max_length=10, choices=Kind.choices)
    reason = models.CharField(max_length=240, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="issued_sanctions"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["community", "user"], name="unique_community_sanction")]

    def __str__(self):
        return f"{self.user} — {self.kind} in c/{self.community.slug}"


class Membership(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships")
    community = models.ForeignKey(Community, on_delete=models.CASCADE, related_name="memberships")
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "community"], name="unique_membership")]


class Thread(models.Model):
    community = models.ForeignKey(Community, on_delete=models.CASCADE, related_name="threads")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="threads")
    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=80, blank=True)
    body = models.TextField(max_length=20000, blank=True)
    score = models.IntegerField(default=0)
    comment_count = models.PositiveIntegerField(default=0)
    hot_rank = models.FloatField(default=0, db_index=True)
    is_pinned = models.BooleanField(default=False)
    is_locked = models.BooleanField(default=False)
    edited_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        indexes = [models.Index(fields=["community", "-hot_rank"]), models.Index(fields=["-score"])]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        self.slug = slugify(self.title)[:80].strip("-") or "thread"
        self.hot_rank = hot_score(self.score, self.created_at)
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("forum:thread_detail", args=[self.community.slug, self.pk, self.slug])

    def refresh_rank(self):
        self.refresh_from_db(fields=["score"])
        self.hot_rank = hot_score(self.score, self.created_at)
        Thread.objects.filter(pk=self.pk).update(hot_rank=self.hot_rank)


class Comment(models.Model):
    thread = models.ForeignKey(Thread, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="comments")
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.CASCADE, related_name="replies")
    body = models.TextField(max_length=10000)
    depth = models.PositiveSmallIntegerField(default=0)
    score = models.IntegerField(default=0)
    is_deleted = models.BooleanField(default=False)
    edited_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        indexes = [models.Index(fields=["thread", "created_at"])]

    def __str__(self):
        return f"Comment {self.pk} on {self.thread_id}"

    def get_absolute_url(self):
        return f"{self.thread.get_absolute_url()}#c{self.pk}"

    @property
    def can_reply(self):
        return not self.is_deleted and self.depth < MAX_COMMENT_DEPTH


class ThreadVote(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="thread_votes")
    thread = models.ForeignKey(Thread, on_delete=models.CASCADE, related_name="votes")
    value = models.SmallIntegerField(choices=[(1, "Up"), (-1, "Down")])

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "thread"], name="unique_thread_vote")]


class CommentVote(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="comment_votes")
    comment = models.ForeignKey(Comment, on_delete=models.CASCADE, related_name="votes")
    value = models.SmallIntegerField(choices=[(1, "Up"), (-1, "Down")])

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "comment"], name="unique_comment_vote")]


class Report(models.Model):
    class Reason(models.TextChoices):
        SPAM = "spam", "Spam or advertising"
        HARASSMENT = "harassment", "Harassment or bullying"
        HATE = "hate", "Hate speech"
        CHEATING = "cheating", "Academic dishonesty (sharing exam answers etc.)"
        PERSONAL = "personal", "Sharing someone's personal information"
        OTHER = "other", "Something else"

    reporter = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="reports")
    thread = models.ForeignKey(Thread, null=True, blank=True, on_delete=models.CASCADE, related_name="reports")
    comment = models.ForeignKey(Comment, null=True, blank=True, on_delete=models.CASCADE, related_name="reports")
    reason = models.CharField(max_length=20, choices=Reason.choices)
    details = models.TextField(max_length=1000, blank=True)
    resolved = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["resolved", "-created_at"]

    def __str__(self):
        target = f"thread {self.thread_id}" if self.thread_id else f"comment {self.comment_id}"
        return f"{self.get_reason_display()} — {target}"
