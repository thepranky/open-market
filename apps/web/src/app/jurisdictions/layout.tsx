import { getJurisdictions } from "@/lib/api";
import { JurisdictionSidebar } from "./JurisdictionSidebar";
import { JurisdictionChat } from "@/components/JurisdictionChat";

export default async function JurisdictionsLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const jurisdictions = [...(await getJurisdictions().catch(() => []))].sort((a, b) =>
    a.jurisdiction_name.localeCompare(b.jurisdiction_name)
  );

  return (
    <div className="flex">
      <aside
        className="hidden md:flex md:flex-col flex-shrink-0 border-r border-line"
        style={{
          width: 272,
          position: "sticky",
          top: 58,
          height: "calc(100vh - 58px)",
          overflowY: "auto",
        }}
      >
        <JurisdictionSidebar jurisdictions={jurisdictions} />
      </aside>

      <div className="flex-1 min-w-0">
        {children}
      </div>

      <JurisdictionChat jurisdictions={jurisdictions} />
    </div>
  );
}
