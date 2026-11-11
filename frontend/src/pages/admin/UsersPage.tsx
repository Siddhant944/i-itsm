import { useState, type SyntheticEvent } from "react";

import { ApiError, type Schemas } from "../../api/client";
import {
  useCreateUser,
  useSkills,
  useTeams,
  useUpdateTechnician,
  useUpdateUser,
  useUsers,
  type UserRow,
} from "../../api/hooks";
import { useAuth } from "../../auth/AuthContext";
import { Badge, RoleBadge } from "../../components/Badge";
import { Button } from "../../components/Button";
import { DataTable } from "../../components/DataTable";
import { ChipGroup, SelectField, TextField } from "../../components/Field";
import { Modal } from "../../components/Modal";
import { ErrorState, PageHeader, QueryView } from "../../components/States";
import { useToasts } from "../../components/Toasts";
import { ALL_ROLES, levelLabel, roleLabel } from "../../lib/format";

type Fields = Schemas["TechnicianFieldsRequest"];
const SUPPORT: readonly Schemas["Role"][] = ["technician", "team_lead"];
const EXPERIENCE = [
  { value: 1, label: "Junior" },
  { value: 2, label: "Mid-level" },
  { value: 3, label: "Senior" },
];

/** Skills, experience, availability and team: the four things smart assignment reads (§5.3). */
function TechnicianFieldset({
  value,
  onChange,
}: {
  value: Fields;
  onChange: (next: Fields) => void;
}) {
  const skills = useSkills();
  const teams = useTeams();
  return (
    <div className="space-y-4 rounded-md border border-line p-3">
      <ChipGroup
        label="Skills"
        options={(skills.data ?? []).map((skill) => ({ value: skill.name, label: skill.name }))}
        selected={value.skills ?? []}
        onChange={(next) => {
          onChange({ ...value, skills: next });
        }}
      />
      <div className="grid grid-cols-2 gap-3">
        <SelectField
          label="Experience"
          value={String(value.experience_level)}
          onChange={(event) => {
            onChange({ ...value, experience_level: Number(event.target.value) });
          }}
        >
          {EXPERIENCE.map((level) => (
            <option key={level.value} value={level.value}>
              {level.label}
            </option>
          ))}
        </SelectField>
        <SelectField
          label="Team"
          value={value.team_id == null ? "" : String(value.team_id)}
          onChange={(event) => {
            onChange({
              ...value,
              team_id: event.target.value === "" ? null : Number(event.target.value),
            });
          }}
        >
          <option value="">No team</option>
          {teams.data?.map((team) => (
            <option key={team.id} value={team.id}>
              {team.name}
            </option>
          ))}
        </SelectField>
      </div>
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={value.available}
          onChange={(event) => {
            onChange({ ...value, available: event.target.checked });
          }}
        />
        Available for new assignments
      </label>
    </div>
  );
}

function CreateUserDialog({ onClose }: { onClose: () => void }) {
  const create = useCreateUser();
  const toasts = useToasts();
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<Schemas["Role"]>("technician");
  const [fields, setFields] = useState<Fields>({
    skills: [],
    experience_level: 1,
    available: true,
    team_id: null,
  });
  const errors = create.error instanceof ApiError ? create.error.fieldErrors : {};

  const submit = (event: SyntheticEvent) => {
    event.preventDefault();
    create.mutate(
      {
        full_name: fullName.trim(),
        email: email.trim(),
        password,
        role,
        technician: SUPPORT.includes(role) ? fields : null,
      },
      {
        onSuccess: (user) => {
          toasts.success(`${user.full_name} was added as ${roleLabel(user.role)}.`);
          onClose();
        },
      },
    );
  };

  return (
    <Modal title="Add a user" onClose={onClose} wide>
      <form onSubmit={submit} className="space-y-4" noValidate>
        <div className="grid grid-cols-2 gap-3">
          <TextField
            label="Full name"
            value={fullName}
            error={errors.full_name}
            onChange={(event) => {
              setFullName(event.target.value);
            }}
          />
          <TextField
            label="Email"
            type="email"
            value={email}
            error={errors.email}
            onChange={(event) => {
              setEmail(event.target.value);
            }}
          />
          <TextField
            label="Initial password"
            type="password"
            autoComplete="new-password"
            hint="At least 8 characters."
            value={password}
            error={errors.password}
            onChange={(event) => {
              setPassword(event.target.value);
            }}
          />
          <SelectField
            label="Role"
            value={role}
            onChange={(event) => {
              setRole(event.target.value as Schemas["Role"]);
            }}
          >
            {ALL_ROLES.map((value) => (
              <option key={value} value={value}>
                {roleLabel(value)}
              </option>
            ))}
          </SelectField>
        </div>
        {SUPPORT.includes(role) && <TechnicianFieldset value={fields} onChange={setFields} />}
        {create.isError && <ErrorState error={create.error} />}
        <div className="flex justify-end gap-2">
          <Button onClick={onClose}>Cancel</Button>
          <Button
            type="submit"
            variant="primary"
            busy={create.isPending}
            disabled={fullName.trim() === "" || email.trim() === "" || password === ""}
          >
            Add user
          </Button>
        </div>
      </form>
    </Modal>
  );
}

