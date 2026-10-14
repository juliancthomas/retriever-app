import json
import logging
import re
from pathlib import Path
from jinja2 import Template

CLAIM_TEMPLATE = """
=== RAW CLAIM RECORD ===
CLAIM_ID: {{ claim_id }}
ENCOUNTER_ID: {{ encounter_id }}
FILING_DATE: {{ filing_date }}
PATIENT_NAME: {{ patient_name }}
DOB: {{ dob }} | GENDER: {{ gender }}
INSURANCE_ID: {{ subscriber_id }} | PAYER: {{ payer_name }}

SERVICE_DATES: {{ start_date }} TO {{ end_date }}
POS_CODE: {{ place_of_service }}

DIAGNOSES (ICD-10-CM):
{% for diag in diagnoses %}
 - {{ diag.code }}: {{ diag.display }}
{% else %}
 - Z00.00: Encounter for general adult medical examination without abnormal findings
{% endfor %}

PROCEDURES & CHARGES (CPT/HCPCS):
{% for proc in procedures %}
 - LINE {{ loop.index }}: {{ proc.code }} | {{ proc.display }} | QTY: 1 | FEE: ${{ "%.2f"|format(proc.cost) }}
{% else %}
 - LINE 1: 99213 | Office or other outpatient visit | QTY: 1 | FEE: $125.00
{% endfor %}

TOTAL_CLAIM_CHARGE: ${{ "%.2f"|format(total_charge) }}
STATUS: SUBMITTED
========================
"""

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - [%(name)s] %(message)s"
)
logger = logging.getLogger("ingestion")

CPT_FEE_SCHEDULE = {
    "99213": 125.00,
    "99214": 175.00,
    "99215": 230.00,
    "45378": 850.00,
    "90686": 40.00,
    "96372": 45.00,
    "D0120": 65.00,
    "D1110": 95.00,
}
DEFAULT_PROCEDURE_FEE = 150.00

def clean_uuid(ref_string: str | None) -> str:
    """Extracts raw UUID from FHIR references like 'Encounter/1234' or 'urn:uuid:1234'."""
    if not ref_string:
        return ""
    match = re.search(r'([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})', ref_string)
    return match.group(1).lower() if match else ref_string.lower()

def extract_coding_system(coding_list: list, preferred_system: str) -> dict | None:
    for coding in coding_list:
        system = coding.get('system', '')
        if preferred_system in system:
            return {
                'code': coding.get('code'),
                'display': coding.get('display')
            }
    return None

def process_synthea_bundle(file_path: str, output_dir: str):
    path = Path(file_path)
    with open(path, 'r', encoding='utf-8') as f:
        bundle = json.load(f)
    
    entries = bundle.get('entry', [])
    
    # 1. Extract Patient Metadata
    patient_name, dob, gender = "UNKNOWN", "UNKNOWN", "UNKNOWN"
    for entry in entries:
        res = entry.get('resource', {})
        if res.get('resourceType') == 'Patient':
            names = res.get('name', [{}])[0]
            family = names.get('family', '')
            given = names.get('given', [''])[0]
            patient_name = f"{family}, {given}"
            dob = res.get('birthDate', 'UNKNOWN')
            gender = res.get('gender', 'UNKNOWN')
            break

    # 2. Extract Encounters, Conditions, Procedures
    encounters = [e.get('resource') for e in entries if e.get('resource', {}).get('resourceType') == 'Encounter']
    conditions = [e.get('resource') for e in entries if e.get('resource', {}).get('resourceType') == 'Condition']
    procedures = [e.get('resource') for e in entries if e.get('resource', {}).get('resourceType') == 'Procedure']

    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    
    generated_files = []

    # 3. Process Encounters
    for idx, enc in enumerate(encounters, start=1):
        raw_enc_id = enc.get('id', '')
        enc_id_clean = clean_uuid(raw_enc_id)
        
        # Service Dates & POS
        period = enc.get('period', {})
        start_date = period.get('start', '2026-01-10')[:10]
        end_date = period.get('end', start_date)[:10]
        
        pos_code = "11 (Office)"
        if 'class' in enc:
            cls = enc['class']
            pos_code = cls.get('code') if isinstance(cls, dict) else str(cls)

        # Filter Conditions matching cleaned Encounter ID
        enc_diagnoses = []
        for cond in conditions:
            cond_enc_ref = clean_uuid(cond.get('encounter', {}).get('reference'))
            if cond_enc_ref == enc_id_clean:
                codings = cond.get('code', {}).get('coding', [])
                icd_match = extract_coding_system(codings, "icd-10")
                if icd_match:
                    enc_diagnoses.append(icd_match)
                elif codings:
                    enc_diagnoses.append({'code': codings[0].get('code'), 'display': codings[0].get('display')})

        # Fallback: Check Encounter.reasonCode if no Condition resource linked
        if not enc_diagnoses and 'reasonCode' in enc:
            for reason in enc.get('reasonCode', []):
                codings = reason.get('coding', [])
                icd_match = extract_coding_system(codings, "icd-10")
                if icd_match:
                    enc_diagnoses.append(icd_match)

        # Filter Procedures matching cleaned Encounter ID
        enc_procedures = []
        for proc in procedures:
            proc_enc_ref = clean_uuid(proc.get('encounter', {}).get('reference'))
            if proc_enc_ref == enc_id_clean:
                codings = proc.get('code', {}).get('coding', [])
                cpt_match = extract_coding_system(codings, "cpt") or extract_coding_system(codings, "hcpcs")
                
                if cpt_match:
                    code = cpt_match['code']
                    display = cpt_match['display']
                elif codings:
                    code = codings[0].get('code')
                    display = codings[0].get('display')
                else:
                    continue

                fee = CPT_FEE_SCHEDULE.get(code, DEFAULT_PROCEDURE_FEE)
                enc_procedures.append({
                    'code': code,
                    'display': display,
                    'cost': fee
                })

        enc_procedures = enc_procedures[:6]
        total_charge = sum(p['cost'] for p in enc_procedures)
        if not enc_procedures:
            total_charge = 125.00

        # Unique Claim ID per encounter file
        claim_id = f"CLM-{path.stem[:8].upper()}-{idx:03d}"

        template = Template(CLAIM_TEMPLATE)
        rendered_claim = template.render(
            claim_id=claim_id,
            encounter_id=raw_enc_id,
            filing_date="2026-01-15",
            patient_name=patient_name,
            dob=dob,
            gender=gender,
            subscriber_id="SUB-994821",
            payer_name="Medicare",
            start_date=start_date,
            end_date=end_date,
            place_of_service=pos_code,
            diagnoses=enc_diagnoses[:4],
            procedures=enc_procedures,
            total_charge=total_charge
        )

        output_file_path = out_path / f"{claim_id}.txt"
        with open(output_file_path, 'w', encoding='utf-8') as out_f:
            out_f.write(rendered_claim)
            
        logger.info(f"Generated text claim: {output_file_path}")
        generated_files.append(str(output_file_path))

    return generated_files

if __name__ == "__main__":
    raw_claims_dir = Path("C:/Users/Julian/Desktop/synthea/output/fhir_test")
    output_claims_dir = Path("C:/Users/Julian/Desktop/synthea/output/claims")

    json_files = list(raw_claims_dir.glob("*.json"))

    for file_path in json_files:
        process_synthea_bundle(file_path=str(file_path), output_dir=str(output_claims_dir))