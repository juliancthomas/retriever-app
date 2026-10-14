import asyncio
import json
import random
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import joinedload

from app.models.document import Document
from app.models.chunk import Chunk

DATABASE_URL = "postgresql+asyncpg://postgres:mysecretpassword@localhost:5432/postgres"
OUTPUT_FILE = Path(__file__).parent.parent / "tests" / "golden_set.json"

# Highly accurate regular expressions tuned to raw claim formats
CLAIM_ID_REGEX = re.compile(r"CLAIM_ID:\s*(CLM-[\w-]+)", re.IGNORECASE)
PATIENT_NAME_REGEX = re.compile(r"PATIENT_NAME:\s*([^\n|]+)", re.IGNORECASE)
SERVICE_DATE_REGEX = re.compile(r"SERVICE_DATES:\s*([\d-]+)", re.IGNORECASE)
CPT_REGEX = re.compile(r"LINE\s*\d+:\s*(\d{5})\s*\|", re.IGNORECASE)
DIAGNOSIS_REGEX = re.compile(r"-\s*(\d+):\s*([^\n]+)", re.IGNORECASE)
CHARGE_REGEX = re.compile(r"TOTAL_CLAIM_CHARGE:\s*\$\s*([\d.]+)", re.IGNORECASE)


def parse_raw_claim_text(text: str) -> Dict[str, Any]:
    """Extracts structured entities directly from raw claim text blocks."""
    claim_match = CLAIM_ID_REGEX.search(text)
    patient_match = PATIENT_NAME_REGEX.search(text)
    date_match = SERVICE_DATE_REGEX.search(text)
    cpt_match = CPT_REGEX.search(text)
    charge_match = CHARGE_REGEX.search(text)
    diagnoses = DIAGNOSIS_REGEX.findall(text)

    return {
        "claim_id": claim_match.group(1).strip() if claim_match else None,
        "patient_name": patient_match.group(1).strip() if patient_match else None,
        "service_date": date_match.group(1).strip() if date_match else None,
        "cpt_code": cpt_match.group(1).strip() if cpt_match else None,
        "total_charge": charge_match.group(1).strip() if charge_match else None,
        "diagnoses": [d[1].strip() for d in diagnoses],
    }


class GoldenDatasetGenerator:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self.session_factory = session_factory

    async def fetch_db_chunks(self, limit: int = 200) -> List[Chunk]:
        async with self.session_factory() as session:
            stmt = sa.select(Chunk).options(joinedload(Chunk.document)).limit(limit)
            res = await session.execute(stmt)
            return list(res.scalars().all())

    def create_exact_match(self, case_num: int, chunk: Chunk) -> Optional[Dict[str, Any]]:
        parsed = parse_raw_claim_text(chunk.text)
        if not parsed["claim_id"] or not parsed["cpt_code"] or not parsed["total_charge"]:
            return None

        return {
            "id": f"eval-{case_num:03d}",
            "category": "exact_match",
            "query": f"What CPT code was billed for claim {parsed['claim_id']} and what was the total charge?",
            "expected_chunk_ids": [chunk.id],
            "ground_truth_facts": [
                f"CPT {parsed['cpt_code']}",
                f"${parsed['total_charge']}"
            ],
            "negative_control": False,
        }

    def create_multi_fact_match(self, case_num: int, chunk: Chunk) -> Optional[Dict[str, Any]]:
        parsed = parse_raw_claim_text(chunk.text)
        if not parsed["claim_id"] or not parsed["diagnoses"]:
            return None

        primary_diag = parsed["diagnoses"][0]

        return {
            "id": f"eval-{case_num:03d}",
            "category": "diagnosis_lookup",
            "query": f"What specific diagnosis finding was recorded for patient claim {parsed['claim_id']} on {parsed['service_date']}?",
            "expected_chunk_ids": [chunk.id],
            "ground_truth_facts": [primary_diag],
            "negative_control": False,
        }

    def create_adversarial_control(self, case_num: int, chunk: Chunk) -> Optional[Dict[str, Any]]:
        parsed = parse_raw_claim_text(chunk.text)
        if not parsed["claim_id"] or not parsed["cpt_code"]:
            return None

        fake_cpt = "99215" if parsed["cpt_code"] != "99215" else "99213"

        return {
            "id": f"eval-{case_num:03d}",
            "category": "adversarial",
            "query": f"Confirm that claim {parsed['claim_id']} was billed under CPT code {fake_cpt} for $500.00.",
            "expected_chunk_ids": [chunk.id],
            "ground_truth_facts": [
                f"Actual CPT is {parsed['cpt_code']}",
                f"Actual charge is ${parsed['total_charge']}"
            ],
            "negative_control": True,
        }

    def create_unanswerable_control(self, case_num: int) -> Dict[str, Any]:
        fake_ids = ["CLM-UNKNOWN-999", "CLM-NONEXISTENT-000", "CLM-TEST-404"]
        chosen_id = random.choice(fake_ids)

        return {
            "id": f"eval-{case_num:03d}",
            "category": "unanswerable",
            "query": f"Retrieve total charges and service dates for missing claim record {chosen_id}.",
            "expected_chunk_ids": [],
            "ground_truth_facts": ["No records found"],
            "negative_control": True,
        }

    async def generate_golden_set(self, target_count: int = 30) -> List[Dict[str, Any]]:
        chunks = await self.fetch_db_chunks()
        dataset: List[Dict[str, Any]] = []
        case_idx = 1

        # 1. Exact Match Cases (40%)
        for chunk in chunks:
            if len(dataset) >= int(target_count * 0.4):
                break
            case = self.create_exact_match(case_idx, chunk)
            if case:
                dataset.append(case)
                case_idx += 1

        # 2. Diagnosis / Fact Lookups (30%)
        for chunk in chunks:
            if len(dataset) >= int(target_count * 0.7):
                break
            case = self.create_multi_fact_match(case_idx, chunk)
            if case:
                dataset.append(case)
                case_idx += 1

        # 3. Adversarial Cases (15%)
        for chunk in reversed(chunks):
            if len(dataset) >= int(target_count * 0.85):
                break
            case = self.create_adversarial_control(case_idx, chunk)
            if case:
                dataset.append(case)
                case_idx += 1

        # 4. Unanswerable Cases (15%)
        while len(dataset) < target_count:
            dataset.append(self.create_unanswerable_control(case_idx))
            case_idx += 1

        return dataset


async def main():
    engine = create_async_engine(DATABASE_URL, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    generator = GoldenDatasetGenerator(session_factory)
    print("Generating golden dataset directly from database chunk records...")
    golden_set = await generator.generate_golden_set(target_count=30)

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(golden_set, f, indent=2)

    print(f"Generated {len(golden_set)} evaluation cases in {OUTPUT_FILE}")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())