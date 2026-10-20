from django import forms
from django.conf import settings
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.core.files.uploadedfile import UploadedFile

from pans_agora.utils import process_chat_media, process_image

from .models import User


class RegistrationForm(UserCreationForm):
    email = forms.EmailField(
        help_text="Used for password resets. Never shown publicly.",
        widget=forms.EmailInput(attrs={"autocomplete": "email"}),
    )
    accept_guidelines = forms.BooleanField(
        required=True, label="I agree to follow the community guidelines"
    )
    # Honeypot: real users never see or fill this field.
    website = forms.CharField(required=False, label="Leave this empty", widget=forms.TextInput(attrs={"tabindex": "-1", "autocomplete": "off"}))

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].help_text = "Letters, digits and @/./+/-/_ only. 150 characters max."
        self.fields["username"].widget.attrs.update({"autocomplete": "username", "autofocus": True})

    def clean_website(self):
        if self.cleaned_data.get("website"):
            raise forms.ValidationError("Please leave this field empty.")
        return ""

    def clean_username(self):
        username = self.cleaned_data["username"]
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("That username is already taken.")
        return username

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email


class LoginForm(AuthenticationForm):
    username = forms.CharField(
        label="Username or email",
        max_length=254,
        widget=forms.TextInput(attrs={"autofocus": True, "autocomplete": "username"}),
    )
    error_messages = {
        "invalid_login": "That username/email and password combination didn't work. Please try again.",
        "inactive": "This account is inactive.",
    }


class ProfileForm(forms.ModelForm):
    avatar = forms.ImageField(
        required=False,
        widget=forms.FileInput(attrs={"accept": "image/jpeg,image/png,image/gif,image/webp", "data-preview": "avatar-preview"}),
        help_text="Square images look best. JPEG, PNG, GIF or WebP, up to 3 MB.",
    )
    banner = forms.ImageField(
        required=False,
        widget=forms.FileInput(attrs={"accept": "image/jpeg,image/png,image/gif,image/webp", "data-preview": "banner-preview"}),
        help_text="Wide images work best (3:1). Up to 5 MB.",
    )
    remove_avatar = forms.BooleanField(required=False, label="Remove current avatar")
    remove_banner = forms.BooleanField(required=False, label="Remove current banner image")

    class Meta:
        model = User
        fields = ["display_name", "field_of_study", "year_of_study", "bio", "avatar", "banner", "banner_theme"]
        widgets = {
            "bio": forms.Textarea(attrs={"rows": 4, "maxlength": 500}),
            "banner_theme": forms.RadioSelect,
        }
        labels = {"banner_theme": "Banner colour (used when no image is set)"}
        help_texts = {"display_name": "Shown instead of your username. Optional."}

    def clean_avatar(self):
        f = self.cleaned_data.get("avatar")
        if isinstance(f, UploadedFile):
            return process_image(f, (256, 256), settings.AVATAR_MAX_BYTES)
        return f

    def clean_banner(self):
        f = self.cleaned_data.get("banner")
        if isinstance(f, UploadedFile):
            return process_image(f, (1500, 500), settings.BANNER_MAX_BYTES)
        return f

    def save(self, commit=True):
        user = super().save(commit=False)
        if self.cleaned_data.get("remove_avatar") and "avatar" not in self.files:
            user.avatar = None
        if self.cleaned_data.get("remove_banner") and "banner" not in self.files:
            user.banner = None
        if commit:
            user.save()
        return user


class EmailChangeForm(forms.Form):
    email = forms.EmailField(label="New email address", widget=forms.EmailInput(attrs={"autocomplete": "email"}))
    current_password = forms.CharField(
        label="Current password", strip=False, widget=forms.PasswordInput(attrs={"autocomplete": "current-password"})
    )

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_current_password(self):
        password = self.cleaned_data["current_password"]
        if not self.user.check_password(password):
            raise forms.ValidationError("Your password was entered incorrectly.")
        return password

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exclude(pk=self.user.pk).exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email


class DeleteAccountForm(forms.Form):
    password = forms.CharField(
        label="Confirm with your password", strip=False, widget=forms.PasswordInput(attrs={"autocomplete": "current-password"})
    )
    confirm = forms.BooleanField(label="I understand this permanently deletes my account")

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_password(self):
        password = self.cleaned_data["password"]
        if not self.user.check_password(password):
            raise forms.ValidationError("Your password was entered incorrectly.")
        return password


class DirectMessageForm(forms.Form):
    body = forms.CharField(
        label="Message",
        required=False,
        max_length=4000,
        widget=forms.Textarea(
            attrs={"rows": 2, "maxlength": 4000, "placeholder": "Write a message…", "autofocus": True}
        ),
    )
    attachment = forms.FileField(required=False)

    def clean_body(self):
        return (self.cleaned_data.get("body") or "").strip()

    def clean_attachment(self):
        f = self.cleaned_data.get("attachment")
        if isinstance(f, UploadedFile):
            return process_chat_media(f)
        return None

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("body") and not cleaned.get("attachment"):
            raise forms.ValidationError("Message cannot be empty.")
        return cleaned



