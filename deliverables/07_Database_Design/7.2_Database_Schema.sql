-- I-ITSM database schema (PostgreSQL), generated from the ORM metadata.

CREATE TABLE skills (
	id SERIAL NOT NULL, 
	name VARCHAR(80) NOT NULL, 
	CONSTRAINT pk_skills PRIMARY KEY (id), 
	CONSTRAINT uq_skills_name UNIQUE (name)
);

CREATE TABLE sla_policies (
	id SERIAL NOT NULL, 
	tier VARCHAR(32) NOT NULL, 
	priority VARCHAR(32) NOT NULL, 
	response BIGINT NOT NULL, 
	resolution BIGINT NOT NULL, 
	CONSTRAINT pk_sla_policies PRIMARY KEY (id), 
	CONSTRAINT uq_sla_policies_tier_priority UNIQUE (tier, priority)
);

CREATE TABLE users (
	id SERIAL NOT NULL, 
	email VARCHAR(255) NOT NULL, 
	full_name VARCHAR(200) NOT NULL, 
	role VARCHAR(32) NOT NULL, 
	password_hash VARCHAR(255), 
	active BOOLEAN NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	failed_login_count INTEGER NOT NULL, 
	locked_until TIMESTAMP WITH TIME ZONE, 
	last_login_at TIMESTAMP WITH TIME ZONE, 
	telegram_chat_id VARCHAR(64), 
	google_subject VARCHAR(64), 
	CONSTRAINT pk_users PRIMARY KEY (id), 
	CONSTRAINT uq_users_google_subject UNIQUE (google_subject)
);

CREATE UNIQUE INDEX ix_users_email ON users (email);

CREATE INDEX ix_users_role ON users (role);

CREATE TABLE categories (
	id SERIAL NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	required_skill_id INTEGER, 
	keywords JSON NOT NULL, 
	minimum_priority VARCHAR(32), 
	active BOOLEAN NOT NULL, 
	CONSTRAINT pk_categories PRIMARY KEY (id), 
	CONSTRAINT uq_categories_name UNIQUE (name), 
	CONSTRAINT fk_categories_required_skill_id_skills FOREIGN KEY(required_skill_id) REFERENCES skills (id)
);

CREATE TABLE services (
	id SERIAL NOT NULL, 
	name VARCHAR(160) NOT NULL, 
	criticality INTEGER NOT NULL, 
	sla_tier VARCHAR(32) NOT NULL, 
	tier_overridden BOOLEAN NOT NULL, 
	required_skill_id INTEGER, 
	active BOOLEAN NOT NULL, 
	CONSTRAINT pk_services PRIMARY KEY (id), 
	CONSTRAINT ck_services_criticality_between_1_and_3 CHECK (criticality BETWEEN 1 AND 3), 
	CONSTRAINT uq_services_name UNIQUE (name), 
	CONSTRAINT fk_services_required_skill_id_skills FOREIGN KEY(required_skill_id) REFERENCES skills (id)
);

CREATE TABLE system_config (
	key VARCHAR(80) NOT NULL, 
	value JSON NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	updated_by INTEGER, 
	CONSTRAINT pk_system_config PRIMARY KEY (key), 
	CONSTRAINT fk_system_config_updated_by_users FOREIGN KEY(updated_by) REFERENCES users (id)
);

CREATE TABLE teams (
	id SERIAL NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	lead_id INTEGER, 
	CONSTRAINT pk_teams PRIMARY KEY (id), 
	CONSTRAINT uq_teams_name UNIQUE (name), 
	CONSTRAINT fk_teams_lead_id_users FOREIGN KEY(lead_id) REFERENCES users (id)
);

