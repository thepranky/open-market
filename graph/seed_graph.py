#!/usr/bin/env python3
"""
Seed Neo4j with case records from data/cases/.

Usage:
  python graph/seed_graph.py [--cases-dir data/cases] [--wipe]

Environment variables:
  NEO4J_URI       bolt://localhost:7687
  NEO4J_USER      neo4j
  NEO4J_PASSWORD  compmap_local
"""

import argparse
import os
import sys
from pathlib import Path

# Allow running from repo root
sys.path.insert(0, str(Path(__file__).parent.parent / "apps" / "api"))

from neo4j import GraphDatabase
from app.loader.yaml_loader import load_all_cases
from app.models import CaseRecord


def get_driver():
    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD", "compmap_local")
    return GraphDatabase.driver(uri, auth=(user, password))


def apply_cypher_file(session, path: Path):
    text = path.read_text()
    for stmt in text.split(";"):
        stmt = stmt.strip()
        if stmt:
            session.run(stmt)


def wipe_graph(session):
    session.run("MATCH (n) DETACH DELETE n")
    print("  Graph wiped.")


def seed_case(session, case: CaseRecord):
    # Jurisdiction
    session.run(
        "MERGE (j:Jurisdiction {name: $name})",
        name=case.jurisdiction,
    )

    # Authority
    session.run(
        "MERGE (a:Authority {name: $name}) SET a.jurisdiction = $jurisdiction",
        name=case.authority, jurisdiction=case.jurisdiction,
    )
    session.run(
        """
        MATCH (j:Jurisdiction {name: $jur}), (a:Authority {name: $auth})
        MERGE (j)-[:HAS_AUTHORITY]->(a)
        """,
        jur=case.jurisdiction, auth=case.authority,
    )

    # Case node
    session.run(
        """
        MERGE (c:Case {case_id: $case_id})
        SET c.case_name = $case_name,
            c.jurisdiction = $jurisdiction,
            c.authority = $authority,
            c.decision_date = $decision_date,
            c.case_type = $case_type,
            c.procedure_stage = $procedure_stage,
            c.sector = $sector,
            c.outcome = $outcome,
            c.ai_summary = $ai_summary
        """,
        **case.to_graph_dict(),
    )

    # Authority -> Case
    session.run(
        """
        MATCH (a:Authority {name: $auth}), (c:Case {case_id: $case_id})
        MERGE (a)-[:DECIDED]->(c)
        """,
        auth=case.authority, case_id=case.case_id,
    )

    # Sector
    session.run("MERGE (s:Sector {name: $name})", name=case.sector)
    session.run(
        """
        MATCH (c:Case {case_id: $case_id}), (s:Sector {name: $sector})
        MERGE (c)-[:CONCERNS_SECTOR]->(s)
        """,
        case_id=case.case_id, sector=case.sector,
    )

    # Outcome
    session.run("MERGE (o:Outcome {name: $name})", name=case.outcome.value)
    session.run(
        """
        MATCH (c:Case {case_id: $case_id}), (o:Outcome {name: $outcome})
        MERGE (c)-[:RESULTED_IN]->(o)
        """,
        case_id=case.case_id, outcome=case.outcome.value,
    )

    # Parties
    for party in case.parties:
        session.run(
            "MERGE (p:Party {name: $name})",
            name=party.name,
        )
        session.run(
            """
            MATCH (c:Case {case_id: $case_id}), (p:Party {name: $name})
            MERGE (c)-[:INVOLVES_PARTY {role: $role}]->(p)
            """,
            case_id=case.case_id, name=party.name, role=party.role.value,
        )

    # Product markets
    for pm in case.product_markets_considered:
        session.run(
            """
            MERGE (pm:ProductMarket {market_id: $market_id})
            SET pm.name = $name,
                pm.definition_status = $definition_status,
                pm.notes = $notes
            """,
            market_id=f"{case.case_id}_{pm.market_id}",
            name=pm.name,
            definition_status=pm.definition_status.value,
            notes=pm.notes,
        )
        session.run(
            """
            MATCH (c:Case {case_id: $case_id}),
                  (pm:ProductMarket {market_id: $market_id})
            MERGE (c)-[:CONSIDERED_PRODUCT_MARKET]->(pm)
            """,
            case_id=case.case_id,
            market_id=f"{case.case_id}_{pm.market_id}",
        )

    # Geographic markets
    for gm in case.geographic_markets_considered:
        session.run(
            """
            MERGE (gm:GeographicMarket {market_id: $market_id})
            SET gm.name = $name,
                gm.definition_status = $definition_status,
                gm.notes = $notes
            """,
            market_id=f"{case.case_id}_{gm.market_id}",
            name=gm.name,
            definition_status=gm.definition_status.value,
            notes=gm.notes,
        )
        session.run(
            """
            MATCH (c:Case {case_id: $case_id}),
                  (gm:GeographicMarket {market_id: $market_id})
            MERGE (c)-[:CONSIDERED_GEOGRAPHIC_MARKET]->(gm)
            """,
            case_id=case.case_id,
            market_id=f"{case.case_id}_{gm.market_id}",
        )

    # Theories of harm
    for toh in case.theories_of_harm:
        session.run(
            """
            MERGE (t:TheoryOfHarm {theory_id: $theory_id})
            SET t.name = $name, t.description = $description
            """,
            theory_id=f"{case.case_id}_{toh.theory_id}",
            name=toh.name,
            description=toh.description,
        )
        session.run(
            """
            MATCH (c:Case {case_id: $case_id}),
                  (t:TheoryOfHarm {theory_id: $theory_id})
            MERGE (c)-[:APPLIES_THEORY]->(t)
            """,
            case_id=case.case_id,
            theory_id=f"{case.case_id}_{toh.theory_id}",
        )

    # Source documents
    for doc in case.source_documents:
        session.run(
            """
            MERGE (sd:SourceDocument {doc_id: $doc_id})
            SET sd.title = $title,
                sd.url = $url,
                sd.doc_type = $doc_type,
                sd.date = $date
            """,
            doc_id=doc.doc_id,
            title=doc.title,
            url=doc.url,
            doc_type=doc.doc_type,
            date=doc.published_date.isoformat() if doc.published_date else None,
        )
        session.run(
            """
            MATCH (c:Case {case_id: $case_id}), (sd:SourceDocument {doc_id: $doc_id})
            MERGE (c)-[:HAS_SOURCE]->(sd)
            """,
            case_id=case.case_id, doc_id=doc.doc_id,
        )

    # Source passages
    for sp in case.source_passages:
        session.run(
            """
            MERGE (sp:SourcePassage {passage_id: $passage_id})
            SET sp.quote_snippet = $quote_snippet,
                sp.page = $page,
                sp.paragraph = $paragraph,
                sp.section = $section,
                sp.extraction_method = $extraction_method,
                sp.review_status = $review_status,
                sp.confidence_score = $confidence_score,
                sp.last_checked_date = $last_checked_date
            """,
            passage_id=sp.passage_id,
            quote_snippet=sp.quote_snippet,
            page=sp.page,
            paragraph=sp.paragraph,
            section=sp.section,
            extraction_method=sp.extraction_method.value,
            review_status=sp.review_status.value,
            confidence_score=sp.confidence_score,
            last_checked_date=sp.last_checked_date.isoformat(),
        )
        # Link passage to its source document
        session.run(
            """
            MATCH (sd:SourceDocument {doc_id: $doc_id}),
                  (sp:SourcePassage {passage_id: $passage_id})
            MERGE (sd)-[:CONTAINS_PASSAGE]->(sp)
            """,
            doc_id=sp.source_document_id,
            passage_id=sp.passage_id,
        )

    # Similar cases (shallow — only creates the rel if both cases exist)
    for sim in case.similar_cases:
        session.run(
            """
            MATCH (c1:Case {case_id: $case_id}), (c2:Case {case_id: $similar_id})
            MERGE (c1)-[r:SIMILAR_TO]->(c2)
            SET r.score = $score, r.method = $method, r.reasons = $reasons
            """,
            case_id=case.case_id,
            similar_id=sim.case_id,
            score=sim.score,
            method=sim.method,
            reasons=sim.reasons,
        )


