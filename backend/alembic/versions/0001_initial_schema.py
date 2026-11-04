"""The eighteen tables of blueprint §9: identity, catalogue, incidents and operations.

Generated from ``app.repositories.sqlalchemy.models``, so the models stay the single
description of the schema. ``tests/integration/test_migrations.py`` fails if the two drift.

Revision ID: 0001
Revises:
Create Date: 2026-11-04 04:16:40.706229+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from app.repositories.sqlalchemy import types as itsm

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "skills",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_skills")),
        sa.UniqueConstraint("name", name=op.f("uq_skills_name")),
    )
    op.create_table(
        "sla_policies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "tier",
            sa.Enum("gold", "silver", "bronze", name="sla_tier", native_enum=False, length=32),
            nullable=False,
        ),
        sa.Column(
            "priority",
            sa.Enum("P1", "P2", "P3", "P4", name="priority", native_enum=False, length=32),
            nullable=False,
        ),
        sa.Column("response", itsm.Seconds(), nullable=False),
        sa.Column("resolution", itsm.Seconds(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sla_policies")),
        sa.UniqueConstraint("tier", "priority", name=op.f("uq_sla_policies_tier_priority")),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=200), nullable=False),
        sa.Column(
            "role",
            sa.Enum(
                "employee",
                "technician",
                "team_lead",
                "administrator",
                "it_manager",
                name="role",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("password_hash", sa.String(length=255), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", itsm.UtcDateTime(), nullable=False),
        sa.Column("failed_login_count", sa.Integer(), nullable=False),
        sa.Column("locked_until", itsm.UtcDateTime(), nullable=True),
        sa.Column("telegram_chat_id", sa.String(length=64), nullable=True),
        sa.Column("google_subject", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("google_subject", name=op.f("uq_users_google_subject")),
    )
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_users_email"), ["email"], unique=True)
        batch_op.create_index(batch_op.f("ix_users_role"), ["role"], unique=False)

    op.create_table(
        "categories",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("required_skill_id", sa.Integer(), nullable=True),
        sa.Column("keywords", sa.JSON(), nullable=False),
        sa.Column(
            "minimum_priority",
            sa.Enum("P1", "P2", "P3", "P4", name="priority", native_enum=False, length=32),
            nullable=True,
        ),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["required_skill_id"],
            ["skills.id"],
            name=op.f("fk_categories_required_skill_id_skills"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_categories")),
        sa.UniqueConstraint("name", name=op.f("uq_categories_name")),
    )
    op.create_table(
        "services",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("criticality", sa.Integer(), nullable=False),
        sa.Column(
            "sla_tier",
            sa.Enum("gold", "silver", "bronze", name="sla_tier", native_enum=False, length=32),
            nullable=False,
        ),
        sa.Column("tier_overridden", sa.Boolean(), nullable=False),
        sa.Column("required_skill_id", sa.Integer(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.CheckConstraint(
            "criticality BETWEEN 1 AND 3", name=op.f("ck_services_criticality_between_1_and_3")
        ),
        sa.ForeignKeyConstraint(
            ["required_skill_id"], ["skills.id"], name=op.f("fk_services_required_skill_id_skills")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_services")),
        sa.UniqueConstraint("name", name=op.f("uq_services_name")),
    )
    op.create_table(
        "system_config",
        sa.Column("key", sa.String(length=80), nullable=False),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("updated_at", itsm.UtcDateTime(), nullable=True),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["updated_by"], ["users.id"], name=op.f("fk_system_config_updated_by_users")
        ),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_system_config")),
    )
    op.create_table(
        "teams",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("lead_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["lead_id"], ["users.id"], name=op.f("fk_teams_lead_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_teams")),
        sa.UniqueConstraint("name", name=op.f("uq_teams_name")),
    )
    op.create_table(
        "incidents",
        sa.Column("id", sa.String(length=20), nullable=False),
        sa.Column("reporter_id", sa.Integer(), nullable=False),
        sa.Column("assignee_id", sa.Integer(), nullable=True),
        sa.Column("category_id", sa.Integer(), nullable=True),
        sa.Column("service_id", sa.Integer(), nullable=False),
        sa.Column("parent_id", sa.String(length=20), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("impact", sa.Integer(), nullable=False),
        sa.Column("urgency", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "NEW",
                "CLASSIFIED",
                "ASSIGNED",
                "ACKNOWLEDGED",
                "IN_PROGRESS",
                "ON_HOLD",
                "RESOLVED",
                "VERIFIED",
                "CLOSED",
                "CANCELLED",
                name="incident_status",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "priority",
            sa.Enum("P1", "P2", "P3", "P4", name="priority", native_enum=False, length=32),
            nullable=True,
        ),
        sa.Column("priority_score", sa.Integer(), nullable=True),
        sa.Column("priority_overridden", sa.Boolean(), nullable=False),
        sa.Column(
            "cancel_reason",
            sa.Enum("withdrawn", "duplicate", name="cancel_reason", native_enum=False, length=32),
            nullable=True,
        ),
        sa.Column("created_at", itsm.UtcDateTime(), nullable=False),
        sa.Column("acknowledged_at", itsm.UtcDateTime(), nullable=True),
        sa.Column("resolved_at", itsm.UtcDateTime(), nullable=True),
        sa.Column("closed_at", itsm.UtcDateTime(), nullable=True),
        sa.Column("reopen_count", sa.Integer(), nullable=False),
        sa.Column("escalation_level", sa.Integer(), nullable=False),
        sa.Column("sla_started_at", itsm.UtcDateTime(), nullable=True),
        sa.Column("sla_response_target", itsm.Seconds(), nullable=True),
        sa.Column("sla_resolution_target", itsm.Seconds(), nullable=True),
        sa.Column("sla_responded_at", itsm.UtcDateTime(), nullable=True),
        sa.Column("sla_paused_total", itsm.Seconds(), nullable=True),
        sa.Column("sla_paused_since", itsm.UtcDateTime(), nullable=True),
        sa.Column("sla_stopped_at", itsm.UtcDateTime(), nullable=True),
        sa.Column("sla_response_met", sa.Boolean(), nullable=True),
        sa.Column("sla_resolution_target_at_stop", itsm.Seconds(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "impact BETWEEN 1 AND 3", name=op.f("ck_incidents_impact_between_1_and_3")
        ),
        sa.CheckConstraint(
            "urgency BETWEEN 1 AND 3", name=op.f("ck_incidents_urgency_between_1_and_3")
        ),
        sa.ForeignKeyConstraint(
            ["assignee_id"], ["users.id"], name=op.f("fk_incidents_assignee_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["category_id"], ["categories.id"], name=op.f("fk_incidents_category_id_categories")
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"], ["incidents.id"], name=op.f("fk_incidents_parent_id_incidents")
        ),
        sa.ForeignKeyConstraint(
            ["reporter_id"], ["users.id"], name=op.f("fk_incidents_reporter_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["service_id"], ["services.id"], name=op.f("fk_incidents_service_id_services")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_incidents")),
    )
    with op.batch_alter_table("incidents", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_incidents_assignee_id"), ["assignee_id"], unique=False)
        batch_op.create_index(
            "ix_incidents_assignee_id_status", ["assignee_id", "status"], unique=False
        )
        batch_op.create_index("ix_incidents_created_at", ["created_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_incidents_parent_id"), ["parent_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_incidents_priority"), ["priority"], unique=False)
        batch_op.create_index(batch_op.f("ix_incidents_reporter_id"), ["reporter_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_incidents_service_id"), ["service_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_incidents_status"), ["status"], unique=False)
        batch_op.create_index("ix_incidents_status_priority", ["status", "priority"], unique=False)

    op.create_table(
        "service_dependencies",
        sa.Column("service_id", sa.Integer(), nullable=False),
        sa.Column("depends_on_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "service_id <> depends_on_id", name=op.f("ck_service_dependencies_no_self_dependency")
        ),
        sa.ForeignKeyConstraint(
            ["depends_on_id"],
            ["services.id"],
            name=op.f("fk_service_dependencies_depends_on_id_services"),
        ),
        sa.ForeignKeyConstraint(
            ["service_id"],
            ["services.id"],
            name=op.f("fk_service_dependencies_service_id_services"),
        ),
        sa.PrimaryKeyConstraint(
            "service_id", "depends_on_id", name=op.f("pk_service_dependencies")
        ),
    )
    op.create_table(
        "technician_profiles",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("experience_level", sa.Integer(), nullable=False),
        sa.Column("available", sa.Boolean(), nullable=False),
        sa.Column("team_id", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "experience_level BETWEEN 1 AND 3",
            name=op.f("ck_technician_profiles_experience_level_between_1_and_3"),
        ),
        sa.ForeignKeyConstraint(
            ["team_id"], ["teams.id"], name=op.f("fk_technician_profiles_team_id_teams")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_technician_profiles_user_id_users")
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_technician_profiles")),
    )
    with op.batch_alter_table("technician_profiles", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_technician_profiles_team_id"), ["team_id"], unique=False
        )

    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("incident_id", sa.String(length=20), nullable=True),
        sa.Column("actor_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(length=60), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", itsm.UtcDateTime(), nullable=False),
        sa.Column("previous_hash", sa.String(length=64), nullable=True),
        sa.Column("hash", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["users.id"], name=op.f("fk_audit_log_actor_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["incident_id"],
            ["incidents.id"],
            name=op.f("fk_audit_log_incident_id_incidents"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_log")),
        sa.UniqueConstraint("hash", name=op.f("uq_audit_log_hash")),
    )
    with op.batch_alter_table("audit_log", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_audit_log_action"), ["action"], unique=False)
        batch_op.create_index("ix_audit_log_incident_id_id", ["incident_id", "id"], unique=False)

    op.create_table(
        "feedback",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("incident_id", sa.String(length=20), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=False),
        sa.Column("given_at", itsm.UtcDateTime(), nullable=False),
        sa.CheckConstraint(
            "rating BETWEEN 1 AND 5", name=op.f("ck_feedback_rating_between_1_and_5")
        ),
        sa.ForeignKeyConstraint(
            ["incident_id"], ["incidents.id"], name=op.f("fk_feedback_incident_id_incidents")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_feedback")),
        sa.UniqueConstraint("incident_id", name=op.f("uq_feedback_incident_id")),
    )
    op.create_table(
        "incident_embeddings",
        sa.Column("incident_id", sa.String(length=20), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("model", sa.String(length=80), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("vector", sa.JSON(), nullable=False),
        sa.Column("created_at", itsm.UtcDateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["incident_id"],
            ["incidents.id"],
            name=op.f("fk_incident_embeddings_incident_id_incidents"),
        ),
        sa.PrimaryKeyConstraint("incident_id", name=op.f("pk_incident_embeddings")),
    )
    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("incident_id", sa.String(length=20), nullable=True),
        sa.Column("event", sa.String(length=40), nullable=False),
        sa.Column("channel", sa.String(length=20), nullable=False),
        sa.Column("subject", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "sent",
                "failed",
                name="notification_status",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("created_at", itsm.UtcDateTime(), nullable=False),
        sa.Column("sent_at", itsm.UtcDateTime(), nullable=True),
        sa.Column("read_at", itsm.UtcDateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["incident_id"], ["incidents.id"], name=op.f("fk_notifications_incident_id_incidents")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_notifications_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notifications")),
    )
    with op.batch_alter_table("notifications", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_notifications_user_id"), ["user_id"], unique=False)
        batch_op.create_index(
            "ix_notifications_user_id_read_at", ["user_id", "read_at"], unique=False
        )

    op.create_table(
        "resolutions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("incident_id", sa.String(length=20), nullable=False),
        sa.Column("resolver_id", sa.Integer(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("resolved_at", itsm.UtcDateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["incident_id"], ["incidents.id"], name=op.f("fk_resolutions_incident_id_incidents")
        ),
        sa.ForeignKeyConstraint(
            ["resolver_id"], ["users.id"], name=op.f("fk_resolutions_resolver_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_resolutions")),
        sa.UniqueConstraint("incident_id", name=op.f("uq_resolutions_incident_id")),
    )
    op.create_table(
        "sla_violations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("incident_id", sa.String(length=20), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "response_warning",
                "response_breach",
                "resolution_warning",
                "resolution_breach",
                name="violation_kind",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("cycle", sa.Integer(), nullable=False),
        sa.Column("deadline", itsm.UtcDateTime(), nullable=False),
        sa.Column("detected_at", itsm.UtcDateTime(), nullable=False),
        sa.Column("escalated_to_level", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["incident_id"], ["incidents.id"], name=op.f("fk_sla_violations_incident_id_incidents")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sla_violations")),
        sa.UniqueConstraint(
            "incident_id", "kind", "cycle", name=op.f("uq_sla_violations_incident_id_kind_cycle")
        ),
    )
    with op.batch_alter_table("sla_violations", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_sla_violations_incident_id"), ["incident_id"], unique=False
        )

    op.create_table(
        "technician_skills",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("skill_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["skill_id"], ["skills.id"], name=op.f("fk_technician_skills_skill_id_skills")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["technician_profiles.user_id"],
            name=op.f("fk_technician_skills_user_id_technician_profiles"),
        ),
        sa.PrimaryKeyConstraint("user_id", "skill_id", name=op.f("pk_technician_skills")),
    )
    op.create_table(
        "work_notes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("incident_id", sa.String(length=20), nullable=False),
        sa.Column("author_id", sa.Integer(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "note",
                "info_request",
                "info_response",
                name="note_kind",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("created_at", itsm.UtcDateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["author_id"], ["users.id"], name=op.f("fk_work_notes_author_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["incident_id"], ["incidents.id"], name=op.f("fk_work_notes_incident_id_incidents")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_work_notes")),
    )
    with op.batch_alter_table("work_notes", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_work_notes_incident_id"), ["incident_id"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("work_notes", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_work_notes_incident_id"))

    op.drop_table("work_notes")
    op.drop_table("technician_skills")
    with op.batch_alter_table("sla_violations", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_sla_violations_incident_id"))

    op.drop_table("sla_violations")
    op.drop_table("resolutions")
    with op.batch_alter_table("notifications", schema=None) as batch_op:
        batch_op.drop_index("ix_notifications_user_id_read_at")
        batch_op.drop_index(batch_op.f("ix_notifications_user_id"))

    op.drop_table("notifications")
    op.drop_table("incident_embeddings")
    op.drop_table("feedback")
    with op.batch_alter_table("audit_log", schema=None) as batch_op:
        batch_op.drop_index("ix_audit_log_incident_id_id")
        batch_op.drop_index(batch_op.f("ix_audit_log_action"))

    op.drop_table("audit_log")
    with op.batch_alter_table("technician_profiles", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_technician_profiles_team_id"))

    op.drop_table("technician_profiles")
    op.drop_table("service_dependencies")
    with op.batch_alter_table("incidents", schema=None) as batch_op:
        batch_op.drop_index("ix_incidents_status_priority")
        batch_op.drop_index(batch_op.f("ix_incidents_status"))
        batch_op.drop_index(batch_op.f("ix_incidents_service_id"))
        batch_op.drop_index(batch_op.f("ix_incidents_reporter_id"))
        batch_op.drop_index(batch_op.f("ix_incidents_priority"))
        batch_op.drop_index(batch_op.f("ix_incidents_parent_id"))
        batch_op.drop_index("ix_incidents_created_at")
        batch_op.drop_index("ix_incidents_assignee_id_status")
        batch_op.drop_index(batch_op.f("ix_incidents_assignee_id"))

    op.drop_table("incidents")
    op.drop_table("teams")
    op.drop_table("system_config")
    op.drop_table("services")
    op.drop_table("categories")
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_users_role"))
        batch_op.drop_index(batch_op.f("ix_users_email"))

    op.drop_table("users")
    op.drop_table("sla_policies")
    op.drop_table("skills")
