"""Declarative platform capabilities for CreatorHub fork extensions.

Keep product rules here instead of adding more platform conditionals to the
upstream-heavy FastAPI entrypoint.  This module is side-effect free and must not
perform account, browser, or external platform operations.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class MediaCapability:
    title_max: int
    require_title: bool = True
    require_desc: bool = False
    min_media: int = 0
    max_media: int | None = None
    extensions: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class PlatformCapability:
    media: dict[str, MediaCapability]
    visibilities: frozenset[str]
    default_visibility: str
    operations: frozenset[str]
    default_operation: str
    supports_schedule: bool = True


_GENERIC_MEDIA = {
    "images": MediaCapability(title_max=20),
    "video": MediaCapability(title_max=20),
}
_GENERIC_VISIBILITY = frozenset({"public", "friends", "private"})
_GENERIC_OPERATIONS = frozenset({"draft", "publish"})


PLATFORM_CAPABILITIES: dict[str, PlatformCapability] = {
    "xhs": PlatformCapability(
        media=_GENERIC_MEDIA,
        visibilities=_GENERIC_VISIBILITY,
        default_visibility="public",
        operations=_GENERIC_OPERATIONS,
        default_operation="publish",
    ),
    "douyin": PlatformCapability(
        media=_GENERIC_MEDIA,
        visibilities=_GENERIC_VISIBILITY,
        default_visibility="public",
        operations=_GENERIC_OPERATIONS,
        default_operation="publish",
    ),
    "kuaishou": PlatformCapability(
        media=_GENERIC_MEDIA,
        visibilities=_GENERIC_VISIBILITY,
        default_visibility="public",
        operations=_GENERIC_OPERATIONS,
        default_operation="publish",
    ),
    "shipinhao": PlatformCapability(
        media=_GENERIC_MEDIA,
        visibilities=_GENERIC_VISIBILITY,
        default_visibility="public",
        operations=_GENERIC_OPERATIONS,
        default_operation="publish",
    ),
    "wechat_mp": PlatformCapability(
        media={
            "article": MediaCapability(title_max=64, require_desc=True),
            "images": MediaCapability(title_max=20, min_media=1),
            "video": MediaCapability(title_max=64, min_media=1, max_media=1),
            "podcast": MediaCapability(
                title_max=20,
                min_media=1,
                max_media=1,
                extensions=frozenset({".mp3", ".m4a", ".wav", ".amr", ".wma"}),
            ),
        },
        visibilities=_GENERIC_VISIBILITY,
        default_visibility="public",
        operations=frozenset({"draft"}),
        default_operation="draft",
    ),
    "youtube": PlatformCapability(
        media={"video": MediaCapability(title_max=100, min_media=1, max_media=1)},
        visibilities=frozenset({"private", "unlisted", "public"}),
        default_visibility="private",
        operations=frozenset({"upload"}),
        default_operation="upload",
        supports_schedule=False,
    ),
}


def capability_for(platform: str) -> PlatformCapability:
    key = str(platform or "").strip().lower()
    try:
        return PLATFORM_CAPABILITIES[key]
    except KeyError as exc:
        raise ValueError(f"unsupported platform: {platform}") from exc


def media_types_for(platform: str) -> tuple[str, ...]:
    return tuple(capability_for(platform).media)


def media_capability(platform: str, media_type: str) -> MediaCapability:
    capability = capability_for(platform)
    try:
        return capability.media[str(media_type or "").strip().lower()]
    except KeyError as exc:
        raise ValueError(f"unsupported media type for {platform}: {media_type}") from exc


def title_limit(platform: str, media_type: str) -> int:
    return media_capability(platform, media_type).title_max


def visibility_allowed(platform: str, visibility: str) -> bool:
    return str(visibility or "").strip().lower() in capability_for(platform).visibilities


def normalize_visibility(platform: str, visibility: str, *, explicitly_set: bool = True) -> str:
    capability = capability_for(platform)
    value = str(visibility or "").strip().lower()
    if explicitly_set and value in capability.visibilities:
        return value
    return capability.default_visibility


def normalize_operation(platform: str, operation: str) -> str:
    capability = capability_for(platform)
    value = str(operation or "").strip().lower()
    return value if value in capability.operations else capability.default_operation


def supports_schedule(platform: str) -> bool:
    return capability_for(platform).supports_schedule
