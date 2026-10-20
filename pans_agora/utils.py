"""Small, dependency-free helpers shared across apps."""
import uuid
from functools import wraps
from io import BytesIO

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from PIL import Image, ImageOps, UnidentifiedImageError

# ---------------------------------------------------------------------------
# Client IP + rate limiting
# ---------------------------------------------------------------------------


def client_ip(request):
    """Return the client IP, honouring X-Forwarded-For only for trusted proxies."""
    num_proxies = getattr(settings, "NUM_PROXIES", 0)
    if num_proxies:
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
        parts = [p.strip() for p in forwarded.split(",") if p.strip()]
        if len(parts) >= num_proxies:
            return parts[-num_proxies]
    return request.META.get("REMOTE_ADDR", "unknown")


def is_rate_limited(request, group, limit, period, by_user=True):
    """Fixed-window counter stored in the cache. Returns True when over the limit."""
    if not getattr(settings, "RATELIMIT_ENABLED", True):
        return False
    if by_user and request.user.is_authenticated:
        ident = f"u{request.user.pk}"
    else:
        ident = "ip" + client_ip(request).replace(":", "_")
    key = f"rl:{group}:{ident}"
    cache.add(key, 0, period)
    try:
        count = cache.incr(key)
    except ValueError:
        cache.set(key, 1, period)
        count = 1
    return count > limit


def ratelimit(group, limit, period, methods=("POST",), by_user=True):
    """View decorator: allow ``limit`` requests per ``period`` seconds."""

    def decorator(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if request.method in methods and is_rate_limited(request, group, limit, period, by_user):
                return render(request, "429.html", status=429)
            return view(request, *args, **kwargs)

        return wrapped

    return decorator


# ---------------------------------------------------------------------------
# Redirects
# ---------------------------------------------------------------------------


def safe_next(request, fallback):
    """Redirect to ?next= / POST next only if it points at this site."""
    target = request.POST.get("next") or request.GET.get("next")
    if target and url_has_allowed_host_and_scheme(
        target, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return redirect(target)
    return redirect(fallback)


# ---------------------------------------------------------------------------
# Image processing
# ---------------------------------------------------------------------------

Image.MAX_IMAGE_PIXELS = 40_000_000  # refuse decompression bombs
ALLOWED_IMAGE_FORMATS = {"JPEG", "PNG", "GIF", "WEBP"}


def process_image(uploaded, size, max_bytes):
    """Validate an uploaded image and re-encode it as a clean WebP.

    Re-encoding strips EXIF/GPS metadata and any payload hidden in the
    original file, and guarantees a predictable size and format.
    """
    if uploaded.size > max_bytes:
        raise ValidationError(f"Image must be smaller than {max_bytes // (1024 * 1024)} MB.")
    try:
        uploaded.seek(0)
        with Image.open(uploaded) as img:
            if img.format not in ALLOWED_IMAGE_FORMATS:
                raise ValidationError("Unsupported format. Please use JPEG, PNG, GIF or WebP.")
            img = ImageOps.exif_transpose(img)
            has_alpha = img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)
            img = img.convert("RGBA" if has_alpha else "RGB")
            img = ImageOps.fit(img, size, method=Image.Resampling.LANCZOS)
            buffer = BytesIO()
            img.save(buffer, format="WEBP", quality=85, method=4)
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, SyntaxError, ValueError):
        raise ValidationError("That file doesn't look like a valid image.")
    return ContentFile(buffer.getvalue(), name=f"{uuid.uuid4().hex}.webp")


def process_chat_media(uploaded, max_bytes=4 * 1024 * 1024):
    """Validate and sanitize a small image or animated GIF/WebP for friend DMs."""
    if uploaded.size > max_bytes:
        raise ValidationError(f"Media must be smaller than {max_bytes // (1024 * 1024)} MB.")
    try:
        uploaded.seek(0)
        with Image.open(uploaded) as img:
            fmt = img.format
            if fmt not in ALLOWED_IMAGE_FORMATS:
                raise ValidationError("Unsupported media format. Please upload a PNG, JPEG, WebP, or GIF.")
            is_animated = bool(getattr(img, "is_animated", False) and getattr(img, "n_frames", 1) > 1)
            if is_animated and fmt in ("GIF", "WEBP"):
                frames = []
                durations = []
                n_frames = min(getattr(img, "n_frames", 1), 80)
                for idx in range(n_frames):
                    img.seek(idx)
                    frame = img.convert("RGBA")
                    frame.thumbnail((480, 480), Image.Resampling.LANCZOS)
                    frames.append(frame)
                    durations.append(int(img.info.get("duration", 80)) or 80)
                buffer = BytesIO()
                frames[0].save(
                    buffer,
                    format="WEBP",
                    save_all=True,
                    append_images=frames[1:],
                    duration=durations,
                    loop=0,
                    quality=80,
                )
                return ContentFile(buffer.getvalue(), name=f"{uuid.uuid4().hex}.webp")

            img = ImageOps.exif_transpose(img)
            has_alpha = img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)
            img = img.convert("RGBA" if has_alpha else "RGB")
            img.thumbnail((960, 960), Image.Resampling.LANCZOS)
            buffer = BytesIO()
            img.save(buffer, format="WEBP", quality=85, method=4)
            return ContentFile(buffer.getvalue(), name=f"{uuid.uuid4().hex}.webp")
    except ValidationError:
        raise
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, SyntaxError, ValueError):
        raise ValidationError("That file doesn't look like a valid image or GIF.")