CREATE TABLE incidents (
	id VARCHAR(20) NOT NULL, 
	reporter_id INTEGER NOT NULL, 
	assignee_id INTEGER, 
	category_id INTEGER, 
	service_id INTEGER NOT NULL, 
	parent_id VARCHAR(20), 
	title VARCHAR(200) NOT NULL, 
	description TEXT NOT NULL, 
	impact INTEGER NOT NULL, 
	urgency INTEGER NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	priority VARCHAR(32), 
	priority_score INTEGER, 
	priority_overridden BOOLEAN NOT NULL, 
	cancel_reason VARCHAR(32), 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	acknowledged_at TIMESTAMP WITH TIME ZONE, 
	resolved_at TIMESTAMP WITH TIME ZONE, 
	closed_at TIMESTAMP WITH TIME ZONE, 
	reopen_count INTEGER NOT NULL, 
	escalation_level INTEGER NOT NULL, 
	sla_started_at TIMESTAMP WITH TIME ZONE, 
	sla_response_target BIGINT, 
	sla_resolution_target BIGINT, 
	sla_responded_at TIMESTAMP WITH TIME ZONE, 
	sla_paused_total BIGINT, 
	sla_paused_since TIMESTAMP WITH TIME ZONE, 
	sla_stopped_at TIMESTAMP WITH TIME ZONE, 
	sla_response_met BOOLEAN, 
	sla_resolution_target_at_stop BIGINT, 
	sla_response_deadline TIMESTAMP WITH TIME ZONE, 
	sla_response_risk_at TIMESTAMP WITH TIME ZONE, 
	sla_resolution_deadline TIMESTAMP WITH TIME ZONE, 
	sla_resolution_risk_at TIMESTAMP WITH TIME ZONE, 
	version INTEGER NOT NULL, 
	CONSTRAINT pk_incidents PRIMARY KEY (id), 
	CONSTRAINT ck_incidents_impact_between_1_and_3 CHECK (impact BETWEEN 1 AND 3), 
	CONSTRAINT ck_incidents_urgency_between_1_and_3 CHECK (urgency BETWEEN 1 AND 3), 
	CONSTRAINT fk_incidents_reporter_id_users FOREIGN KEY(reporter_id) REFERENCES users (id), 
	CONSTRAINT fk_incidents_assignee_id_users FOREIGN KEY(assignee_id) REFERENCES users (id), 
	CONSTRAINT fk_incidents_category_id_categories FOREIGN KEY(category_id) REFERENCES categories (id), 
	CONSTRAINT fk_incidents_service_id_services FOREIGN KEY(service_id) REFERENCES services (id), 
	CONSTRAINT fk_incidents_parent_id_incidents FOREIGN KEY(parent_id) REFERENCES incidents (id)
);

CREATE INDEX ix_incidents_assignee_id ON incidents (assignee_id);

CREATE INDEX ix_incidents_assignee_id_status ON incidents (assignee_id, status);

CREATE INDEX ix_incidents_created_at ON incidents (created_at);

CREATE INDEX ix_incidents_parent_id ON incidents (parent_id);

CREATE INDEX ix_incidents_priority ON incidents (priority);

CREATE INDEX ix_incidents_reporter_id ON incidents (reporter_id);

CREATE INDEX ix_incidents_service_id ON incidents (service_id);

CREATE INDEX ix_incidents_status ON incidents (status);

CREATE INDEX ix_incidents_status_priority ON incidents (status, priority);

CREATE INDEX ix_incidents_status_sla_resolution_deadline ON incidents (status, sla_resolution_deadline);

CREATE TABLE service_dependencies (
	service_id INTEGER NOT NULL, 
	depends_on_id INTEGER NOT NULL, 
	position INTEGER NOT NULL, 
	CONSTRAINT pk_service_dependencies PRIMARY KEY (service_id, depends_on_id), 
	CONSTRAINT ck_service_dependencies_no_self_dependency CHECK (service_id <> depends_on_id), 
	CONSTRAINT fk_service_dependencies_service_id_services FOREIGN KEY(service_id) REFERENCES services (id), 
	CONSTRAINT fk_service_dependencies_depends_on_id_services FOREIGN KEY(depends_on_id) REFERENCES services (id)
);

CREATE TABLE technician_profiles (
	user_id INTEGER NOT NULL, 
	experience_level INTEGER NOT NULL, 
	available BOOLEAN NOT NULL, 
	team_id INTEGER, 
	CONSTRAINT pk_technician_profiles PRIMARY KEY (user_id), 
	CONSTRAINT ck_technician_profiles_experience_level_between_1_and_3 CHECK (experience_level BETWEEN 1 AND 3), 
	CONSTRAINT fk_technician_profiles_user_id_users FOREIGN KEY(user_id) REFERENCES users (id), 
	CONSTRAINT fk_technician_profiles_team_id_teams FOREIGN KEY(team_id) REFERENCES teams (id)
);

CREATE INDEX ix_technician_profiles_team_id ON technician_profiles (team_id);

CREATE TABLE audit_log (
	id SERIAL NOT NULL, 
	incident_id VARCHAR(20), 
	actor_id INTEGER, 
	action VARCHAR(60) NOT NULL, 
	details JSON NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	previous_hash VARCHAR(64), 
	hash VARCHAR(64) NOT NULL, 
	CONSTRAINT pk_audit_log PRIMARY KEY (id), 
	CONSTRAINT fk_audit_log_incident_id_incidents FOREIGN KEY(incident_id) REFERENCES incidents (id) ON DELETE RESTRICT, 
	CONSTRAINT fk_audit_log_actor_id_users FOREIGN KEY(actor_id) REFERENCES users (id), 
	CONSTRAINT uq_audit_log_hash UNIQUE (hash)
);

CREATE INDEX ix_audit_log_action ON audit_log (action);

CREATE INDEX ix_audit_log_incident_id_id ON audit_log (incident_id, id);

