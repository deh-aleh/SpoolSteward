"""The System page: maintenance, update, backups and the setting of the log, in one place."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from spoolsteward.admin import backups
from spoolsteward.admin.common import current_admin, get_db, render
from spoolsteward.db.models import AdminAudit, User
from spoolsteward.policy import control

router = APIRouter(prefix="/admin")


@router.get("/system", response_class=HTMLResponse)
def system_page(request: Request, admin: User = Depends(current_admin), db: Session = Depends(get_db)):
    ctx = backups.page_context(request, admin, db)
    since = None
    if control.is_maintenance(db):   # when it started: the latest time an administrator switched it on
        since = db.scalar(select(AdminAudit.ts).where(AdminAudit.action == "maintenance.on").order_by(AdminAudit.id.desc()).limit(1))
    return render(request, "system.html", admin, titles_on=control.titles_enabled(db), maint_since=since, **ctx)
