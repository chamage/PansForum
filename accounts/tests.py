from datetime import timedelta
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from .models import Conversation, DirectMessage, FriendRequest, User, relationship


def make_image_bytes(fmt="PNG", size=(300, 300), color=(45, 106, 79)):
    buf = BytesIO()
    img = Image.new("RGB", size, color)
    img.save(buf, format=fmt)
    return buf.getvalue()


class AccountsTests(TestCase):
    def setUp(self):
        self.password = "CorrectHorseBattery99!"
        self.alice = User.objects.create_user(
            username="alice", email="alice@student.pans.edu", password=self.password
        )
        self.bob = User.objects.create_user(
            username="bob", email="bob@student.pans.edu", password=self.password
        )

    def test_registration_and_honeypot(self):
        # Honeypot filled -> rejected
        resp = self.client.post(
            reverse("accounts:register"),
            {
                "username": "botuser",
                "email": "bot@student.pans.edu",
                "password1": self.password,
                "password2": self.password,
                "accept_guidelines": "on",
                "website": "http://spam.example",
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(User.objects.filter(username="botuser").exists())

        # Valid registration -> logged in & redirected
        resp = self.client.post(
            reverse("accounts:register"),
            {
                "username": "charlie",
                "email": "Charlie@student.pans.edu",
                "password1": self.password,
                "password2": self.password,
                "accept_guidelines": "on",
                "website": "",
            },
        )
        self.assertRedirects(resp, reverse("forum:community_list"))
        self.assertTrue(User.objects.filter(username="charlie", email="charlie@student.pans.edu").exists())

    def test_login_with_username_or_email(self):
        # Login by email (case-insensitive)
        resp = self.client.post(
            reverse("accounts:login"),
            {"username": "ALICE@student.pans.edu", "password": self.password},
        )
        self.assertRedirects(resp, reverse("forum:home"))
        self.client.logout()

        # Login by username
        resp = self.client.post(
            reverse("accounts:login"),
            {"username": "alice", "password": self.password},
        )
        self.assertRedirects(resp, reverse("forum:home"))

    def test_profile_update_avatar_and_banner_reencoding(self):
        self.client.force_login(self.alice)
        avatar_file = SimpleUploadedFile("avatar.png", make_image_bytes("PNG", (400, 400)), content_type="image/png")
        banner_file = SimpleUploadedFile("banner.jpg", make_image_bytes("JPEG", (1600, 600)), content_type="image/jpeg")

        resp = self.client.post(
            reverse("accounts:settings_profile"),
            {
                "display_name": "Alice N.",
                "field_of_study": "Computer Science",
                "year_of_study": User.Year.SECOND,
                "bio": "Hello PANS!",
                "banner_theme": User.BannerTheme.OCEAN,
                "avatar": avatar_file,
                "banner": banner_file,
                "avatar_crop": "0.10000,0.10000,0.80000,0.80000",
                "banner_crop": "0.05000,0.15000,0.90000,0.70000",
            },
        )
        self.assertRedirects(resp, reverse("accounts:settings_profile"))
        self.alice.refresh_from_db()
        self.assertEqual(self.alice.display_name, "Alice N.")
        self.assertTrue(self.alice.avatar.name.endswith(".webp"))
        self.assertTrue(self.alice.banner.name.endswith(".webp"))

        # Clean up test files
        self.alice.avatar.delete(save=False)
        self.alice.banner.delete(save=False)

    def test_invalid_image_rejected(self):
        self.client.force_login(self.alice)
        bad_file = SimpleUploadedFile("evil.png", b"not-an-image-payload", content_type="image/png")
        resp = self.client.post(
            reverse("accounts:settings_profile"),
            {"display_name": "Alice", "banner_theme": User.BannerTheme.SAGE, "avatar": bad_file},
        )
        self.assertEqual(resp.status_code, 200)
        self.alice.refresh_from_db()
        self.assertFalse(bool(self.alice.avatar))

    def test_password_change(self):
        self.client.force_login(self.alice)
        new_pw = "BrandNewPassphrase2026!"
        resp = self.client.post(
            reverse("accounts:settings_password"),
            {
                "old_password": self.password,
                "new_password1": new_pw,
                "new_password2": new_pw,
            },
        )
        self.assertRedirects(resp, reverse("accounts:settings_password"))
        self.alice.refresh_from_db()
        self.assertTrue(self.alice.check_password(new_pw))

    def test_friend_request_lifecycle(self):
        # Alice sends friend request to Bob
        self.client.force_login(self.alice)
        self.client.post(reverse("accounts:friend_add", args=[self.bob.username]))
        state, fr = relationship(self.alice, self.bob)
        self.assertEqual(state, "outgoing")
        self.assertIsNotNone(fr)

        # Bob sees incoming and accepts
        self.client.force_login(self.bob)
        state_bob, _ = relationship(self.bob, self.alice)
        self.assertEqual(state_bob, "incoming")
        self.client.post(reverse("accounts:friend_accept", args=[fr.pk]))

        state_after, _ = relationship(self.alice, self.bob)
        self.assertEqual(state_after, "friends")
        self.assertIn(self.bob, self.alice.friends())

        # Unfriend
        self.client.post(reverse("accounts:friend_remove", args=[self.alice.username]))
        state_removed, _ = relationship(self.alice, self.bob)
        self.assertEqual(state_removed, "none")

    def test_self_friend_request_blocked(self):
        self.client.force_login(self.alice)
        self.client.post(reverse("accounts:friend_add", args=[self.alice.username]))
        self.assertEqual(FriendRequest.objects.count(), 0)

    def test_friends_can_dm_freely(self):
        FriendRequest.objects.create(
            from_user=self.alice, to_user=self.bob, status=FriendRequest.Status.ACCEPTED
        )
        self.client.force_login(self.alice)
        self.client.post(reverse("accounts:chat_thread", args=[self.bob.username]), {"body": "Hey Bob!"})
        self.client.post(reverse("accounts:chat_thread", args=[self.bob.username]), {"body": "Are you going to lecture?"})

        conv = Conversation.between(self.alice, self.bob)
        self.assertEqual(conv.status, Conversation.Status.ACTIVE)
        self.assertEqual(conv.messages.count(), 2)

    def test_non_friend_message_request_respond_or_ignore(self):
        # Alice (non-friend) sends an initial message request to Bob
        self.client.force_login(self.alice)
        self.client.post(reverse("accounts:chat_thread", args=[self.bob.username]), {"body": "Hi Bob, can we share notes?"})
        conv = Conversation.between(self.alice, self.bob)
        self.assertEqual(conv.status, Conversation.Status.PENDING)
        self.assertEqual(conv.messages.count(), 1)

        # Alice cannot send a 2nd message before Bob responds or accepts
        self.client.post(reverse("accounts:chat_thread", args=[self.bob.username]), {"body": "Hello?"})
        self.assertEqual(conv.messages.count(), 1)

        # Bob decides to ignore it first
        self.client.force_login(self.bob)
        self.client.post(reverse("accounts:chat_ignore", args=[conv.pk]))
        conv.refresh_from_db()
        self.assertEqual(conv.status, Conversation.Status.IGNORED)

        # Alice still cannot message while ignored
        self.client.force_login(self.alice)
        self.client.post(reverse("accounts:chat_thread", args=[self.bob.username]), {"body": "Still blocked"})
        self.assertEqual(conv.messages.count(), 1)

        # Later Bob decides to respond -> conversation becomes ACTIVE and Alice can reply freely
        self.client.force_login(self.bob)
        self.client.post(reverse("accounts:chat_thread", args=[self.alice.username]), {"body": "Sure, here are the notes!"})
        conv.refresh_from_db()
        self.assertEqual(conv.status, Conversation.Status.ACTIVE)
        self.assertEqual(conv.messages.count(), 2)

        self.client.force_login(self.alice)
        self.client.post(reverse("accounts:chat_thread", args=[self.bob.username]), {"body": "Thank you so much!"})
        self.assertEqual(conv.messages.count(), 3)

    def test_live_poll_and_live_actions(self):
        # Alice sends a friend request via X-Live-Action
        self.client.force_login(self.alice)
        resp_fr = self.client.post(
            reverse("accounts:friend_add", args=[self.bob.username]),
            HTTP_X_LIVE_ACTION="1",
        )
        self.assertEqual(resp_fr.status_code, 200)
        self.assertTrue(resp_fr.json()["ok"])

        # Alice sends a chat message via X-Live-Action
        resp_msg = self.client.post(
            reverse("accounts:chat_thread", args=[self.bob.username]),
            {"body": "Live hello!"},
            HTTP_X_LIVE_ACTION="1",
        )
        self.assertEqual(resp_msg.status_code, 200)
        self.assertTrue(resp_msg.json()["ok"])

        # Bob polls /live/poll/ and sees 1 pending friend request and 1 unread message
        self.client.force_login(self.bob)
        poll_resp = self.client.get(
            reverse("accounts:live_poll"),
            {"friends_page": "1", "profile_user": self.alice.username},
        )
        self.assertEqual(poll_resp.status_code, 200)
        payload = poll_resp.json()
        self.assertEqual(payload["pending_friends"], 1)
        self.assertEqual(payload["unread_messages"], 1)
        self.assertIn("friends_html", payload)
        self.assertIn("profile_actions_html", payload)

        # Bob polls while viewing chat with Alice -> receives new_messages_html & marks read
        chat_poll = self.client.get(
            reverse("accounts:live_poll"),
            {"chat_shell": "1", "chat_partner": self.alice.username, "last_msg_id": "0"},
        )
        chat_payload = chat_poll.json()
        self.assertIn("Live hello!", chat_payload["chat"]["new_messages_html"])
        self.assertEqual(chat_payload["unread_messages"], 0)
        self.assertFalse(chat_payload["chat"]["partner_typing"])

        # Bob starts typing to Alice -> Alice sees partner_typing = True
        self.client.post(reverse("accounts:chat_typing", args=[self.alice.username]), {"typing": "1"})
        self.client.force_login(self.alice)
        alice_poll = self.client.get(
            reverse("accounts:live_poll"),
            {"chat_shell": "1", "chat_partner": self.bob.username, "last_msg_id": "0"},
        )
        self.assertTrue(alice_poll.json()["chat"]["partner_typing"])

        # Bob sends his message -> typing indicator clears immediately
        self.client.force_login(self.bob)
        self.client.post(
            reverse("accounts:chat_thread", args=[self.alice.username]),
            {"body": "Replying now!"},
            HTTP_X_LIVE_ACTION="1",
        )
        self.client.force_login(self.alice)
        alice_poll_after = self.client.get(
            reverse("accounts:live_poll"),
            {"chat_shell": "1", "chat_partner": self.bob.username, "last_msg_id": "0"},
        )
        self.assertFalse(alice_poll_after.json()["chat"]["partner_typing"])

    def test_chat_media_friends_only_and_time_separators(self):
        # 1. Non-friends cannot send media attachments
        self.client.force_login(self.alice)
        non_friend_img = SimpleUploadedFile("pic.png", make_image_bytes("PNG", (200, 200)), content_type="image/png")
        blocked_media = self.client.post(
            reverse("accounts:chat_thread", args=[self.bob.username]),
            {"attachment": non_friend_img},
            HTTP_X_LIVE_ACTION="1",
        )
        self.assertEqual(blocked_media.status_code, 400)
        self.assertFalse(blocked_media.json()["ok"])
        self.assertEqual(DirectMessage.objects.count(), 0)

        # 2. Once friends, Alice can send media attachments (with or without text)
        FriendRequest.objects.create(
            from_user=self.alice, to_user=self.bob, status=FriendRequest.Status.ACCEPTED
        )
        photo1 = SimpleUploadedFile("note1.png", make_image_bytes("PNG", (320, 240)), content_type="image/png")
        ok_first = self.client.post(
            reverse("accounts:chat_thread", args=[self.bob.username]),
            {"attachment": photo1},
            HTTP_X_LIVE_ACTION="1",
        )
        self.assertEqual(ok_first.status_code, 200)
        self.assertTrue(ok_first.json()["ok"])
        self.assertIn("chat-media", ok_first.json()["message_html"])
        # First message in conversation should include a Messenger-style time separator
        self.assertIn("chat-sep", ok_first.json()["message_html"])

        # Immediate second message (0 min gap) should NOT have a second separator
        ok_second = self.client.post(
            reverse("accounts:chat_thread", args=[self.bob.username]),
            {"body": "Here is the slide"},
            HTTP_X_LIVE_ACTION="1",
        )
        self.assertEqual(ok_second.status_code, 200)
        self.assertTrue(ok_second.json()["ok"])
        self.assertNotIn("chat-sep", ok_second.json()["message_html"])

        # Backdate the existing messages by 30 minutes and send a new message -> new time separator appears!
        DirectMessage.objects.all().update(created_at=timezone.now() - timedelta(minutes=30))
        after_gap = self.client.post(
            reverse("accounts:chat_thread", args=[self.bob.username]),
            {"body": "Back from lecture!"},
            HTTP_X_LIVE_ACTION="1",
        )
        self.assertEqual(after_gap.status_code, 200)
        self.assertIn("chat-sep", after_gap.json()["message_html"])

        # 3. Edit within 15-minute window succeeds and marks edited_at
        latest_msg = DirectMessage.objects.order_by("-pk").first()
        edit_ok = self.client.post(
            reverse("accounts:chat_message_edit", args=[latest_msg.pk]),
            {"body": "Back from lecture (updated)!"},
            HTTP_X_LIVE_ACTION="1",
        )
        self.assertEqual(edit_ok.status_code, 200)
        self.assertTrue(edit_ok.json()["ok"])
        latest_msg.refresh_from_db()
        self.assertEqual(latest_msg.body, "Back from lecture (updated)!")
        self.assertIsNotNone(latest_msg.edited_at)

        # 4. Edit after 15-minute window is rejected
        oldest_msg = DirectMessage.objects.order_by("pk").first()
        edit_expired = self.client.post(
            reverse("accounts:chat_message_edit", args=[oldest_msg.pk]),
            {"body": "Too late to edit"},
            HTTP_X_LIVE_ACTION="1",
        )
        self.assertEqual(edit_expired.status_code, 400)
        self.assertFalse(edit_expired.json()["ok"])

        # 5. Delete message marks is_deleted=True and clears body
        del_resp = self.client.post(
            reverse("accounts:chat_message_delete", args=[latest_msg.pk]),
            HTTP_X_LIVE_ACTION="1",
        )
        self.assertEqual(del_resp.status_code, 200)
        self.assertTrue(del_resp.json()["ok"])
        latest_msg.refresh_from_db()
        self.assertTrue(latest_msg.is_deleted)
        self.assertEqual(latest_msg.body, "")

        # 6. Floating Quick-Chat Dock renders both conversation list and partner thread
        dock_list = self.client.get(reverse("accounts:chat_dock"))
        self.assertEqual(dock_list.status_code, 200)
        self.assertContains(dock_list, "Quick Chat")

        dock_thread = self.client.get(reverse("accounts:chat_dock_thread", args=[self.bob.username]))
        self.assertEqual(dock_thread.status_code, 200)
        self.assertContains(dock_thread, "This message was deleted.")






