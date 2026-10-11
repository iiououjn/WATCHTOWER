import pytest

from watchtower.engine.knowledge import Knowledge

LIGHTHOUSE = "A lighthouse beacon rotates so ships see a flashing light from every direction."
BREAD = "Sourdough bread needs a starter, flour, water and salt."


def test_search_ranks_relevant_doc_first(conn):
    kb = Knowledge(conn)
    kb.add(BREAD, "https://bread.example", "Bread")
    lid = kb.add(LIGHTHOUSE, "https://lights.example", "Lighthouses")
    hits = kb.search("why does a lighthouse rotate its beacon")
    assert hits[0].doc_id == lid
    assert hits[0].source == "https://lights.example"
    assert "beacon" in hits[0].snippet


def test_web_content_is_untrusted_by_default(conn):
    kb = Knowledge(conn)
    kb.add(LIGHTHOUSE, "https://lights.example")
    kb.add(BREAD, "file:///notes/bread.md", trusted=True)
    trust = {h.source: h.trusted for h in kb.search("lighthouse bread")}
    assert trust == {"https://lights.example": False, "file:///notes/bread.md": True}


def test_same_text_is_stored_once(conn):
    kb = Knowledge(conn)
    assert kb.add(LIGHTHOUSE, "a") == kb.add(LIGHTHOUSE, "b")
    assert kb.count() == 1


@pytest.mark.parametrize("query", ['"', "*", "NEAR(", "AND OR NOT", "beacon\"; DROP TABLE x", "(((", "-"])
def test_fts_syntax_in_query_never_crashes(conn, query):
    kb = Knowledge(conn)
    kb.add(LIGHTHOUSE, "a")
    kb.search(query)


def test_empty_query_returns_nothing(conn):
    kb = Knowledge(conn)
    kb.add(LIGHTHOUSE, "a")
    assert kb.search("   ") == []


def test_long_document_chunked_one_hit_per_doc(conn):
    kb = Knowledge(conn)
    filler = "\n\n".join(f"Paragraph {i} about harbours and tides." * 10 for i in range(20))
    doc = kb.add(filler + "\n\nThe Fresnel lens was invented in 1822.", "long")
    hits = kb.search("fresnel lens harbours")
    assert [h.doc_id for h in hits] == [doc]


def test_workspaces_are_isolated(conn):
    Knowledge(conn, workspace_id="a").add(LIGHTHOUSE, "a")
    assert Knowledge(conn, workspace_id="b").search("lighthouse") == []


@pytest.mark.parametrize("text,source", [("", "a"), ("   ", "a"), ("x", ""), ("x", "  ")])
def test_rejects_blank_text_or_source(conn, text, source):
    with pytest.raises(ValueError):
        Knowledge(conn).add(text, source)


def test_unicode_search(conn):
    kb = Knowledge(conn)
    doc = kb.add("Le phare de Cordouan éclaire l'estuaire.", "fr")
    assert kb.search("phare")[0].doc_id == doc
