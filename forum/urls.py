from django.urls import path

from . import views

app_name = "forum"

urlpatterns = [
    path("", views.home, name="home"),
    path("search/", views.search, name="search"),
    path("guidelines/", views.guidelines, name="guidelines"),
    path("submit/", views.thread_create, name="submit"),
    # Communities
    path("communities/", views.community_list, name="community_list"),
    path("communities/new/", views.community_create, name="community_create"),
    path("c/<slug:slug>/", views.community_detail, name="community_detail"),
    path("c/<slug:slug>/manage/", views.community_manage, name="community_manage"),
    path("c/<slug:slug>/edit/", views.community_manage, name="community_edit"),
    path("c/<slug:slug>/mods/add/", views.community_mod_add, name="community_mod_add"),
    path("c/<slug:slug>/mods/<str:username>/remove/", views.community_mod_remove, name="community_mod_remove"),
    path("c/<slug:slug>/sanctions/set/", views.community_sanction_set, name="community_sanction_set"),
    path("c/<slug:slug>/sanctions/<str:username>/remove/", views.community_sanction_remove, name="community_sanction_remove"),
    path("c/<slug:slug>/reports/<int:pk>/resolve/", views.community_report_resolve, name="community_report_resolve"),
    path("c/<slug:slug>/join/", views.community_join, name="community_join"),
    path("c/<slug:slug>/leave/", views.community_leave, name="community_leave"),
    path("c/<slug:slug>/submit/", views.thread_create, name="community_submit"),
    # Threads
    path("c/<slug:slug>/t/<int:pk>/", views.thread_detail, name="thread_detail_short"),
    path("c/<slug:slug>/t/<int:pk>/<slug:thread_slug>/", views.thread_detail, name="thread_detail"),
    path("t/<int:pk>/edit/", views.thread_edit, name="thread_edit"),
    path("t/<int:pk>/delete/", views.thread_delete, name="thread_delete"),
    path("t/<int:pk>/pin/", views.thread_moderate, {"action": "pin"}, name="thread_pin"),
    path("t/<int:pk>/lock/", views.thread_moderate, {"action": "lock"}, name="thread_lock"),
    path("t/<int:pk>/vote/", views.thread_vote, name="thread_vote"),
    path("t/<int:pk>/comment/", views.comment_create, name="comment_create"),
    path("t/<int:pk>/report/", views.report, {"kind": "thread"}, name="thread_report"),
    # Comments
    path("comment/<int:pk>/edit/", views.comment_edit, name="comment_edit"),
    path("comment/<int:pk>/delete/", views.comment_delete, name="comment_delete"),
    path("comment/<int:pk>/vote/", views.comment_vote, name="comment_vote"),
    path("comment/<int:pk>/report/", views.report, {"kind": "comment"}, name="comment_report"),
]
