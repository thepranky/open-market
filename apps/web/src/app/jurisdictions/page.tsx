import { getJurisdictions } from "@/lib/api";
import { redirect } from "next/navigation";

export default async function JurisdictionsIndexPage() {
  const jurisdictions = [...(await getJurisdictions().catch(() => []))].sort((a, b) =>
    a.jurisdiction_name.localeCompare(b.jurisdiction_name)
  );
  if (jurisdictions.length > 0) {
    redirect(`/jurisdictions/${jurisdictions[0].jurisdiction_id}`);
  }

  return (
    <div className="flex items-center justify-center h-[60vh] text-faint text-[14px]">
      No jurisdictions loaded.
    </div>
  );
}
