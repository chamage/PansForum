from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import Conversation, DirectMessage, FriendRequest, User


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
