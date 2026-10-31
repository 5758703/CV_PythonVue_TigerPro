"""Stable membership sources and complete, independently revocable grants."""
from datetime import datetime

from extensions import db


class OrgMembership(db.Model):
    __tablename__ = "sys_org_membership"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("sys_user.id"), nullable=False, index=True)
    org_id = db.Column(db.Integer, db.ForeignKey("sys_dept.id"), nullable=False, index=True)
    member_kind = db.Column(db.String(64), nullable=False, default="MEMBER")
    is_primary = db.Column(db.Boolean, nullable=False, default=False)
    valid_from = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    valid_to = db.Column(db.DateTime)
    status = db.Column(db.String(1), nullable=False, default="0")
    user = db.relationship("User", foreign_keys=[user_id])
    org = db.relationship("Dept", foreign_keys=[org_id])

    def to_dict(self):
        return dict(id=self.id, userId=self.user_id, orgId=self.org_id,
                    orgName=self.org.dept_name, orgType=self.org.org_type,
                    memberKind=self.member_kind, isPrimary=self.is_primary,
                    validFrom=self.valid_from.isoformat(),
                    validTo=self.valid_to.isoformat() if self.valid_to else None, status=self.status)


class OrgGrant(db.Model):
    __tablename__ = "sys_org_grant"
    id = db.Column(db.Integer, primary_key=True)
    membership_id = db.Column(db.Integer, db.ForeignKey("sys_org_membership.id"), nullable=False, index=True)
    role_id = db.Column(db.Integer, db.ForeignKey("sys_role.id"), nullable=False, index=True)
    scope_type = db.Column(db.String(32), nullable=False, default="ORG")
    scope_anchor_org_id = db.Column(db.Integer, db.ForeignKey("sys_dept.id"))
    scope_org_ids = db.Column(db.JSON, nullable=False, default=list)
    source_type = db.Column(db.String(32), nullable=False, default="MEMBERSHIP")
    source_ref = db.Column(db.String(128), nullable=False, default="")
    approval_ref = db.Column(db.String(255))
    valid_from = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    valid_to = db.Column(db.DateTime)
    status = db.Column(db.String(1), nullable=False, default="0")
    granted_by = db.Column(db.Integer, db.ForeignKey("sys_user.id"), nullable=False)
    membership = db.relationship("OrgMembership", foreign_keys=[membership_id])
    role = db.relationship("Role", foreign_keys=[role_id])

    def to_dict(self):
        return dict(id=self.id, membershipId=self.membership_id, roleId=self.role_id,
                    roleName=self.role.role_name, businessDomain=self.role.business_domain,
                    contextOrgId=self.membership.org_id, scopeType=self.scope_type,
                    scopeAnchorOrgId=self.scope_anchor_org_id, scopeOrgIds=self.scope_org_ids or [],
                    sourceType=self.source_type, sourceRef=self.source_ref, approvalRef=self.approval_ref,
                    validFrom=self.valid_from.isoformat(),
                    validTo=self.valid_to.isoformat() if self.valid_to else None, status=self.status)


class OrgAuthAudit(db.Model):
    __tablename__ = "sys_org_auth_audit"
    id = db.Column(db.Integer, primary_key=True)
    actor_id = db.Column(db.Integer, nullable=False)
    subject_id = db.Column(db.Integer, index=True)
    event_type = db.Column(db.String(64), nullable=False)
    detail = db.Column(db.JSON, nullable=False, default=dict)
    occurred_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def to_dict(self):
        return dict(id=self.id, actorId=self.actor_id, subjectId=self.subject_id,
                    eventType=self.event_type, detail=self.detail, occurredAt=self.occurred_at.isoformat())
