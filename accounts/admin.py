from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import ChatGroup, ChatGroupMember, Conversation, DirectMessage, FriendRequest, GroupMessage, User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ("username", "email", "display_name", "is_active", "is_staff", "date_joined")
    search_fields = ("username", "email", "display_name")
    fieldsets = BaseUserAdmin.fieldsets + (
        ("Profile", {"fields": ("display_name", "bio", "field_of_study", "year_of_study", "avatar", "banner", "banner_theme")}),
    )
    add_fieldsets = BaseUserAdmin.add_fieldsets + ((None, {"fields": ("email",)}),)


@admin.register(FriendRequest)
class FriendRequestAdmin(admin.ModelAdmin):
    list_display = ("from_user", "to_user", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("from_user__username", "to_user__username")
    raw_id_fields = ("from_user", "to_user")


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ("user1", "user2", "initiated_by", "status", "updated_at")
    list_filter = ("status",)
    search_fields = ("user1__username", "user2__username")
    raw_id_fields = ("user1", "user2", "initiated_by")


@admin.register(DirectMessage)
class DirectMessageAdmin(admin.ModelAdmin):
    list_display = ("pk", "conversation", "sender", "is_read", "created_at")
    list_filter = ("is_read",)
    search_fields = ("sender__username", "body")
    raw_id_fields = ("conversation", "sender")


class ChatGroupMemberInline(admin.TabularInline):
    model = ChatGroupMember
    extra = 0
    raw_id_fields = ("user",)


@admin.register(ChatGroup)
class ChatGroupAdmin(admin.ModelAdmin):
    list_display = ("pk", "name", "created_by", "updated_at")
    search_fields = ("name", "created_by__username")
    raw_id_fields = ("created_by",)
    inlines = [ChatGroupMemberInline]


@admin.register(GroupMessage)
class GroupMessageAdmin(admin.ModelAdmin):
    list_display = ("pk", "group", "sender", "is_deleted", "created_at")
    list_filter = ("is_deleted",)
    search_fields = ("sender__username", "body", "group__name")
    raw_id_fields = ("group", "sender")

