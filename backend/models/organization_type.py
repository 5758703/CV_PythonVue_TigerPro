"""Editable organization catalog; codes remain stable for historical references."""
from sqlalchemy import event, select
from extensions import db


class OrgType(db.Model):
    __tablename__ = "sys_org_type"
    code = db.Column(db.String(16), primary_key=True)
    name = db.Column(db.String(64), nullable=False)
    order_num = db.Column(db.Integer, nullable=False, default=0)
    status = db.Column(db.String(1), nullable=False, default="0")
    supports_primary = db.Column(db.Boolean, nullable=False, default=False)
    archived = db.Column(db.Boolean, nullable=False, default=False)

    def to_dict(self):
        return dict(code=self.code, name=self.name, orderNum=self.order_num,
                    status=self.status, supportsPrimary=self.supports_primary, archived=self.archived)


@event.listens_for(OrgType.__table__, "after_create")
def initial_catalog(target, connection, **kwargs):
    # Initial data only: never reinsert deleted types or reset administrator edits.
    connection.execute(target.insert(), [
        dict(code="ADMIN", name="行政组织", order_num=10, status="0", supports_primary=True),
        dict(code="PARTY", name="党组织", order_num=20, status="0", supports_primary=False),
    ])


def default_org_type(context):
    table = OrgType.__table__
    return context.connection.execute(select(table.c.code).where(
        table.c.status == "0", table.c.archived.is_(False), table.c.supports_primary.is_(True)
    ).order_by(table.c.order_num, table.c.code)).scalar()
