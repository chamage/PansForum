from django import template
from django.utils.html import format_html, linebreaks, urlize
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter
def get_item(mapping, key):
    if not mapping:
        return None
    return mapping.get(key)


@register.filter
def render_body(text):
    """Escape user text, turn URLs into nofollow links and newlines into paragraphs."""
    if not text:
        return ""
    linked = urlize(text, trim_url_limit=60, nofollow=True, autoescape=True)
    return mark_safe(linebreaks(linked, autoescape=False))


@register.inclusion_tag("components/avatar.html")
def avatar(user, size="md"):
    if user is None or not getattr(user, "is_active", False):
        return {"user": None, "size": size, "initial": "?", "color": 0}
    return {"user": user, "size": size, "initial": user.initial, "color": (user.pk or 0) % 8}


@register.simple_tag
def user_link(user):
    if user is None or not user.is_active:
        return format_html('<span class="muted">[deleted]</span>')
    return format_html('<a class="userlink" href="{}">{}</a>', user.get_absolute_url(), user.name)
