import { useState } from "react";

import type { Schemas } from "../../../api/client";
import { usePolicies, useSavePolicy } from "../../../api/hooks";
import { Button } from "../../../components/Button";
import { Card, PageHeader, QueryView } from "../../../components/States";
import { useToasts } from "../../../components/Toasts";
import {
  ALL_PRIORITIES,
  ALL_TIERS,
  formatMinutes,
  priorityLabel,
  titleCase,
} from "../../../lib/format";

type Policy = Schemas["SLAPolicyResponse"];

const INPUT =
  "w-20 rounded-md border border-line bg-surface px-2 py-1 text-right text-sm focus-visible:outline-2 focus-visible:outline-accent";

function Cell({ policy }: { policy: Policy }) {
  const save = useSavePolicy();
  const toasts = useToasts();
  const [response, setResponse] = useState(String(policy.response_minutes));
  const [resolution, setResolution] = useState(String(policy.resolution_minutes));
  const name = `${titleCase(policy.tier)} ${policy.priority}`;
  const responseMinutes = Number(response);
  const resolutionMinutes = Number(resolution);
  const valid =
    Number.isInteger(responseMinutes) &&
    Number.isInteger(resolutionMinutes) &&
    responseMinutes >= 1 &&
    resolutionMinutes >= responseMinutes;
  const changed =
    responseMinutes !== policy.response_minutes || resolutionMinutes !== policy.resolution_minutes;

  return (
    <td className="border-b border-line px-3 py-3 align-top">
      <div className="flex items-center gap-1.5">
        <input
          aria-label={`${name} response minutes`}
          type="number"
          min={1}
          className={INPUT}
          value={response}
          onChange={(event) => {
            setResponse(event.target.value);
          }}
        />
        <span className="text-muted">/</span>
        <input
          aria-label={`${name} resolution minutes`}
          type="number"
          min={1}
          className={INPUT}
          value={resolution}
          onChange={(event) => {
            setResolution(event.target.value);
          }}
        />
        <span className="text-xs text-muted">min</span>
      </div>
      <p className="mt-1 text-xs text-muted">
        {valid
          ? `${formatMinutes(responseMinutes)} / ${formatMinutes(resolutionMinutes)}`
          : "Response must be at least 1 minute and no longer than resolution."}
      </p>
      {changed && (
        <Button
          small
          variant="primary"
          className="mt-1.5"
          busy={save.isPending}
          disabled={!valid}
          aria-label={`Save ${name}`}
          onClick={() => {
            save.mutate(
              {
                tier: policy.tier,
                priority: policy.priority,
                body: { response_minutes: responseMinutes, resolution_minutes: resolutionMinutes },
              },
              {
                onSuccess: () => {
                  toasts.success(`${name} saved. New incidents use it from now on.`);
                },
                onError: (error) => {
                  toasts.error(error);
                },
              },
            );
          }}
        >
          Save
        </Button>
      )}
    </td>
  );
}

/** The §5.2 grid: response / resolution targets per service tier and priority. */
export function SLAPage() {
  const policies = usePolicies();
  return (
    <>
      <PageHeader
        title="SLA policies"
        subtitle="Response / resolution targets in minutes. Incidents already open keep the target they started with."
      />
      <QueryView query={policies} loadingLabel="Loading SLA policies">
        {(rows) => (
          <Card>
            <table className="w-full border-collapse text-sm">
              <caption className="sr-only">SLA policies</caption>
              <thead>
                <tr className="text-left text-xs tracking-wide text-muted uppercase">
                  <th scope="col" className="border-b border-line px-3 py-2">
                    Priority
                  </th>
                  {ALL_TIERS.map((tier) => (
                    <th key={tier} scope="col" className="border-b border-line px-3 py-2">
                      {titleCase(tier)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {ALL_PRIORITIES.map((priority) => (
                  <tr key={priority}>
                    <th
                      scope="row"
                      className="border-b border-line px-3 py-3 text-left font-medium"
                    >
                      {priorityLabel(priority)}
                    </th>
                    {ALL_TIERS.map((tier) => {
                      const policy = rows.find(
                        (row) => row.tier === tier && row.priority === priority,
                      );
                      return policy === undefined ? (
                        <td
                          key={tier}
                          className="border-b border-line px-3 py-3 text-xs text-muted"
                        >
                          Not set · the Gold target applies
                        </td>
                      ) : (
                        <Cell
                          key={`${tier}-${String(policy.response_minutes)}-${String(policy.resolution_minutes)}`}
                          policy={policy}
                        />
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        )}
      </QueryView>
    </>
  );
}