function EditUserDialog({ user, onClose }: { user: UserRow; onClose: () => void }) {
  const { user: me } = useAuth();
  const update = useUpdateUser();
  const updateTechnician = useUpdateTechnician();
  const toasts = useToasts();
  const [role, setRole] = useState(user.role);
  const [fields, setFields] = useState<Fields>({
    skills: user.skills ?? [],
    experience_level: user.experience_level ?? 1,
    available: user.available ?? true,
    team_id: user.team_id ?? null,
  });
  const isSelf = me?.id === user.id;
  const wasSupport = SUPPORT.includes(user.role);
  const busy = update.isPending || updateTechnician.isPending;
  const problem = update.error ?? updateTechnician.error;

  const save = async () => {
    if (role !== user.role) await update.mutateAsync({ id: user.id, body: { role } });
    // The profile can only be edited once the person is (still) support staff.
    if (SUPPORT.includes(role)) await updateTechnician.mutateAsync({ id: user.id, body: fields });
    toasts.success(`${user.full_name} was updated.`);
    onClose();
  };

  return (
    <Modal title={`Edit ${user.full_name}`} onClose={onClose} wide>
      <form
        className="space-y-4"
        onSubmit={(event: SyntheticEvent) => {
          event.preventDefault();
          // The failure is rendered from the mutation's own error state below.
          save().catch(() => undefined);
        }}
      >
        <SelectField
          label="Role"
          value={role}
          disabled={isSelf}
          hint={isSelf ? "You cannot change your own role." : undefined}
          onChange={(event) => {
            setRole(event.target.value as Schemas["Role"]);
          }}
        >
          {ALL_ROLES.map((value) => (
            <option key={value} value={value}>
              {roleLabel(value)}
            </option>
          ))}
        </SelectField>
        {SUPPORT.includes(role) && <TechnicianFieldset value={fields} onChange={setFields} />}
        {wasSupport && !SUPPORT.includes(role) && (
          <p className="text-sm text-muted">
            This removes the technician profile. Open incidents must be reassigned first.
          </p>
        )}
        {problem !== null && <ErrorState error={problem} />}
        <div className="flex justify-end gap-2">
          <Button onClick={onClose}>Cancel</Button>
          <Button type="submit" variant="primary" busy={busy}>
            Save changes
          </Button>
        </div>
      </form>
    </Modal>
  );
}

/** Accounts, roles and technician profiles (blueprint §3, §8). */
export function UsersPage() {
  const users = useUsers();
  const teams = useTeams();
  const update = useUpdateUser();
  const toasts = useToasts();
  const { user: me } = useAuth();
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<UserRow | null>(null);
  const [roleFilter, setRoleFilter] = useState("");

  const teamName = (id: number | null | undefined) =>
    id == null ? "—" : (teams.data?.find((team) => team.id === id)?.name ?? "—");

  return (
    <>
      <PageHeader
        title="Users"
        subtitle="Give roles, keep technician profiles current, and switch accounts off."
        actions={
          <Button
            variant="primary"
            onClick={() => {
              setCreating(true);
            }}
          >
            Add a user
          </Button>
        }
      />
      <div className="mb-4 w-56">
        <SelectField
          label="Role"
          value={roleFilter}
          onChange={(event) => {
            setRoleFilter(event.target.value);
          }}
        >
          <option value="">All roles</option>
          {ALL_ROLES.map((value) => (
            <option key={value} value={value}>
              {roleLabel(value)}
            </option>
          ))}
        </SelectField>
      </div>
      <QueryView query={users} loadingLabel="Loading users">
        {(rows) => (
          <DataTable
            caption="Users"
            rows={rows.filter((row) => roleFilter === "" || row.role === roleFilter)}
            rowKey={(row) => row.id}
            columns={[
              {
                key: "name",
                header: "Name",
                cell: (row) => (
                  <div>
                    <p className="font-medium">{row.full_name}</p>
                    <p className="text-xs text-muted">{row.email}</p>
                  </div>
                ),
              },
              { key: "role", header: "Role", cell: (row) => <RoleBadge role={row.role} /> },
              { key: "team", header: "Team", cell: (row) => teamName(row.team_id) },
              {
                key: "skills",
                header: "Skills",
                cell: (row) =>
                  row.skills == null ? (
                    "—"
                  ) : (
                    <span className="text-xs">
                      {row.skills.join(", ") || "none"} ·{" "}
                      {levelLabel(row.experience_level ?? 1) === "Low"
                        ? "junior"
                        : levelLabel(row.experience_level ?? 1) === "Medium"
                          ? "mid-level"
                          : "senior"}
                    </span>
                  ),
              },
              {
                key: "state",
                header: "Status",
                cell: (row) =>
                  !row.active ? (
                    <Badge tone="bad">Deactivated</Badge>
                  ) : row.available === false ? (
                    <Badge>Unavailable</Badge>
                  ) : (
                    <Badge tone="good">Active</Badge>
                  ),
              },
              {
                key: "actions",
                header: "",
                align: "right",
                cell: (row) => (
                  <div className="flex justify-end gap-1">
                    <Button
                      small
                      onClick={() => {
                        setEditing(row);
                      }}
                    >
                      Edit
                    </Button>
                    <Button
                      small
                      variant={row.active ? "ghost" : "secondary"}
                      disabled={row.id === me?.id || update.isPending}
                      onClick={() => {
                        update.mutate(
                          { id: row.id, body: { active: !row.active } },
                          {
                            onSuccess: (changed) => {
                              toasts.success(
                                `${changed.full_name} was ${changed.active ? "reactivated" : "deactivated"}.`,
                              );
                            },
                            onError: (error) => {
                              toasts.error(error);
                            },
                          },
                        );
                      }}
                    >
                      {row.active ? "Deactivate" : "Reactivate"}
                    </Button>
                  </div>
                ),
              },
            ]}
          />
        )}
      </QueryView>
      {creating && (
        <CreateUserDialog
          onClose={() => {
            setCreating(false);
          }}
        />
      )}
      {editing !== null && (
        <EditUserDialog
          user={editing}
          onClose={() => {
            setEditing(null);
          }}
        />
      )}
    </>
  );
}
