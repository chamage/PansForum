from django.contrib import admin

from .models import Comment, Community, CommunitySanction, Membership, Report, Thread


@admin.register(Community)
class CommunityAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "member_count", "created_by", "created_at")
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}
    filter_horizontal = ("moderators",)
    raw_id_fields = ("created_by",)


@admin.register(Thread)
class ThreadAdmin(admin.ModelAdmin):
    list_display = ("title", "community", "author", "score", "comment_count", "is_pinned", "is_locked", "created_at")
    list_filter = ("community", "is_pinned", "is_locked")
    search_fields = ("title", "body", "author__username")
    raw_id_fields = ("author",)
    readonly_fields = ("score", "comment_count", "hot_rank")


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ("pk", "thread", "author", "score", "is_deleted", "created_at")
    list_filter = ("is_deleted",)
    search_fields = ("body", "author__username")
    raw_id_fields = ("thread", "author", "parent")


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ("__str__", "reporter", "reason", "resolved", "created_at")
    list_filter = ("resolved", "reason")
    raw_id_fields = ("reporter", "thread", "comment")
    actions = ["mark_resolved"]

    @admin.action(description="Mark selected reports as resolved")
    def mark_resolved(self, request, queryset):
        queryset.update(resolved=True)


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ("user", "community", "joined_at")
    raw_id_fields = ("user", "community")


@admin.register(CommunitySanction)
class CommunitySanctionAdmin(admin.ModelAdmin):
    list_display = ("user", "community", "kind", "reason", "created_by", "created_at")
    list_filter = ("kind", "community")
    search_fields = ("user__username", "reason")
    raw_id_fields = ("user", "community", "created_by")