def main():
    parser = argparse.ArgumentParser(description="Seed CompMap graph from YAML case records")
    parser.add_argument("--cases-dir", default="data/cases", help="Path to cases directory")
    parser.add_argument("--wipe", action="store_true", help="Wipe graph before seeding")
    parser.add_argument("--no-constraints", action="store_true", help="Skip applying constraints/indexes")
    args = parser.parse_args()

    graph_dir = Path(__file__).parent

    print("Connecting to Neo4j...")
    driver = get_driver()

    with driver.session() as session:
        if args.wipe:
            print("Wiping existing graph...")
            wipe_graph(session)

        if not args.no_constraints:
            print("Applying constraints...")
            apply_cypher_file(session, graph_dir / "constraints.cypher")
            print("Applying indexes...")
            apply_cypher_file(session, graph_dir / "indexes.cypher")

        print(f"Loading cases from {args.cases_dir}...")
        ok = 0
        errors = 0
        for path, result in load_all_cases(args.cases_dir):
            if isinstance(result, Exception):
                print(f"  SKIP  {path.name}: {result}")
                errors += 1
            else:
                seed_case(session, result)
                print(f"  OK    {result.case_id}")
                ok += 1

    driver.close()
    print(f"\nDone. {ok} cases seeded, {errors} errors.")
    sys.exit(0 if errors == 0 else 1)


if __name__ == "__main__":
    main()
