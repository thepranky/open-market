#!/usr/bin/env python3
"""
Seed Neo4j with case records from data/cases/, indexed cases from data/case_index/,
and concept nodes from data/concepts/.

Usage:
  python graph/seed_graph.py [--cases-dir data/cases] [--case-index-dir data/case_index]
                             [--concepts-dir data/concepts] [--wipe]

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
from app.cases.loader.yaml_loader import load_all_cases
from app.cases.loader.index_loader import load_all_index_cases
from app.cases.loader.concept_loader import load_all_concepts
from app.cases.models import CaseRecord
from app.cases.models.case_index import CaseIndexEntry
from app.cases.models.concept import ConceptNode


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


def _seed_jurisdiction_authority(session, jurisdiction: str, authority: str):
    session.run(
        "MERGE (j:Jurisdiction {name: $name})",
        name=jurisdiction,
    )
    session.run(
        "MERGE (a:Authority {name: $name}) SET a.jurisdiction = $jurisdiction",
        name=authority, jurisdiction=jurisdiction,
    )
    session.run(
        """
        MATCH (j:Jurisdiction {name: $jur}), (a:Authority {name: $auth})
        MERGE (j)-[:HAS_AUTHORITY]->(a)
        """,
        jur=jurisdiction, auth=authority,
    )


def _seed_sector_outcome(session, case_id: str, sector: str, outcome_value: str):
    session.run("MERGE (s:Sector {name: $name})", name=sector)
    session.run(
        """
        MATCH (c:Case {case_id: $case_id}), (s:Sector {name: $sector})
        MERGE (c)-[:CONCERNS_SECTOR]->(s)
        """,
        case_id=case_id, sector=sector,
    )
    session.run("MERGE (o:Outcome {name: $name})", name=outcome_value)
    session.run(
        """
        MATCH (c:Case {case_id: $case_id}), (o:Outcome {name: $outcome})
        MERGE (c)-[:RESULTED_IN]->(o)
        """,
        case_id=case_id, outcome=outcome_value,
    )


def _seed_concept_refs(session, case_id: str, concept_refs):
    for ref in concept_refs:
        session.run(
            """
            MATCH (c:Case {case_id: $case_id}), (co:Concept {concept_id: $concept_id})
            MERGE (c)-[r:REFERENCES_CONCEPT]->(co)
            SET r.quality_level = $quality_level, r.provenance = $provenance
            """,
            case_id=case_id,
            concept_id=ref.concept_id,
            quality_level=ref.quality_level,
            provenance=ref.provenance,
        )


def seed_case(session, case: CaseRecord):
    _seed_jurisdiction_authority(session, case.jurisdiction, case.authority)

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
            c.ai_summary = $ai_summary,
            c.data_layer = 'canonical',
            c.record_status = 'canonical_reviewed'
        """,
        **case.to_graph_dict(),
    )

    session.run(
        """
        MATCH (a:Authority {name: $auth}), (c:Case {case_id: $case_id})
        MERGE (a)-[:DECIDED]->(c)
        """,
        auth=case.authority, case_id=case.case_id,
    )

    _seed_sector_outcome(session, case.case_id, case.sector, case.outcome.value)

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
        session.run(
            """
            MATCH (sd:SourceDocument {doc_id: $doc_id}),
                  (sp:SourcePassage {passage_id: $passage_id})
            MERGE (sd)-[:CONTAINS_PASSAGE]->(sp)
            """,
            doc_id=sp.source_document_id,
            passage_id=sp.passage_id,
        )

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

    _seed_concept_refs(session, case.case_id, case.concept_refs)