CREATE TABLE feedback (
	id SERIAL NOT NULL, 
	incident_id VARCHAR(20) NOT NULL, 
	rating INTEGER NOT NULL, 
	comment TEXT NOT NULL, 
	given_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	CONSTRAINT pk_feedback PRIMARY KEY (id), 
	CONSTRAINT ck_feedback_rating_between_1_and_5 CHECK (rating BETWEEN 1 AND 5), 
	CONSTRAINT uq_feedback_incident_id UNIQUE (incident_id), 
	CONSTRAINT fk_feedback_incident_id_incidents FOREIGN KEY(incident_id) REFERENCES incidents (id)
);

CREATE TABLE incident_embeddings (
	incident_id VARCHAR(20) NOT NULL, 
	provider VARCHAR(40) NOT NULL, 
	model VARCHAR(80) NOT NULL, 
	dimensions INTEGER NOT NULL, 
	vector JSON NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	CONSTRAINT pk_incident_embeddings PRIMARY KEY (incident_id), 
	CONSTRAINT fk_incident_embeddings_incident_id_incidents FOREIGN KEY(incident_id) REFERENCES incidents (id)
);

CREATE TABLE notifications (
	id SERIAL NOT NULL, 
	user_id INTEGER NOT NULL, 
	incident_id VARCHAR(20), 
	event VARCHAR(40) NOT NULL, 
	channel VARCHAR(20) NOT NULL, 
	subject VARCHAR(200) NOT NULL, 
	body TEXT NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	attempts INTEGER NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	sent_at TIMESTAMP WITH TIME ZONE, 
	read_at TIMESTAMP WITH TIME ZONE, 
	CONSTRAINT pk_notifications PRIMARY KEY (id), 
	CONSTRAINT fk_notifications_user_id_users FOREIGN KEY(user_id) REFERENCES users (id), 
	CONSTRAINT fk_notifications_incident_id_incidents FOREIGN KEY(incident_id) REFERENCES incidents (id)
);

CREATE INDEX ix_notifications_user_id ON notifications (user_id);

CREATE INDEX ix_notifications_user_id_read_at ON notifications (user_id, read_at);

CREATE TABLE resolutions (
	id SERIAL NOT NULL, 
	incident_id VARCHAR(20) NOT NULL, 
	resolver_id INTEGER NOT NULL, 
	summary TEXT NOT NULL, 
	resolved_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	CONSTRAINT pk_resolutions PRIMARY KEY (id), 
	CONSTRAINT uq_resolutions_incident_id UNIQUE (incident_id), 
	CONSTRAINT fk_resolutions_incident_id_incidents FOREIGN KEY(incident_id) REFERENCES incidents (id), 
	CONSTRAINT fk_resolutions_resolver_id_users FOREIGN KEY(resolver_id) REFERENCES users (id)
);

CREATE TABLE sla_violations (
	id SERIAL NOT NULL, 
	incident_id VARCHAR(20) NOT NULL, 
	kind VARCHAR(32) NOT NULL, 
	cycle INTEGER NOT NULL, 
	deadline TIMESTAMP WITH TIME ZONE NOT NULL, 
	detected_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	escalated_to_level INTEGER, 
	CONSTRAINT pk_sla_violations PRIMARY KEY (id), 
	CONSTRAINT uq_sla_violations_incident_id_kind_cycle UNIQUE (incident_id, kind, cycle), 
	CONSTRAINT fk_sla_violations_incident_id_incidents FOREIGN KEY(incident_id) REFERENCES incidents (id)
);

CREATE INDEX ix_sla_violations_incident_id ON sla_violations (incident_id);

CREATE TABLE technician_skills (
	user_id INTEGER NOT NULL, 
	skill_id INTEGER NOT NULL, 
	CONSTRAINT pk_technician_skills PRIMARY KEY (user_id, skill_id), 
	CONSTRAINT fk_technician_skills_user_id_technician_profiles FOREIGN KEY(user_id) REFERENCES technician_profiles (user_id), 
	CONSTRAINT fk_technician_skills_skill_id_skills FOREIGN KEY(skill_id) REFERENCES skills (id)
);

CREATE TABLE work_notes (
	id SERIAL NOT NULL, 
	incident_id VARCHAR(20) NOT NULL, 
	author_id INTEGER NOT NULL, 
	kind VARCHAR(32) NOT NULL, 
	text TEXT NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	CONSTRAINT pk_work_notes PRIMARY KEY (id), 
	CONSTRAINT fk_work_notes_incident_id_incidents FOREIGN KEY(incident_id) REFERENCES incidents (id), 
	CONSTRAINT fk_work_notes_author_id_users FOREIGN KEY(author_id) REFERENCES users (id)
);

CREATE INDEX ix_work_notes_incident_id ON work_notes (incident_id);
