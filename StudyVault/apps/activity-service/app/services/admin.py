from __future__ import annotations

from fastapi import status

from studyvault_backend_common.errors import api_error
from studyvault_backend_common.logging import get_logger
from studyvault_backend_common.models import (
    AdminAuditEvent,
    AdminErrorRecord,
    AdminHealthSummary,
    AdminPasswordResetResult,
    AdminRegistrationSyncResult,
    AdminUserSummary,
    AuthenticatedUser,
    STUDYVAULT_ADMIN_ROLE,
)

from app.services.admin_integrations import AuditLogGateway, KeycloakAdminGateway, ServiceHealthGateway


logger = get_logger(__name__)
ADMIN_QUERY_LIMIT_MAX = 200


class AdminService:
    def __init__(
        self,
        *,
        keycloak: KeycloakAdminGateway,
        audit_logs: AuditLogGateway,
        service_health: ServiceHealthGateway,
        max_registered_users: int = 20,
    ) -> None:
        self.keycloak = keycloak
        self.audit_logs = audit_logs
        self.service_health = service_health
        self.max_registered_users = max_registered_users

    @staticmethod
    def require_admin(user: AuthenticatedUser) -> None:
        if not user.is_admin:
            raise api_error(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin access required",
                code="admin_access_required",
                category="permission",
            )

    async def list_users(self, actor: AuthenticatedUser) -> list[AdminUserSummary]:
        self.require_admin(actor)
        return await self.keycloak.list_users()

    async def set_user_enabled(self, actor: AuthenticatedUser, user_id: str, enabled: bool) -> AdminUserSummary:
        self.require_admin(actor)
        updated = await self.keycloak.set_enabled(user_id, enabled)
        logger.info(
            "admin updated user enabled state",
            event_name="admin_user_state_changed",
            event_category="admin",
            actor_user_id=actor.subject,
            actor_username=actor.username,
            actor_email=actor.email,
            target_user_id=updated.user_id,
            target_username=updated.username,
            target_email=updated.email,
            status="succeeded",
            metadata={"enabled": enabled},
        )
        return updated

    async def set_admin_role(self, actor: AuthenticatedUser, user_id: str, make_admin: bool) -> AdminUserSummary:
        self.require_admin(actor)
        updated = await self.keycloak.set_admin_role(user_id, make_admin)
        logger.info(
            "admin updated user role",
            event_name="admin_role_changed",
            event_category="admin",
            actor_user_id=actor.subject,
            actor_username=actor.username,
            actor_email=actor.email,
            target_user_id=updated.user_id,
            target_username=updated.username,
            target_email=updated.email,
            status="succeeded",
            metadata={"role": STUDYVAULT_ADMIN_ROLE, "granted": make_admin},
        )
        return updated

    async def reset_password(self, actor: AuthenticatedUser, user_id: str) -> AdminPasswordResetResult:
        self.require_admin(actor)
        result = await self.keycloak.reset_password(user_id)
        logger.info(
            "admin reset user password",
            event_name="admin_password_reset",
            event_category="admin",
            actor_user_id=actor.subject,
            actor_username=actor.username,
            actor_email=actor.email,
            target_user_id=result.user_id,
            target_username=result.username,
            target_email=None,
            status="succeeded",
        )
        return result

    async def sync_registration_limit(self, actor: AuthenticatedUser) -> AdminRegistrationSyncResult:
        self.require_admin(actor)
        users = await self.keycloak.list_users()
        current_user_count = len(users)
        should_allow_registration = current_user_count < self.max_registered_users
        current_registration_allowed = await self.keycloak.get_registration_allowed()
        changed = current_registration_allowed != should_allow_registration
        registration_allowed = current_registration_allowed
        if changed:
            registration_allowed = await self.keycloak.set_registration_allowed(should_allow_registration)
        logger.info(
            "admin synced registration limit",
            event_name="admin_registration_limit_synced",
            event_category="admin",
            actor_user_id=actor.subject,
            actor_username=actor.username,
            actor_email=actor.email,
            status="succeeded",
            metadata={
                "current_user_count": current_user_count,
                "max_registered_users": self.max_registered_users,
                "registration_allowed": registration_allowed,
                "changed": changed,
            },
        )
        return AdminRegistrationSyncResult(
            max_registered_users=self.max_registered_users,
            current_user_count=current_user_count,
            registration_allowed=registration_allowed,
            changed=changed,
        )

    async def list_audit_events(self, actor: AuthenticatedUser, limit: int = 100) -> list[AdminAuditEvent]:
        self.require_admin(actor)
        safe_limit = min(limit, ADMIN_QUERY_LIMIT_MAX)
        return await self.audit_logs.list_app_audit_events(safe_limit)

    async def health_summary(self, actor: AuthenticatedUser) -> AdminHealthSummary:
        self.require_admin(actor)
        users = await self.keycloak.list_users()
        counts = await self.audit_logs.summarize_counts()
        services = await self.service_health.check_services()
        return AdminHealthSummary(
            total_users=len(users),
            enabled_users=sum(1 for user in users if user.enabled),
            admin_users=sum(1 for user in users if user.is_admin),
            recent_uploads=counts.get("uploads", 0),
            recent_downloads=counts.get("downloads", 0),
            recent_searches=counts.get("searches", 0),
            recent_errors=counts.get("errors", 0),
            services=services,
        )

    async def recent_errors(self, actor: AuthenticatedUser, limit: int = 50) -> list[AdminErrorRecord]:
        self.require_admin(actor)
        return await self.audit_logs.list_recent_errors(min(limit, ADMIN_QUERY_LIMIT_MAX))
