from fastapi import APIRouter


def protected_resource_router(
    resource_id: str, authorization_server: str, resource_name: str | None = None
) -> APIRouter:
    """RFC 9728 Protected Resource Metadata, served by the resource server itself.

    MCP clients hit this after getting a 401 from a protected endpoint, to learn
    which authorization server issues tokens this resource accepts.
    """
    router = APIRouter()

    @router.get("/.well-known/oauth-protected-resource")
    async def metadata():
        body = {
            "resource": resource_id,
            "authorization_servers": [authorization_server],
            "bearer_methods_supported": ["header"],
        }
        if resource_name:
            body["resource_name"] = resource_name
        return body

    return router
