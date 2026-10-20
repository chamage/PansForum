from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.db.models import Q


class UsernameOrEmailBackend(ModelBackend):
    """Authenticate with either username or email (both case-insensitive)."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        UserModel = get_user_model()
        if username is None:
            username = kwargs.get(UserModel.USERNAME_FIELD)
        if not username or not password:
            return None
        user = (
            UserModel.objects.filter(Q(username__iexact=username) | Q(email__iexact=username))
            .order_by("pk")
            .first()
        )
        if user is None:
            # Run the hasher anyway to reduce timing differences for unknown users.
            UserModel().set_password(password)
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
