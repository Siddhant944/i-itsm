import { useState, type SyntheticEvent } from "react";

import { ApiError, type Schemas } from "../../../api/client";
import { useSaveService, useServices, useSkills, type Service } from "../../../api/hooks";
import { Badge } from "../../../components/Badge";
import { Button } from "../../../components/Button";
import { DataTable } from "../../../components/DataTable";
import { ChipGroup, SelectField, TextField } from "../../../components/Field";
import { Modal } from "../../../components/Modal";
import { ErrorState, PageHeader, QueryView } from "../../../components/States";
import { useToasts } from "../../../components/Toasts";
import { ALL_TIERS, levelLabel, titleCase } from "../../../lib/format";

function ServiceDialog({
  service,
  all,
  onClose,
}: {
  service: Service | null;
  all: readonly Service[];
  onClose: () => void;
}) {
  const save = useSaveService();
  const skills = useSkills();
  const toasts = useToasts();
  const [name, setName] = useState(service?.name ?? "");
  const [criticality, setCriticality] = useState(String(service?.criticality ?? 2));
  // "" = follow the criticality (3 Gold, 2 Silver, 1 Bronze; blueprint §5.2).
  const [tier, setTier] = useState<string>(
    service?.tier_overridden === true ? service.sla_tier : "",
  );
  const [skillId, setSkillId] = useState(
    service?.required_skill_id == null ? "" : String(service.required_skill_id),
  );
  const [dependsOn, setDependsOn] = useState<number[]>(service?.depends_on ?? []);
  const [active, setActive] = useState(service?.active ?? true);
  const errors = save.error instanceof ApiError ? save.error.fieldErrors : {};

  const submit = (event: SyntheticEvent) => {
    event.preventDefault();
    save.mutate(
      {
        id: service?.id ?? null,
        body: {
          name: name.trim(),
          criticality: Number(criticality),
          sla_tier: tier === "" ? null : (tier as Schemas["SLATier"]),
          required_skill_id: skillId === "" ? null : Number(skillId),
          depends_on: dependsOn,
          active,
        },
      },
      {
        onSuccess: (saved) => {
          toasts.success(`${saved.name} was ${service === null ? "added" : "updated"}.`);
          onClose();
        },
      },
    );
  };

  return (
    <Modal
      title={service === null ? "Add a service" : `Edit ${service.name}`}
      onClose={onClose}
      wide
    >
      <form onSubmit={submit} className="space-y-4" noValidate>
        <TextField
          label="Name"
          value={name}
          error={errors.name}
          onChange={(event) => {
            setName(event.target.value);
          }}
        />
        <div className="grid grid-cols-3 gap-3">
          <SelectField
            label="Criticality"
            hint="Feeds the priority score."
            value={criticality}
            onChange={(event) => {
              setCriticality(event.target.value);
            }}
          >
            {[1, 2, 3].map((value) => (
              <option key={value} value={value}>
                {String(value)} · {levelLabel(value)}
              </option>
            ))}
          </SelectField>
          <SelectField
            label="SLA tier"
            value={tier}
            onChange={(event) => {
              setTier(event.target.value);
            }}
          >
            <option value="">Follow criticality</option>
            {ALL_TIERS.map((value) => (
              <option key={value} value={value}>
                {titleCase(value)}
              </option>
            ))}
          </SelectField>
          <SelectField
            label="Required skill"
            value={skillId}
            error={errors.required_skill_id}
            onChange={(event) => {
              setSkillId(event.target.value);
            }}
          >
            <option value="">None</option>
            {skills.data?.map((skill) => (
              <option key={skill.id} value={skill.id}>
                {skill.name}
              </option>
            ))}
          </SelectField>
        </div>
        <ChipGroup
          label="Depends on"
          options={all
            .filter((other) => other.id !== service?.id)
            .map((other) => ({ value: other.id, label: other.name }))}
          selected={dependsOn}
          onChange={setDependsOn}
        />
        {errors.depends_on !== undefined && (
          <p role="alert" className="text-xs text-red-600">
            {errors.depends_on}
          </p>
        )}
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={active}
            onChange={(event) => {
              setActive(event.target.checked);
            }}
          />
          Active (offered on the report form)
        </label>
        {save.isError && <ErrorState error={save.error} />}
        <div className="flex justify-end gap-2">
          <Button onClick={onClose}>Cancel</Button>
          <Button
            type="submit"
            variant="primary"
            busy={save.isPending}
            disabled={name.trim() === ""}
          >
            {service === null ? "Add service" : "Save changes"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}

/** Services, their criticality and SLA tier, and the dependency graph (blueprint §3, §6.2). */
export function ServicesPage() {
  const services = useServices(true);
  const [editing, setEditing] = useState<Service | "new" | null>(null);
  const all = services.data ?? [];
  const nameOf = (id: number) => all.find((service) => service.id === id)?.name ?? `#${String(id)}`;

  return (
    <>
      <PageHeader
        title="Services"
        subtitle="Criticality drives priority, the tier picks the SLA targets, and dependencies link related outages."
        actions={
          <Button
            variant="primary"
            onClick={() => {
              setEditing("new");
            }}
          >
            Add a service
          </Button>
        }
      />
      <QueryView query={services} loadingLabel="Loading services">
        {(rows) => (
          <DataTable
            caption="Services"
            rows={rows}
            rowKey={(row) => row.id}
            columns={[
              {
                key: "name",
                header: "Name",
                cell: (row) => <span className="font-medium">{row.name}</span>,
              },
              {
                key: "crit",
                header: "Criticality",
                cell: (row) => `${String(row.criticality)} · ${levelLabel(row.criticality)}`,
              },
              {
                key: "tier",
                header: "SLA tier",
                cell: (row) => (
                  <span>
                    {titleCase(row.sla_tier)}
                    {row.tier_overridden && <span className="text-xs text-muted"> (pinned)</span>}
                  </span>
                ),
              },
              {
                key: "deps",
                header: "Depends on",
                cell: (row) => (
                  <span className="text-xs text-muted">
                    {row.depends_on.map(nameOf).join(", ") || "—"}
                  </span>
                ),
              },
              {
                key: "active",
                header: "Status",
                cell: (row) =>
                  row.active ? <Badge tone="good">Active</Badge> : <Badge>Retired</Badge>,
              },
              {
                key: "actions",
                header: "",
                align: "right",
                cell: (row) => (
                  <Button
                    small
                    aria-label={`Edit ${row.name}`}
                    onClick={() => {
                      setEditing(row);
                    }}
                  >
                    Edit
                  </Button>
                ),
              },
            ]}
          />
        )}
      </QueryView>
      {editing !== null && (
        <ServiceDialog
          service={editing === "new" ? null : editing}
          all={all}
          onClose={() => {
            setEditing(null);
          }}
        />
      )}
    </>
  );
}
