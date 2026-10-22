from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("register/", views.register, name="register"),
    path("login/", views.LoginView.as_view(), name="login"),
    path("logout/", views.LogoutView.as_view(), name="logout"),
    # Password reset
    path("password-reset/", views.PasswordResetView.as_view(), name="password_reset"),
    path(
        "password-reset/sent/",
        auth_views.PasswordResetDoneView.as_view(template_name="registration/password_reset_done.html"),
        name="password_reset_done",
    ),
    path("password-reset/<uidb64>/<token>/", views.PasswordResetConfirmView.as_view(), name="password_reset_confirm"),
    path(
        "password-reset/complete/",
        auth_views.PasswordResetCompleteView.as_view(template_name="registration/password_reset_complete.html"),
        name="password_reset_complete",
    ),
    # Settings
    path("settings/", views.settings_profile, name="settings_profile"),
    path("settings/account/", views.settings_account, name="settings_account"),
    path("settings/password/", views.PasswordChangeView.as_view(), name="settings_password"),
    path("settings/delete/", views.settings_delete, name="settings_delete"),
    # Friends
    path("friends/", views.friends, name="friends"),
    path("friends/<int:pk>/accept/", views.friend_accept, name="friend_accept"),
    path("friends/<int:pk>/decline/", views.friend_decline, name="friend_decline"),
    # Chat / Direct Messages & Group Chats
    path("messages/", views.chat_inbox, name="chat_inbox"),
    path("messages/groups/create/", views.chat_group_create, name="chat_group_create"),
    path("messages/g/<int:pk>/", views.chat_group, name="chat_group"),
    path("messages/g/<int:pk>/add-member/", views.chat_group_add_member, name="chat_group_add_member"),
    path("messages/g/<int:pk>/leave/", views.chat_group_leave, name="chat_group_leave"),
    path("messages/g/<int:pk>/typing/", views.chat_group_typing, name="chat_group_typing"),
    path("messages/gm/<int:pk>/edit/", views.chat_group_message_edit, name="chat_group_message_edit"),
    path("messages/gm/<int:pk>/delete/", views.chat_group_message_delete, name="chat_group_message_delete"),
    path("messages/dock/", views.chat_dock, name="chat_dock"),
    path("messages/dock/g/<int:pk>/", views.chat_dock_group, name="chat_dock_group"),
    path("messages/dock/<str:username>/", views.chat_dock, name="chat_dock_thread"),
    path("messages/<int:pk>/accept/", views.chat_accept, name="chat_accept"),
    path("messages/<int:pk>/ignore/", views.chat_ignore, name="chat_ignore"),
    path("messages/m/<int:pk>/edit/", views.chat_message_edit, name="chat_message_edit"),
    path("messages/m/<int:pk>/delete/", views.chat_message_delete, name="chat_message_delete"),
    path("messages/<str:username>/typing/", views.chat_typing, name="chat_typing"),
    path("messages/<str:username>/", views.chat_thread, name="chat_thread"),
    # Live real-time sync
    path("live/poll/", views.live_poll, name="live_poll"),
    # Profiles
    path("u/<str:username>/", views.profile, name="profile"),
    path("u/<str:username>/add-friend/", views.friend_add, name="friend_add"),
    path("u/<str:username>/cancel-request/", views.friend_cancel, name="friend_cancel"),
    path("u/<str:username>/unfriend/", views.friend_remove, name="friend_remove"),
]
