"""Web API handlers for the directory management UI.

All routes are registered under /astrbot_plugin_identity_directory/... and
served through the AstrBot dashboard bridge (auth enforced by dashboard).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from astrbot.api.web import error_response, json_response, request

from . import serializers as ser

if TYPE_CHECKING:
    from .service import DirectoryService


def _str_field(payload: dict[str, Any], key: str, default: str = "") -> str:
    value = payload.get(key, default)
    return str(value).strip() if isinstance(value, (str, int, float)) else default


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
            query=query, include_archived=include_archived, limit=limit, offset=max(0, offset or 0)
        )
        return json_response({"items": [ser.person_to_dict(p) for p in persons], "total": total})

    async def create_person(self):
        payload = await request.json(default={})
        name = _str_field(payload, "canonical_name")
        if not name:
            return error_response("canonical_name is required", status_code=400)
        tags = payload.get("tags") if isinstance(payload.get("tags"), list) else []
        person = await self._service.create_person(
            name,
            notes=_str_field(payload, "notes"),
            tags=[str(t) for t in tags],
            is_bot=bool(payload.get("is_bot", False)),
        )
        return json_response(ser.person_to_dict(person))

    async def get_person(self, person_id: str):
        view = await self._service.get_person_view(person_id)
        if view is None:
            return error_response("person not found", status_code=404)
        return json_response(ser.person_view_to_dict(view))

    async def update_person(self, person_id: str):
        payload = await request.json(default={})
        fields: dict[str, Any] = {}
        if "canonical_name" in payload:
            name = _str_field(payload, "canonical_name")
            if not name:
                return error_response("canonical_name must not be empty", status_code=400)
            fields["canonical_name"] = name
        if "notes" in payload:
            fields["notes"] = str(payload.get("notes") or "")
        if "tags" in payload and isinstance(payload["tags"], list):
            fields["tags"] = [str(t) for t in payload["tags"]]
        if "is_bot" in payload:
            fields["is_bot"] = bool(payload["is_bot"])
        if "is_archived" in payload:
            fields["is_archived"] = bool(payload["is_archived"])
        person = await self._service.update_person(person_id, **fields)
        if person is None:
            return error_response("person not found", status_code=404)
        return json_response(ser.person_to_dict(person))

    async def delete_person(self, person_id: str):
        if not await self._service.delete_person(person_id):
            return error_response("person not found", status_code=404)
        return json_response({"deleted": True})

    async def merge_persons(self):
        payload = await request.json(default={})
        # Target person: the survivor (absorber)
        target = _str_field(payload, "target_person_id")

        # Source persons: the ones to be merged and deleted
        source_ids: list[str] = []

        # Support both plural (source_person_ids) and singular (source_person_id) keys
        raw_sources = payload.get("source_person_ids") or payload.get("source_person_id")

        if isinstance(raw_sources, list):
            source_ids = [str(sid).strip() for sid in raw_sources if str(sid).strip()]
        elif isinstance(raw_sources, str) and raw_sources.strip():
            source_ids = [raw_sources.strip()]

        if not target:
            return error_response("target_person_id is required", status_code=400)
        if not source_ids:
            return error_response("source_person_ids (or source_person_id) is required", status_code=400)

        # Filter out self-merge
        filtered_sources = [sid for sid in source_ids if sid != target]
        if not filtered_sources:
            return error_response("source and target must differ", status_code=400)

        merged_count = await self._service.merge_multiple_persons(filtered_sources, target)
        if merged_count == 0:
            return error_response("merge failed: target or sources not found", status_code=404)
        view = await self._service.get_person_view(target)
        return json_response(
            ser.person_view_to_dict(view) if view else {"merged": True, "count": merged_count}
        )

    # ---------------- accounts ----------------

    async def list_accounts(self):
        unlinked = request.query.get("unlinked", "0") == "1"
        platform = request.query.get("platform", "").strip() or None
        query = request.query.get("q", "").strip()
        limit = request.query.get("limit", 100, type=int)
        offset = request.query.get("offset", 0, type=int)
        views = await self._service.list_account_views(
            unlinked=unlinked,
            platform=platform,
            query=query,
            limit=max(1, min(limit or 100, 500)),
            offset=max(0, offset or 0),
        )
        return json_response({"items": [ser.account_view_to_dict(v) for v in views]})

    async def link_account(self, account_id: str):
        payload = await request.json(default={})
        person_id = _str_field(payload, "person_id")
        if not person_id:
            return error_response("person_id is required", status_code=400)
        if not await self._service.link_account(account_id, person_id):
            return error_response("account not found", status_code=404)
        return json_response({"linked": True})

    async def unlink_account(self, account_id: str):
        if not await self._service.unlink_account(account_id):
            return error_response("account not found", status_code=404)
        return json_response({"unlinked": True})

    async def delete_account(self, account_id: str):
        if not await self._service.delete_account(account_id):
            return error_response("account not found", status_code=404)
        return json_response({"deleted": True})

    # ---------------- aliases ----------------

    async def list_aliases(self, account_id: str):
        aliases = await self._service.list_aliases(account_id)
        return json_response({"items": [ser.alias_to_dict(a) for a in aliases]})

    async def add_alias(self, account_id: str):
        payload = await request.json(default={})
        name = _str_field(payload, "name")
        platform = _str_field(payload, "platform")
        group_id = _str_field(payload, "group_id") or None
        if not name or not platform:
            return error_response("name and platform are required", status_code=400)
        alias = await self._service.add_alias(account_id, name, platform, group_id)
        if alias is None:
            return error_response("failed to add alias", status_code=400)
        return json_response(ser.alias_to_dict(alias))

    async def delete_alias(self, alias_id: str):
        if not await self._service.delete_alias(alias_id):
            return error_response("alias not found", status_code=404)
        return json_response({"deleted": True})

    # ---------------- memberships ----------------

    async def update_membership(self, membership_id: str):
        payload = await request.json(default={})
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
        user_id = request.query.get("user_id", "").strip()
        group_id = request.query.get("group_id", "").strip() or None
        if not platform or not user_id:
            return error_response("platform and user_id are required", status_code=400)
        resolution = await self._service.resolve_sender(platform, user_id, group_id)
        if resolution is None:
            return error_response("account not found", status_code=404)
        return json_response(ser.resolution_to_dict(resolution))

    async def find_by_name(self):
        name = request.query.get("name", "").strip()
        platform = request.query.get("platform", "").strip() or None
        group_id = request.query.get("group_id", "").strip() or None
        if not name:
            return error_response("name is required", status_code=400)
        candidates = await self._service.find_by_name(name, platform=platform, group_id=group_id)
        return json_response(
            {
                "items": [
                    {
                        "person": ser.person_to_dict(c.person),
                        "account": ser.account_to_dict(c.account),
                        "matched_name": c.matched_name,
                        "in_group": c.in_group,
                    }
                    for c in candidates
                ]
            }
        )
