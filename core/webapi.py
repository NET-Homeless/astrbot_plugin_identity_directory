"""Web API handlers for the directory management UI."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from astrbot.api.web import error_response, json_response, request

from . import serializers as ser
from .errors import DirectoryConflictError, DirectoryError, DirectoryNotFoundError

if TYPE_CHECKING:
    from .service import DirectoryService


def _str_field(payload: dict[str, Any], key: str, default: str = "") -> str:
    value = payload.get(key, default)
    return str(value).strip() if isinstance(value, (str, int, float)) else default


def _bool_field(payload: dict[str, Any], key: str, default: bool = False) -> bool:
    value = payload.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().casefold() not in {"", "0", "false", "no", "off"}
    return bool(value)


async def _read_json_object() -> dict[str, Any] | None:
    try:
        payload = await request.json(default=None)
    except (TypeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _bad_json_response():
    return error_response("request body must be a JSON object", status_code=400)


def _directory_error_response(exc: DirectoryError):
    if isinstance(exc, DirectoryNotFoundError):
        status_code = 404
    elif isinstance(exc, DirectoryConflictError):
        status_code = 409
    else:
        status_code = 400
    return error_response(str(exc), status_code=status_code)


class DirectoryWebApi:
    def __init__(self, service: DirectoryService) -> None:
        self._service = service

    # ---------------- stats ----------------

    async def stats(self):
        return json_response(await self._service.stats())

    async def repair_unlinked(self):
        repaired = await self._service.repair_unlinked_accounts()
        return json_response({"repaired": repaired})

    # ---------------- persons ----------------

    async def list_persons(self):
        query = request.query.get("q", "").strip()
        include_archived = request.query.get("archived", "0") == "1"
        limit = request.query.get("limit", 50, type=int)
        offset = request.query.get("offset", 0, type=int)
        limit = max(1, min(limit or 50, 200))
        persons, total = await self._service.list_persons(
            query=query,
            include_archived=include_archived,
            limit=limit,
            offset=max(0, offset or 0),
        )
        return json_response({"items": [ser.person_to_dict(person) for person in persons], "total": total})

    async def create_person(self):
        payload = await _read_json_object()
        if payload is None:
            return _bad_json_response()
        name = _str_field(payload, "canonical_name")
        if not name:
            return error_response("canonical_name is required", status_code=400)
        raw_tags = payload.get("tags", [])
        if not isinstance(raw_tags, list):
            return error_response("tags must be an array", status_code=400)
        try:
            person = await self._service.create_person(
                name,
                notes=_str_field(payload, "notes"),
                tags=[str(tag) for tag in raw_tags],
                is_bot=_bool_field(payload, "is_bot"),
            )
        except DirectoryError as exc:
            return _directory_error_response(exc)
        return json_response(ser.person_to_dict(person))

    async def get_person(self, person_id: str):
        view = await self._service.get_person_view(person_id)
        if view is None:
            return error_response("person not found", status_code=404)
        return json_response(ser.person_view_to_dict(view))

    async def update_person(self, person_id: str):
        payload = await _read_json_object()
        if payload is None:
            return _bad_json_response()
        fields: dict[str, Any] = {}
        if "canonical_name" in payload:
            name = _str_field(payload, "canonical_name")
            if not name:
                return error_response("canonical_name must not be empty", status_code=400)
            fields["canonical_name"] = name
        if "notes" in payload:
            fields["notes"] = _str_field(payload, "notes")
        if "tags" in payload:
            if not isinstance(payload["tags"], list):
                return error_response("tags must be an array", status_code=400)
            fields["tags"] = [str(tag) for tag in payload["tags"]]
        if "is_bot" in payload:
            fields["is_bot"] = _bool_field(payload, "is_bot")
        if "is_archived" in payload:
            fields["is_archived"] = _bool_field(payload, "is_archived")
        try:
            person = await self._service.update_person(person_id, **fields)
        except DirectoryError as exc:
            return _directory_error_response(exc)
        if person is None:
            return error_response("person not found", status_code=404)
        return json_response(ser.person_to_dict(person))

    async def delete_person(self, person_id: str):
        try:
            deleted = await self._service.delete_person(person_id)
        except DirectoryError as exc:
            return _directory_error_response(exc)
        if not deleted:
            return error_response("person not found", status_code=404)
        return json_response({"deleted": True})

    async def merge_persons(self):
        payload = await _read_json_object()
        if payload is None:
            return _bad_json_response()
        target = _str_field(payload, "target_person_id")
        raw_sources = payload.get("source_person_ids")
        if raw_sources is None:
            raw_sources = payload.get("source_person_id")
        if isinstance(raw_sources, list):
            if not all(isinstance(source, (str, int, float)) for source in raw_sources):
                return error_response("source_person_ids must contain scalar IDs", status_code=400)
            source_ids = [str(source).strip() for source in raw_sources if str(source).strip()]
        elif isinstance(raw_sources, (str, int, float)) and str(raw_sources).strip():
            source_ids = [str(raw_sources).strip()]
        else:
            source_ids = []

        if not target:
            return error_response("target_person_id is required", status_code=400)
        source_ids = list(dict.fromkeys(source_id for source_id in source_ids if source_id != target))
        if not source_ids:
            return error_response("source and target must differ", status_code=400)

        try:
            merged_count = await self._service.merge_multiple_persons(source_ids, target)
        except DirectoryError as exc:
            return _directory_error_response(exc)
        view = await self._service.get_person_view(target)
        return json_response(
            ser.person_view_to_dict(view) if view else {"merged": True, "count": merged_count}
        )

    # ---------------- accounts ----------------

    async def list_accounts(self):
        unlinked = request.query.get("unlinked", "0") == "1"
        platform = request.query.get("platform", "").strip() or None
        platform_instance_id = request.query.get("platform_instance_id", "").strip() or None
        query = request.query.get("q", "").strip()
        limit = request.query.get("limit", 100, type=int)
        offset = request.query.get("offset", 0, type=int)
        views, total = await self._service.list_account_views(
            unlinked=unlinked,
            platform=platform,
            platform_instance_id=platform_instance_id,
            query=query,
            limit=max(1, min(limit or 100, 200)),
            offset=max(0, offset or 0),
        )
        return json_response({"items": [ser.account_view_to_dict(view) for view in views], "total": total})

    async def link_account(self, account_id: str):
        payload = await _read_json_object()
        if payload is None:
            return _bad_json_response()
        person_id = _str_field(payload, "person_id")
        if not person_id:
            return error_response("person_id is required", status_code=400)
        try:
            await self._service.link_account(account_id, person_id)
        except DirectoryError as exc:
            return _directory_error_response(exc)
        return json_response({"linked": True})

    async def unlink_account(self, account_id: str):
        if not await self._service.unlink_account(account_id):
            return error_response("account not found", status_code=404)
        return json_response({"unlinked": True, "auto_stub_suppressed": True})

    async def delete_account(self, account_id: str):
        if not await self._service.delete_account(account_id):
            return error_response("account not found", status_code=404)
        return json_response({"deleted": True})

    # ---------------- aliases ----------------

    async def list_aliases(self, account_id: str):
        if await self._service.get_account(account_id) is None:
            return error_response("account not found", status_code=404)
        aliases = await self._service.list_aliases(account_id)
        return json_response({"items": [ser.alias_to_dict(alias) for alias in aliases]})

    async def add_alias(self, account_id: str):
        payload = await _read_json_object()
        if payload is None:
            return _bad_json_response()
        name = _str_field(payload, "name")
        platform = _str_field(payload, "platform")
        group_id = _str_field(payload, "group_id") or None
        if not name or not platform:
            return error_response("name and platform are required", status_code=400)
        try:
            alias = await self._service.add_alias(account_id, name, platform, group_id)
        except DirectoryError as exc:
            return _directory_error_response(exc)
        if alias is None:
            return error_response("name must not be empty", status_code=400)
        return json_response(ser.alias_to_dict(alias))

    async def delete_alias(self, alias_id: str):
        if not await self._service.delete_alias(alias_id):
            return error_response("alias not found", status_code=404)
        return json_response({"deleted": True})

    # ---------------- memberships ----------------

    async def update_membership(self, membership_id: str):
        payload = await _read_json_object()
        if payload is None:
            return _bad_json_response()
        card = _str_field(payload, "current_card")
        if not await self._service.update_membership_card(membership_id, card):
            return error_response("membership not found", status_code=404)
        return json_response({"updated": True})

    async def delete_membership(self, membership_id: str):
        if not await self._service.delete_membership(membership_id):
            return error_response("membership not found", status_code=404)
        return json_response({"deleted": True})

    # ---------------- lookup (for other consumers / debugging) ----------------

    async def resolve(self):
        platform = request.query.get("platform", "").strip()
        platform_instance_id = request.query.get("platform_instance_id", "").strip() or None
        user_id = request.query.get("user_id", "").strip()
        group_id = request.query.get("group_id", "").strip() or None
        if not platform or not user_id:
            return error_response("platform and user_id are required", status_code=400)
        resolution = await self._service.resolve_sender(
            platform,
            user_id,
            group_id,
            platform_instance_id=platform_instance_id,
        )
        if resolution is None:
            return error_response("account not found", status_code=404)
        return json_response(ser.resolution_to_dict(resolution))

    async def find_by_name(self):
        name = request.query.get("name", "").strip()
        platform = request.query.get("platform", "").strip() or None
        platform_instance_id = request.query.get("platform_instance_id", "").strip() or None
        group_id = request.query.get("group_id", "").strip() or None
        if not name:
            return error_response("name is required", status_code=400)
        candidates = await self._service.find_by_name(
            name,
            platform=platform,
            platform_instance_id=platform_instance_id,
            group_id=group_id,
        )
        return json_response(
            {
                "items": [
                    {
                        "person": ser.person_to_dict(candidate.person),
                        "account": ser.account_to_dict(candidate.account),
                        "matched_name": candidate.matched_name,
                        "in_group": candidate.in_group,
                    }
                    for candidate in candidates
                ]
            }
        )
