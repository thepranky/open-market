import { ScreenClient } from "./ScreenClient";

export default function ScreenPage() {
  return (
    <main className="mx-auto max-w-content px-6 lg:px-8 py-8">
      <div className="mb-8">
        <h1 className="text-[22px] font-semibold text-ink mb-1">Deal screening</h1>
        <p className="text-[14px] text-muted">
          Enter deal parameters to identify mandatory merger control filing obligations across{" "}
          <span className="font-medium text-ink">29 jurisdictions</span>.
        </p>
      </div>
      <ScreenClient />
    </main>
  );
}
