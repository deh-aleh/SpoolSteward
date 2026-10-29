"""the whole schema

First and only migration of the project: every later one starts from here. Written from the models and checked against them
(tests/test_migrations.py compares both), so a change to a model needs its own migration after this one.

Revision ID: 0001
Revises:
"""
from alembic import op
import sqlalchemy as sa

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('audit_archive',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('source_table', sa.String(length=32), nullable=False),
    sa.Column('path', sa.String(length=512), nullable=False),
    sa.Column('first_ts', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_ts', sa.DateTime(timezone=True), nullable=False),
    sa.Column('first_id', sa.Integer(), nullable=False),
    sa.Column('last_id', sa.Integer(), nullable=False),
    sa.Column('rows', sa.Integer(), nullable=False),
    sa.Column('bytes', sa.Integer(), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('gateway_setting',
    sa.Column('key', sa.String(length=64), nullable=False),
    sa.Column('value', sa.String(length=255), server_default=sa.text("''"), nullable=False),
    sa.PrimaryKeyConstraint('key')
    )
    op.create_table('group',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=64), nullable=False),
    sa.Column('requestable', sa.Boolean(), server_default=sa.text('0'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )
    op.create_table('notice',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(length=48), nullable=False),
    sa.Column('key', sa.String(length=128), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('first_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('count', sa.Integer(), nullable=False),
    sa.Column('detail_json', sa.JSON(), nullable=True),
    sa.Column('dismissed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('dismissed_by', sa.String(length=128), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sqlite_autoincrement=True
    )
    with op.batch_alter_table('notice', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_notice_kind'), ['kind'], unique=False)
        batch_op.create_index(batch_op.f('ix_notice_user_id'), ['user_id'], unique=False)

    op.create_table('permission_rule',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('subject_type', sa.Enum('user', 'group', name='subjecttype'), nullable=False),
    sa.Column('subject_id', sa.Integer(), nullable=False),
    sa.Column('color', sa.Boolean(), nullable=True),
    sa.Column('one_sided', sa.Boolean(), nullable=True),
    sa.Column('printers_mode', sa.String(length=8), nullable=True),
    sa.Column('printers', sa.JSON(), nullable=True),
    sa.Column('hours_mode', sa.String(length=8), nullable=True),
    sa.Column('hours_days', sa.String(length=7), nullable=True),
    sa.Column('hours_start', sa.Integer(), nullable=True),
    sa.Column('hours_end', sa.Integer(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('subject_type', 'subject_id')
    )
    op.create_table('policy_rule',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('subject_type', sa.Enum('user', 'group', name='subjecttype'), nullable=False),
    sa.Column('subject_id', sa.Integer(), nullable=False),
    sa.Column('resource', sa.Enum('print', 'scan', name='resource'), nullable=False),
    sa.Column('metric', sa.Enum('jobs', 'pages', name='metric'), nullable=False),
    sa.Column('limit', sa.Integer(), nullable=False),
    sa.Column('period', sa.Enum('weekly', 'monthly', name='period'), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('subject_type', 'subject_id', 'resource', 'metric')
    )
    op.create_table('printer_control',
    sa.Column('printer', sa.String(length=128), nullable=False),
    sa.Column('blocked', sa.Boolean(), server_default=sa.text('0'), nullable=False),
    sa.Column('mdns_hidden', sa.Boolean(), server_default=sa.text('0'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('printer')
    )
    op.create_table('printer_former',
    sa.Column('name', sa.String(length=128), nullable=False),
    sa.Column('display', sa.String(length=128), nullable=False),
    sa.Column('removed_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('reason', sa.String(length=16), nullable=False),
    sa.PrimaryKeyConstraint('name')
    )
    op.create_table('printer_keepalive',
    sa.Column('printer', sa.String(length=128), nullable=False),
    sa.Column('enabled', sa.Boolean(), server_default=sa.text('0'), nullable=False),
    sa.Column('interval_hours', sa.Integer(), server_default='168', nullable=False),
    sa.Column('color', sa.Boolean(), server_default=sa.text('0'), nullable=False),
    sa.Column('enabled_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_job_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_color_job_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_attempt_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_ok_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_status', sa.String(length=8), nullable=True),
    sa.Column('last_error', sa.String(length=500), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_by', sa.String(length=128), server_default=sa.text("''"), nullable=False),
    sa.PrimaryKeyConstraint('printer')
    )
    op.create_table('printer_offline',
    sa.Column('printer', sa.String(length=128), nullable=False),
    sa.Column('since', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('printer')
    )
    op.create_table('printer_seen',
    sa.Column('printer', sa.String(length=128), nullable=False),
    sa.Column('first_seen', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('printer')
    )
    op.create_table('user',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('provider', sa.String(length=32), nullable=False),
    sa.Column('username', sa.String(length=128), nullable=False),
    sa.Column('is_admin', sa.Boolean(), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('group_id', sa.Integer(), nullable=True),
    sa.Column('password_hash', sa.String(length=255), nullable=True),
    sa.Column('must_change_password', sa.Boolean(), server_default=sa.text('0'), nullable=False),
    sa.Column('password_changed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('theme', sa.String(length=8), server_default='auto', nullable=False),
    sa.Column('language', sa.String(length=8), nullable=True),
    sa.Column('notices_seen_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('own_notices_seen_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('refresh_seconds', sa.Integer(), server_default='30', nullable=False),
    sa.Column('secondary_read_minutes', sa.Integer(), server_default='20', nullable=False),
    sa.ForeignKeyConstraint(['group_id'], ['group.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('username', name='uq_user_username'),
    sqlite_autoincrement=True
    )
    op.create_table('admin_audit',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('ts', sa.DateTime(timezone=True), nullable=False),
    sa.Column('actor_id', sa.Integer(), nullable=True),
    sa.Column('actor_name', sa.String(length=128), nullable=False),
    sa.Column('action', sa.String(length=64), nullable=False),
    sa.Column('target_type', sa.String(length=32), nullable=True),
    sa.Column('target_id', sa.Integer(), nullable=True),
    sa.Column('detail_json', sa.JSON(), nullable=True),
    sa.ForeignKeyConstraint(['actor_id'], ['user.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sqlite_autoincrement=True
    )
    with op.batch_alter_table('admin_audit', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_admin_audit_ts'), ['ts'], unique=False)

    op.create_table('backup_target',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('owner_id', sa.Integer(), nullable=True),
    sa.Column('owner_name', sa.String(length=128), server_default=sa.text("''"), nullable=False),
    sa.Column('is_global', sa.Boolean(), server_default=sa.text('0'), nullable=False),
    sa.Column('name', sa.String(length=80), nullable=False),
    sa.Column('folder', sa.String(length=200), nullable=False),
    sa.Column('enabled', sa.Boolean(), server_default=sa.text('1'), nullable=False),
    sa.Column('require_marker', sa.Boolean(), server_default=sa.text('0'), nullable=False),
    sa.Column('hour', sa.Integer(), server_default='3', nullable=False),
    sa.Column('keep_daily', sa.Integer(), server_default='7', nullable=False),
    sa.Column('keep_weekly', sa.Integer(), server_default='4', nullable=False),
    sa.Column('keep_monthly', sa.Integer(), server_default='12', nullable=False),
    sa.Column('mode', sa.String(length=16), server_default=sa.text("'none'"), nullable=False),
    sa.Column('recipient', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_attempt_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_ok_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_status', sa.String(length=8), nullable=True),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('last_file', sa.String(length=200), nullable=True),
    sa.Column('last_size', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['owner_id'], ['user.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sqlite_autoincrement=True
    )
    op.create_table('job_log',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('ts', sa.DateTime(timezone=True), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('user_name', sa.String(length=128), nullable=True),
    sa.Column('kind', sa.Enum('print', 'scan', name='jobkind'), nullable=False),
    sa.Column('printer', sa.String(length=128), nullable=True),
    sa.Column('cups_job_id', sa.Integer(), nullable=True),
    sa.Column('title', sa.String(length=512), nullable=True),
    sa.Column('pages', sa.Integer(), nullable=True),
    sa.Column('state', sa.Enum('accepted', 'denied', 'completed', 'failed', 'canceled', 'held', name='jobstate'), nullable=False),
    sa.Column('denied_reason', sa.String(length=256), nullable=True),
    sa.Column('options_json', sa.JSON(), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sqlite_autoincrement=True
    )
    with op.batch_alter_table('job_log', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_job_log_ts'), ['ts'], unique=False)
        batch_op.create_index(batch_op.f('ix_job_log_user_id'), ['user_id'], unique=False)

    op.create_table('print_key',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('label', sa.String(length=64), nullable=False),
    sa.Column('key_prefix', sa.String(length=16), nullable=False),
    sa.Column('key_hash', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_used_ip', sa.String(length=64), nullable=True),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('single_use', sa.Boolean(), server_default=sa.text('0'), nullable=False),
    sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('disabled_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('expiry_notified_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('key_hash')
    )
    with op.batch_alter_table('print_key', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_print_key_user_id'), ['user_id'], unique=False)

    op.create_table('printer_order',
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('printer', sa.String(length=128), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
    sa.PrimaryKeyConstraint('user_id', 'printer')
    )
    op.create_table('quota_request',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('kind', sa.Enum('quota', 'group_change', 'permission', name='requestkind'), nullable=False),
    sa.Column('scope', sa.Enum('temporary', 'permanent', name='requestscope'), nullable=True),
    sa.Column('params_json', sa.JSON(), nullable=True),
    sa.Column('reason', sa.String(length=500), nullable=False),
    sa.Column('status', sa.Enum('pending', 'approved', 'rejected', 'expired', 'canceled', name='requeststatus'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('decided_by', sa.Integer(), nullable=True),
    sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('decision_note', sa.String(length=500), nullable=True),
    sa.ForeignKeyConstraint(['decided_by'], ['user.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('quota_request', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_quota_request_status'), ['status'], unique=False)
        batch_op.create_index(batch_op.f('ix_quota_request_user_id'), ['user_id'], unique=False)

    op.create_table('registration',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('ip', sa.String(length=64), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id')
    )
    op.create_table('permission_grant',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('perm', sa.String(length=16), nullable=False),
    sa.Column('printer', sa.String(length=128), nullable=True),
    sa.Column('valid_from', sa.DateTime(timezone=True), nullable=False),
    sa.Column('valid_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('request_id', sa.Integer(), nullable=True),
    sa.Column('granted_by', sa.Integer(), nullable=True),
    sa.Column('note', sa.String(length=500), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('revoked_by', sa.Integer(), nullable=True),
    sa.Column('expiry_notified_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['granted_by'], ['user.id'], ),
    sa.ForeignKeyConstraint(['request_id'], ['quota_request.id'], ),
    sa.ForeignKeyConstraint(['revoked_by'], ['user.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('permission_grant', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_permission_grant_user_id'), ['user_id'], unique=False)

    op.create_table('quota_grant',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('metric', sa.Enum('jobs', 'pages', name='metric'), nullable=False),
    sa.Column('amount', sa.Integer(), nullable=False),
    sa.Column('scope', sa.Enum('temporary', 'permanent', name='requestscope'), nullable=False),
    sa.Column('valid_from', sa.DateTime(timezone=True), nullable=False),
    sa.Column('valid_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('request_id', sa.Integer(), nullable=True),
    sa.Column('granted_by', sa.Integer(), nullable=True),
    sa.Column('note', sa.String(length=500), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('revoked_by', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['granted_by'], ['user.id'], ),
    sa.ForeignKeyConstraint(['request_id'], ['quota_request.id'], ),
    sa.ForeignKeyConstraint(['revoked_by'], ['user.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('quota_grant', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_quota_grant_user_id'), ['user_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('quota_grant', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_quota_grant_user_id'))

    op.drop_table('quota_grant')
    with op.batch_alter_table('permission_grant', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_permission_grant_user_id'))

    op.drop_table('permission_grant')
    op.drop_table('registration')
    with op.batch_alter_table('quota_request', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_quota_request_user_id'))
        batch_op.drop_index(batch_op.f('ix_quota_request_status'))

    op.drop_table('quota_request')
    op.drop_table('printer_order')
    with op.batch_alter_table('print_key', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_print_key_user_id'))

    op.drop_table('print_key')
    with op.batch_alter_table('job_log', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_job_log_user_id'))
        batch_op.drop_index(batch_op.f('ix_job_log_ts'))

    op.drop_table('job_log')
    op.drop_table('backup_target')
    with op.batch_alter_table('admin_audit', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_admin_audit_ts'))

    op.drop_table('admin_audit')
    op.drop_table('user')
    op.drop_table('printer_seen')
    op.drop_table('printer_offline')
    op.drop_table('printer_keepalive')
    op.drop_table('printer_former')
    op.drop_table('printer_control')
    op.drop_table('policy_rule')
    op.drop_table('permission_rule')
    with op.batch_alter_table('notice', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_notice_user_id'))
        batch_op.drop_index(batch_op.f('ix_notice_kind'))

    op.drop_table('notice')
    op.drop_table('group')
    op.drop_table('gateway_setting')
    op.drop_table('audit_archive')
