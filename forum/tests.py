from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import Comment, Community, Thread

User = get_user_model()


class ForumTests(TestCase):
    def setUp(self):
        self.password = "CorrectHorseBattery99!"
        self.alice = User.objects.create_user(
            username="alice", email="alice@student.pans.edu", password=self.password
        )
        self.bob = User.objects.create_user(
            username="bob", email="bob@student.pans.edu", password=self.password
        )
        self.community = Community.objects.create(
            name="Computer Science",
            slug="computer-science",
            description="CS discussions",
            created_by=self.alice,
        )
        self.community.moderators.add(self.alice)

    def test_security_headers_present(self):
        resp = self.client.get(reverse("forum:home"))
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Content-Security-Policy", resp.headers)
        self.assertIn("Permissions-Policy", resp.headers)

    def test_create_thread_and_nested_comments(self):
        self.client.force_login(self.alice)
        resp = self.client.post(
            reverse("forum:community_submit", args=[self.community.slug]),
            {"title": "How to prepare for Algorithms exam?", "body": "Share your best tips!"},
        )
        thread = Thread.objects.get()
        self.assertEqual(thread.score, 1)
        self.assertRedirects(resp, thread.get_absolute_url())

        # Bob posts a top-level comment
        self.client.force_login(self.bob)
        self.client.post(
            reverse("forum:comment_create", args=[thread.pk]),
            {"body": "Practice dynamic programming problems."},
        )
        parent_comment = Comment.objects.get()
        self.assertEqual(parent_comment.depth, 0)

        # Alice replies to Bob's comment
        self.client.force_login(self.alice)
        self.client.post(
            reverse("forum:comment_create", args=[thread.pk]),
            {"body": "Thanks! Any specific book?", "parent": parent_comment.pk},
        )
        reply = Comment.objects.exclude(pk=parent_comment.pk).get()
        self.assertEqual(reply.parent, parent_comment)
        self.assertEqual(reply.depth, 1)
        thread.refresh_from_db()
        self.assertEqual(thread.comment_count, 2)

    def test_voting_toggle_and_flip(self):
        thread = Thread.objects.create(
            community=self.community, author=self.alice, title="Voting test thread", score=0
        )
        self.client.force_login(self.bob)

        # Upvote -> +1
        resp = self.client.post(
            reverse("forum:thread_vote", args=[thread.pk]),
            {"value": "1"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(resp.json(), {"score": 1, "vote": 1})

        # Flip to downvote -> -1
        resp = self.client.post(
            reverse("forum:thread_vote", args=[thread.pk]),
            {"value": "-1"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(resp.json(), {"score": -1, "vote": -1})

        # Same vote again -> unvote (0)
        resp = self.client.post(
            reverse("forum:thread_vote", args=[thread.pk]),
            {"value": "-1"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(resp.json(), {"score": 0, "vote": 0})

    def test_moderation_lock_prevents_comments(self):
        thread = Thread.objects.create(
            community=self.community, author=self.alice, title="Locked thread test"
        )
        self.client.force_login(self.alice)
        self.client.post(reverse("forum:thread_lock", args=[thread.pk]))
        thread.refresh_from_db()
        self.assertTrue(thread.is_locked)

        # Bob tries to comment on locked thread
        self.client.force_login(self.bob)
        self.client.post(
            reverse("forum:comment_create", args=[thread.pk]),
            {"body": "Can I comment?"},
        )
        self.assertEqual(Comment.objects.count(), 0)

    def test_join_and_leave_community(self):
        self.client.force_login(self.bob)
        self.client.post(reverse("forum:community_join", args=[self.community.slug]))
        self.community.refresh_from_db()
        self.assertEqual(self.community.member_count, 1)

        self.client.post(reverse("forum:community_leave", args=[self.community.slug]))
        self.community.refresh_from_db()
        self.assertEqual(self.community.member_count, 0)

    def test_quick_view_drawer(self):
        thread = Thread.objects.create(
            community=self.community, author=self.alice, title="Quick view test", body="Preview body"
        )
        resp = self.client.get(thread.get_absolute_url(), HTTP_X_QUICK_VIEW="1")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Open full thread")
        self.assertContains(resp, "Quick view test")
        self.assertNotContains(resp, "<html")

    def test_live_poll_threads_and_comments(self):
        thread = Thread.objects.create(
            community=self.community, author=self.alice, title="Live thread", body="Body"
        )
        self.client.force_login(self.bob)
        c_resp = self.client.post(
            reverse("forum:comment_create", args=[thread.pk]),
            {"body": "Real-time comment!"},
            HTTP_X_LIVE_ACTION="1",
        )
        self.assertEqual(c_resp.status_code, 200)
        self.assertTrue(c_resp.json()["ok"])

        poll = self.client.get(
            reverse("accounts:live_poll"),
            {
                "thread_ids": str(thread.pk),
                "feed": "all",
                "page": "1",
                "max_thread_id": "0",
                "open_thread_id": str(thread.pk),
                "comments_sig": "init",
            },
        )
        self.assertEqual(poll.status_code, 200)
        data = poll.json()
        self.assertEqual(data["threads"][str(thread.pk)]["comment_count"], 1)
        self.assertIn("Live thread", data["new_threads_html"])
        self.assertIn("Real-time comment!", data["comments_html"])


