import { Card, PageTitle } from "@/components/ui";
import { api } from "@/lib/api";
import type { ProfileFile } from "@/lib/types";

export const metadata = { title: "Settings" };

export default async function SettingsPage() {
  const files = await api<ProfileFile[]>("/api/profiles");
  return (
    <>
      <PageTitle title="Settings" subtitle="Read-only for now. Edit the files in the project, then refresh this page." />
      <Card className="mb-4 text-sm text-ink-2">
        <p>
          Every number is in YAML: <code className="rounded bg-surface-2 px-1">config/profiles/&lt;profile&gt;.yaml</code> holds the quality rules,
          strategy parameters, ranking and backtest settings; <code className="rounded bg-surface-2 px-1">config/settings.yaml</code> holds data
          sources, the daily job and the Telegram summary. Try a change without editing first:
        </p>
        <pre className="mt-2 overflow-x-auto rounded-lg bg-surface-2 p-3 text-xs">
          python -m dse_screener backtest --profile swing --set strategies.quiet_accumulation.params.min_volume_ratio=2
        </pre>
        <p className="mt-2">Secrets (config/secrets.yaml) are never shown here.</p>
      </Card>
      <div className="space-y-4">
        {files.map((f) => (
          <Card key={f.path}>
            <h2 className="mb-2 font-mono text-sm font-semibold">{f.path}</h2>
            <pre className="max-h-[36rem] overflow-auto rounded-lg bg-surface-2 p-3 text-xs leading-relaxed">{f.yaml}</pre>
          </Card>
        ))}
      </div>
    </>
  );
}
