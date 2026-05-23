import Link from "next/link";

export default function HomePage() {
  return (
    <div className="max-w-4xl mx-auto px-4 py-24 sm:px-6">
      {/* Hero */}
      <div className="text-center mb-16">
        <h1 className="text-5xl font-bold tracking-tight text-slate-900 mb-4">
          CompMap
        </h1>
        <p className="text-xl text-slate-600 mb-8 max-w-2xl mx-auto">
          Open-source market-definition research graph for competition lawyers.
          Search EU, UK, and US merger precedent by sector, product market,
          theory of harm, and outcome.
        </p>
        <Link
          href="/explore"
          className="inline-block bg-brand-600 hover:bg-brand-700 text-white font-semibold px-8 py-3 rounded-lg transition-colors"
        >
          Explore cases
        </Link>
      </div>

      {/* Features */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-8 mb-16">
        {[
          {
            title: "Source-linked records",
            description:
              "Every market-definition proposition links to a specific page, paragraph, and quote in the underlying decision or court document.",
          },
          {
            title: "Graph relationships",
            description:
              "Navigate cases through shared markets, sectors, parties, and theories of harm using Neo4j-powered graph queries.",
          },
          {
            title: "Transparent quality",
            description:
              "Each record shows its extraction method, review status, and confidence score so you can judge the reliability of the data.",
          },
        ].map((f) => (
          <div
            key={f.title}
            className="bg-slate-50 rounded-xl p-6 border border-slate-100"
          >
            <h3 className="font-semibold text-slate-900 mb-2">{f.title}</h3>
            <p className="text-sm text-slate-600">{f.description}</p>
          </div>
        ))}
      </div>

      {/* Jurisdictions */}
      <div className="bg-blue-50 rounded-xl p-8 mb-16 border border-blue-100">
        <h2 className="text-lg font-semibold text-slate-900 mb-4">
          Covered jurisdictions
        </h2>
        <div className="flex flex-wrap gap-4">
          {[
            { flag: "🇪🇺", label: "EU", sub: "European Commission" },
            { flag: "🇬🇧", label: "UK", sub: "CMA" },
            { flag: "🇺🇸", label: "US", sub: "DOJ / FTC" },
          ].map((j) => (
            <div key={j.label} className="flex items-center gap-3">
              <span className="text-3xl">{j.flag}</span>
              <div>
                <div className="font-semibold text-slate-800">{j.label}</div>
                <div className="text-xs text-slate-500">{j.sub}</div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Disclaimer */}
      <div className="rounded-lg border border-amber-200 bg-amber-50 p-6 text-sm text-amber-900">
        <strong>Disclaimer:</strong> CompMap is an open-source research aid for
        market-definition research. It is{" "}
        <strong>not legal advice</strong>. Records may be generated or assisted
        by AI and may contain errors. Users must verify all propositions against
        the linked source materials before relying on them.
      </div>
    </div>
  );
}
