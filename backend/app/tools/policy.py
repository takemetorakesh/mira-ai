from typing import Literal

from pydantic import BaseModel

from app.db import repo
from app.db.models import POLICY_KINDS
from app.tools.base import Tool, ToolContext, error


class PolicyArgs(BaseModel):
    property_id: str
    kind: Literal[POLICY_KINDS]


class GetPolicy(Tool):
    name = "get_policy"
    description = (
        "A property's policy on cancellation, check-in/out times, children, pets, smoking or payment. "
        "Quote it; don't paraphrase it into stronger promises."
    )
    Args = PolicyArgs

    async def run(self, ctx: ToolContext, args: PolicyArgs) -> dict:
        prop = await repo.get_property(ctx.session, args.property_id)
        if not prop:
            return error("not_found", f"Unknown property_id '{args.property_id}'.")
        details = await repo.get_policy(ctx.session, prop.id, args.kind)
        if details is None:
            return {
                "property_name": prop.name,
                "kind": args.kind,
                "known": False,
                "policies_on_file": await repo.policy_kinds(ctx.session, prop.id),
                "note": "Not on file. Tell the guest you don't know and offer to check with the property.",
            }
        return {"property_name": prop.name, "kind": args.kind, "known": True, "details": details}
