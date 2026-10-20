import re

from django import forms
from django.utils.text import slugify

from .models import Comment, Community, CommunitySanction, Report, Thread

RESERVED_SLUGS = {"new", "all", "admin", "edit", "manage", "submit", "join", "leave", "mod", "mods", "sanctions", "reports", "settings"}


class CommunityForm(forms.ModelForm):
    class Meta:
        model = Community
        fields = ["name", "description"]
        widgets = {"description": forms.Textarea(attrs={"rows": 3, "maxlength": 500})}
        help_texts = {
            "name": "3–50 characters: letters, numbers, spaces, hyphens. E.g. “Linear Algebra”.",
            "description": "What is this community about?",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields["name"].disabled = True
            self.fields["name"].help_text = "Community names can't be changed."

    def clean_name(self):
        name = " ".join(self.cleaned_data["name"].split())
        if self.instance.pk:
            return self.instance.name
        if not re.fullmatch(r"[\w\- ]{3,50}", name):
            raise forms.ValidationError("Use 3–50 letters, numbers, spaces or hyphens.")
        slug = slugify(name)
        if not slug or slug in RESERVED_SLUGS:
            raise forms.ValidationError("Please choose a different name.")
        if Community.objects.filter(name__iexact=name).exists() or Community.objects.filter(slug=slug).exists():
            raise forms.ValidationError("A community with this name already exists.")
        return name


class ThreadForm(forms.ModelForm):
    class Meta:
        model = Thread
        fields = ["community", "title", "body"]
        widgets = {
            "title": forms.TextInput(attrs={"maxlength": 200, "placeholder": "An interesting, specific title", "autofocus": True}),
            "body": forms.Textarea(attrs={"rows": 10, "maxlength": 20000, "placeholder": "Share details, context, what you've tried… (optional)"}),
        }
        labels = {"body": "Text"}

    def __init__(self, *args, community=None, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        qs = Community.objects.order_by("name")
        if user and user.is_authenticated and not user.is_staff:
            restricted_ids = (
                CommunitySanction.objects.filter(user=user)
                .exclude(community__moderators=user)
                .values_list("community_id", flat=True)
            )
            qs = qs.exclude(pk__in=restricted_ids)
        self.fields["community"].queryset = qs
        self.fields["community"].empty_label = "Choose a community…"
        if community is not None:
            del self.fields["community"]

    def clean_title(self):
        title = " ".join(self.cleaned_data["title"].split())
        if len(title) < 5:
            raise forms.ValidationError("Titles need at least 5 characters.")
        return title


class ThreadEditForm(forms.ModelForm):
    class Meta:
        model = Thread
        fields = ["body"]
        widgets = {"body": forms.Textarea(attrs={"rows": 12, "maxlength": 20000})}
        labels = {"body": "Text"}


class CommentForm(forms.ModelForm):
    parent = forms.IntegerField(required=False, widget=forms.HiddenInput)

    class Meta:
        model = Comment
        fields = ["body"]
        widgets = {"body": forms.Textarea(attrs={"rows": 4, "maxlength": 10000, "placeholder": "Add to the discussion…"})}
        labels = {"body": "Comment"}

    def clean_body(self):
        body = self.cleaned_data["body"].strip()
        if not body:
            raise forms.ValidationError("Comments can't be empty.")
        return body


class ReportForm(forms.ModelForm):
    class Meta:
        model = Report
        fields = ["reason", "details"]
        widgets = {
            "reason": forms.RadioSelect,
            "details": forms.Textarea(attrs={"rows": 3, "maxlength": 1000, "placeholder": "Anything the moderators should know? (optional)"}),
        }
