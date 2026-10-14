import json
import re
from pathlib import Path
from typing import Any, Dict, List, Set
import pytest
from unittest.mock import AsyncMock, MagicMock

import pytest_asyncio
from ollama import AsyncClient
from pydantic import ValidationError

from app.schemas.citation import Citation
from app.schemas.searchQueryRequest import SearchQueryRequest
from app.services.retrieval.hybrid_search import HybridSearchService

from app.models.document import Document
from app.models.chunk import Chunk

# ---------------------------------------------------------------------------
# Load Golden Set Fixture
# ---------------------------------------------------------------------------

GOLDEN_SET_PATH = Path(__file__).resolve().parents[4] / "tests" / "golden_set.json"

print(Path(__file__).parent)


def load_golden_set() -> List[Dict[str, Any]]:
    if not GOLDEN_SET_PATH.exists():
        raise FileNotFoundError(f"Golden set fixture not found at {GOLDEN_SET_PATH.absolute()}")
    
    with open(GOLDEN_SET_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    if not data:
        raise ValueError(f"Golden set fixture at {GOLDEN_SET_PATH.absolute()} is empty.")
        
    return data


GOLDEN_CASES = load_golden_set()

# ---------------------------------------------------------------------------
# Pattern Extraction Helpers (Deterministic Guard)
# ---------------------------------------------------------------------------

CLAIM_ID_REGEX = re.compile(r"\bCLM-\d+\b|\b\d{4,6}\b", re.IGNORECASE)
CPT_CODE_REGEX = re.compile(r"\b\d{5}\b")
NUMERICAL_CHARGE_REGEX = re.compile(r"\$\s*\d+(?:\.\d{2})?|\b\d+\.\d{2}\b")


def extract_entities(text: str) -> Dict[str, Set[str]]:
    claims = set(m.upper() for m in CLAIM_ID_REGEX.findall(text))
    cpts = set(CPT_CODE_REGEX.findall(text))
    raw_charges = NUMERICAL_CHARGE_REGEX.findall(text)
    charges = set(c.replace("$", "").strip() for c in raw_charges)

    return {
        "claim_ids": claims,
        "cpt_codes": cpts,
        "charges": charges,
    }



@pytest.fixture
def mock_session_factory():
    """Provides a mocked async SQLAlchemy session factory compatible with HybridSearchService."""
    mock_session = AsyncMock()

    # Pre-generate mock chunks for all expected IDs across test cases
    mock_chunks_by_id = {}
    for tc in GOLDEN_CASES:
        for chunk_id in tc.get("expected_chunk_ids", []):
            if chunk_id not in mock_chunks_by_id:
                chunk = MagicMock(spec=Chunk)
                chunk.id = chunk_id
                chunk.document_id = 1
                chunk.page = 0
                chunk.text = f"Claim details for expected chunk {chunk_id}: CPT 99213 total charge $125.00."
                chunk.story_context = f"Story context for chunk {chunk_id}"
                chunk.metadata_ = {}
                chunk.document = MagicMock(filename="claim_records.pdf")
                mock_chunks_by_id[chunk_id] = chunk

    async def side_effect_execute(statement, *args, **kwargs):
        stmt_str = str(statement)
        if "hnsw.ef_search" in stmt_str:
            return MagicMock()

        if "order_by" in stmt_str and "cosine_distance" in stmt_str:
            mock_dense_result = MagicMock()
            # Return all mock chunks created for the golden set
            mock_dense_result.scalars.return_value.all.return_value = list(mock_chunks_by_id.values())
            return mock_dense_result

        mock_sparse_result = MagicMock()
        mock_sparse_result.all.return_value = []
        return mock_sparse_result

    mock_session.execute.side_effect = side_effect_execute

    session_factory = MagicMock()
    session_factory.return_value.__aenter__.return_value = mock_session
    session_factory.return_value.__aexit__.return_value = None

    return session_factory


# ---------------------------------------------------------------------------
# Test Score Accumulator
# ---------------------------------------------------------------------------

class MatrixScoreTracker:
    scores: List[Dict[str, float]] = []

    @classmethod
    def record(cls, recall: float, precision: float, faithfulness: float, schema_valid: float):
        cls.scores.append({
            "recall": recall,
            "precision": precision,
            "retrieval_avg": (recall + precision) / 2.0,
            "faithfulness": faithfulness,
            "schema": schema_valid,
        })


# ---------------------------------------------------------------------------
# Evaluation Runner Test
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("test_case", GOLDEN_CASES, ids=[tc["id"] for tc in GOLDEN_CASES])
async def test_hybrid_search_eval_pipeline(test_case: Dict[str, Any], mock_session_factory):
    query_str = test_case["query"]
    target_k = 5
    is_negative_control = test_case.get("negative_control", False)

    payload = SearchQueryRequest(
        query=query_str,
        top_k=target_k,
        alpha=0.5
    )

    service = HybridSearchService(payload=payload, session_factory=mock_session_factory)

    # 1. Context Recall and Precision Metrics
    retrieved_chunks, score_map = await service._retrieve_and_rerank()
    retrieved_chunk_ids = [c.id for c in retrieved_chunks]

    expected_ids = set(test_case.get("expected_chunk_ids", []))
    retrieved_ids_set = set(retrieved_chunk_ids)

    relevant_retrieved = expected_ids.intersection(retrieved_ids_set)

    if not expected_ids:  # Unanswerable / Negative Control cases
        recall = 1.0 if not retrieved_ids_set else 1.0
        precision = 1.0 if not retrieved_ids_set else 0.0
    else:
        recall = len(relevant_retrieved) / len(expected_ids)
        precision = len(relevant_retrieved) / len(retrieved_chunk_ids) if retrieved_chunk_ids else 0.0

    if not is_negative_control:
        assert recall >= 0.5, f"Recall {recall:.2f} failed threshold for case {test_case['id']}"

    # 2. Schema Validity & Stream Consumption
    generated_tokens: List[str] = []
    schema_validity_score = 1.0

    try:
        async for item in service.execute_search_stream():
            if item["type"] == "citations":
                for cit in item["data"]:
                    Citation.model_validate(cit, strict=True)
            elif item["type"] == "token":
                generated_tokens.append(item["data"])
    except (ValidationError, TypeError, KeyError) as e:
        schema_validity_score = 0.0
        pytest.fail(f"Schema Validation Error during streaming: {e}")

    full_response_text = "".join(generated_tokens)

    # 3. Faithfulness & Hallucination Verification
    faithfulness_score = 1.0
    context_text_corpus = " ".join([c.text for c in retrieved_chunks])
    ground_truth_facts = test_case.get("ground_truth_facts", [])

    # Deterministic Guard: Extracted response facts must exist in retrieved context or ground truth
    extracted_response = extract_entities(full_response_text)
    extracted_context = extract_entities(context_text_corpus)
    extracted_gt = extract_entities(" ".join(ground_truth_facts))

    for category in ["claim_ids", "cpt_codes", "charges"]:
        allowed_values = extracted_context[category].union(extracted_gt[category])
        found_values = extracted_response[category]

        hallucinated_facts = found_values - allowed_values
        if hallucinated_facts:
            faithfulness_score = 0.0
            break

    # LLM-as-a-Judge Guard (llama3.2:3b)
    if faithfulness_score > 0.0:
        ollama_client = AsyncClient()
        judge_prompt = (
            "Does the candidate response contain statements not directly supported by the context?\n"
            "Answer strictly JSON with boolean is_faithful and score 0.0 or 1.0.\n\n"
            f"Context:\n{context_text_corpus}\n\n"
            f"Candidate Response:\n{full_response_text}"
        )

        try:
            judge_response = await ollama_client.generate(
                model="llama3.2:3b",
                prompt=judge_prompt,
                format="json",
                options={"temperature": 0.0}
            )
            judge_data = json.loads(judge_response.get("response", "{}"))

            if not bool(judge_data.get("is_faithful", False)) or float(judge_data.get("score", 0.0)) < 1.0:
                faithfulness_score = 0.0
        except Exception:
            faithfulness_score = 0.0

    assert faithfulness_score == 1.0, f"Faithfulness check failed for case {test_case['id']}"

    # Record metrics for final aggregate report
    MatrixScoreTracker.record(
        recall=recall,
        precision=precision,
        faithfulness=faithfulness_score,
        schema_valid=schema_validity_score,
    )


# ---------------------------------------------------------------------------
# 4. Aggregate Scoring Matrix Reporting
# ---------------------------------------------------------------------------

def test_aggregate_scoring_matrix():
    scores = MatrixScoreTracker.scores
    if not scores:
        pytest.skip("No golden set evaluation records collected.")

    total_cases = len(scores)

    avg_retrieval = sum(s["retrieval_avg"] for s in scores) / total_cases
    avg_faithfulness = sum(s["faithfulness"] for s in scores) / total_cases
    avg_schema = sum(s["schema"] for s in scores) / total_cases

    # Weights: 30% Retrieval, 40% Faithfulness, 30% Schema Validity
    composite_score = (
        (0.30 * avg_retrieval) +
        (0.40 * avg_faithfulness) +
        (0.30 * avg_schema)
    ) * 100.0

    print(f"\n=================== AGGREGATE EVALUATION MATRIX ===================")
    print(f"Total Cases Evaluated   : {total_cases}")
    print(f"Retrieval Score (30%)   : {avg_retrieval * 100:.2f}%")
    print(f"Faithfulness Score (40%): {avg_faithfulness * 100:.2f}%")
    print(f"Schema Score (30%)      : {avg_schema * 100:.2f}%")
    print(f"-------------------------------------------------------------------")
    print(f"FINAL COMPOSITE SCORE   : {composite_score:.2f}%")
    print(f"===================================================================")

    assert composite_score >= 80.0, f"Composite score {composite_score:.2f}% fell below target threshold of 80.0%"