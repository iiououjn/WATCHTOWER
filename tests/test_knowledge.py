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


def test_hits_carry_the_full_chunk_text(conn):
    kb = Knowledge(conn)
    text = "Glass layers filter what the beacon passes down. " + "Each floor has its own rules. " * 20
    kb.add(text, "spec")
    hit = kb.search("glass layers")[0]
    assert hit.text.startswith("Glass layers filter") and len(hit.text) > len(hit.snippet)


def test_common_words_do_not_drive_matches(conn):
    kb = Knowledge(conn)
    kb.add("The cat sat in the hall of the house of the king.", "noise")
    lid = kb.add("Glass layer rules protect floor input.", "signal")
    hits = kb.search("explain the glass layer of the tower")
    assert [h.doc_id for h in hits] == [lid]


def test_only_stopwords_returns_nothing(conn):
    kb = Knowledge(conn)
    kb.add(LIGHTHOUSE, "a")
    assert kb.search("the of and in") == []


def test_agents_can_get_several_chunks_from_one_document(conn):
    kb = Knowledge(conn)
    paras = [f"Section {i}: glass layer rule number {i}. " + "filler words here. " * 70 for i in range(4)]
    doc = kb.add("\n\n".join(paras), "spec")
    assert len(kb.search("glass layer rule")) == 1
    chunks = kb.search("glass layer rule", limit=3, distinct=False)
    assert len(chunks) == 3 and {h.doc_id for h in chunks} == {doc}
    assert len({h.text for h in chunks}) == 3
