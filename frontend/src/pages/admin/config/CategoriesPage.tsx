import { useState, type SyntheticEvent } from "react";

import { ApiError, type Schemas } from "../../../api/client";
import { useCategories, useSaveCategory, useSkills, type Category } from "../../../api/hooks";
import { Badge, PriorityBadge } from "../../../components/Badge";
import { Button } from "../../../components/Button";
import { DataTable } from "../../../components/DataTable";
import { SelectField, TextField } from "../../../components/Field";
import { Modal } from "../../../components/Modal";
import { ErrorState, PageHeader, QueryView } from "../../../components/States";
import { useToasts } from "../../../components/Toasts";
import { ALL_PRIORITIES, parseKeywords, priorityLabel } from "../../../lib/format";

function CategoryDialog({ category, onClose }: { category: Category | null; onClose: () => void }) {
  const save = useSaveCategory();
  const skills = useSkills();
  const toasts = useToasts();
  const [name, setName] = useState(category?.name ?? "");
  const [skillId, setSkillId] = useState(
    category?.required_skill_id == null ? "" : String(category.required_skill_id),
  );
  const [keywords, setKeywords] = useState(category?.keywords.join(", ") ?? "");
  const [floor, setFloor] = useState<string>(category?.minimum_priority ?? "");
  const [active, setActive] = useState(category?.active ?? true);
  const errors = save.error instanceof ApiError ? save.error.fieldErrors : {};

  const submit = (event: SyntheticEvent) => {
    event.preventDefault();
    save.mutate(
      {
        id: category?.id ?? null,
        body: {
          name: name.trim(),
          required_skill_id: skillId === "" ? null : Number(skillId),
          keywords: parseKeywords(keywords),
          minimum_priority: floor === "" ? null : (floor as Schemas["Priority"]),
          active,
        },
      },
      {
        onSuccess: (saved) => {
          toasts.success(
            category === null
              ? `${saved.name} was added and is live for the next incident.`
              : `${saved.name} was updated.`,
          );
          onClose();
        },
      },
    );
  };

  return (
    <Modal title={category === null ? "Add a category" : `Edit ${category.name}`} onClose={onClose}>
      <form onSubmit={submit} className="space-y-4" noValidate>
        <TextField
          label="Name"
          value={name}
          error={errors.name}
          onChange={(event) => {
            setName(event.target.value);
          }}
        />
        <SelectField
          label="Required skill"
          hint="Technicians with this skill are preferred for the category."
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
        <TextField
          label="Keywords"
          hint="Comma-separated. The classifier suggests this category when a report mentions one."
          value={keywords}
          onChange={(event) => {
            setKeywords(event.target.value);
          }}
        />
        <SelectField
          label="Minimum priority"
          hint="A floor: incidents in this category are never ranked below it."
          value={floor}
          onChange={(event) => {
            setFloor(event.target.value);
          }}
        >
          <option value="">No floor</option>
          {ALL_PRIORITIES.map((value) => (
            <option key={value} value={value}>
              {priorityLabel(value)}
            </option>
          ))}
        </SelectField>
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
            {category === null ? "Add category" : "Save changes"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}

/** Categories as data (blueprint §3): a new one works at once, with no deploy. */
export function CategoriesPage() {
  const categories = useCategories(true);
  const skills = useSkills();
  const [editing, setEditing] = useState<Category | "new" | null>(null);
  const skillName = (id: number | null) =>
    id === null ? "—" : (skills.data?.find((skill) => skill.id === id)?.name ?? "—");

  return (
    <>
      <PageHeader
        title="Categories"
        subtitle="What an incident can be classified as, the skill it needs and its priority floor."
        actions={
          <Button
            variant="primary"
            onClick={() => {
              setEditing("new");
            }}
          >
            Add a category
          </Button>
        }
      />
      <QueryView query={categories} loadingLabel="Loading categories">
        {(rows) => (
          <DataTable
            caption="Categories"
            rows={rows}
            rowKey={(row) => row.id}
            columns={[
              {
                key: "name",
                header: "Name",
                cell: (row) => <span className="font-medium">{row.name}</span>,
              },
              {
                key: "skill",
                header: "Required skill",
                cell: (row) => skillName(row.required_skill_id),
              },
              {
                key: "keywords",
                header: "Keywords",
                cell: (row) => (
                  <span className="text-xs text-muted">{row.keywords.join(", ") || "—"}</span>
                ),
              },
              {
                key: "floor",
                header: "Minimum priority",
                cell: (row) =>
                  row.minimum_priority === null ? (
                    "—"
                  ) : (
                    <PriorityBadge priority={row.minimum_priority} />
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
        <CategoryDialog
          category={editing === "new" ? null : editing}
          onClose={() => {
            setEditing(null);
          }}
        />
      )}
    </>
  );
}