def seed_index_case(session, entry: CaseIndexEntry):
    _seed_jurisdiction_authority(session, entry.jurisdiction, entry.authority)

    session.run(
        """
        MERGE (c:Case {case_id: $case_id})
        SET c.case_name = $case_name,
            c.jurisdiction = $jurisdiction,
            c.authority = $authority,
            c.decision_date = $decision_date,
            c.case_type = $case_type,
            c.sector = $sector,
            c.outcome = $outcome,
            c.ai_summary = $ai_summary,
            c.source_url = $source_url,
            c.data_layer = 'indexed',
            c.record_status = 'indexed_metadata'
        """,
        case_id=entry.case_id,
        case_name=entry.case_name,
        jurisdiction=entry.jurisdiction,
        authority=entry.authority,
        decision_date=entry.decision_date.isoformat(),
        case_type=entry.case_type,
        sector=entry.sector,
        outcome=entry.outcome.value,
        ai_summary=entry.ai_summary,
        source_url=entry.source_url,
    )

    session.run(
        """
        MATCH (a:Authority {name: $auth}), (c:Case {case_id: $case_id})
        MERGE (a)-[:DECIDED]->(c)
        """,
        auth=entry.authority, case_id=entry.case_id,
    )

    _seed_sector_outcome(session, entry.case_id, entry.sector, entry.outcome.value)

    for party in entry.parties:
        session.run(
            "MERGE (p:Party {name: $name})",
            name=party.name,
        )
        session.run(
            """
            MATCH (c:Case {case_id: $case_id}), (p:Party {name: $name})
            MERGE (c)-[:INVOLVES_PARTY {role: $role}]->(p)
            """,
            case_id=entry.case_id, name=party.name, role=party.role.value,
        )

    _seed_concept_refs(session, entry.case_id, entry.concept_refs)


def seed_concept(session, concept: ConceptNode):
    session.run(
        """
        MERGE (co:Concept {concept_id: $concept_id})
        SET co.name = $name,
            co.category = $category,
            co.description = $description,
            co.aliases = $aliases
        """,
        concept_id=concept.concept_id,
        name=concept.name,
        category=concept.category,
        description=concept.description,
        aliases=concept.aliases,
    )


def main():
    parser = argparse.ArgumentParser(description="Seed Meridian graph from YAML records")
    parser.add_argument("--cases-dir", default="data/cases", help="Path to canonical cases directory")
    parser.add_argument("--case-index-dir", default=None, help="Path to indexed cases directory")
    parser.add_argument("--concepts-dir", default=None, help="Path to concepts directory")
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

        if args.concepts_dir:
            print(f"Loading concepts from {args.concepts_dir}...")
            ok = errors = 0
            for path, result in load_all_concepts(args.concepts_dir):
                if isinstance(result, Exception):
                    print(f"  SKIP  {path.name}: {result}")
                    errors += 1
                else:
                    seed_concept(session, result)
                    print(f"  OK    {result.concept_id}")
                    ok += 1
            print(f"  Concepts: {ok} seeded, {errors} errors.")

        print(f"Loading canonical cases from {args.cases_dir}...")
        ok = errors = 0
        for path, result in load_all_cases(args.cases_dir):
            if isinstance(result, Exception):
                print(f"  SKIP  {path.name}: {result}")
                errors += 1
            else:
                seed_case(session, result)
                print(f"  OK    {result.case_id}")
                ok += 1
        canonical_errors = errors
        print(f"  Canonical: {ok} seeded, {errors} errors.")

        indexed_errors = 0
        if args.case_index_dir:
            print(f"Loading indexed cases from {args.case_index_dir}...")
            ok = errors = 0
            for path, result in load_all_index_cases(args.case_index_dir):
                if isinstance(result, Exception):
                    print(f"  SKIP  {path.name}: {result}")
                    errors += 1
                else:
                    seed_index_case(session, result)
                    print(f"  OK    {result.case_id}")
                    ok += 1
            indexed_errors = errors
            print(f"  Indexed: {ok} seeded, {errors} errors.")

    driver.close()
    total_errors = canonical_errors + indexed_errors
    print(f"\nDone. Total errors: {total_errors}.")
    sys.exit(0 if total_errors == 0 else 1)


if __name__ == "__main__":
    main()
