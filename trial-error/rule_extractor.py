#!/usr/bin/env python3
"""
Rule Extraction from RBI Circulars using Gemini API
Updated with robust type handling and sanitization
"""

import os
import json
import re
import hashlib
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple, Union
from datetime import datetime

import pdfplumber
from google import genai
from google.genai import types
import jsonschema
from jsonschema import validate
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configuration
MODEL_NAME = "gemini-flash-latest"  # or "gemini-1.5-flash"
MAX_CHUNK_SIZE = 5000

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# Updated Schema with all fields allowing null for flexibility
# ----------------------------------------------------------------------

RULE_SCHEMA = {
    "type": "object",
    "properties": {
        "rule_id": {"type": "string"},
        "version": {"type": "string"},
        "status": {"type": "string", "enum": ["ACTIVE", "SUPERSEDED", "DRAFT"]},
        "source": {
            "type": "object",
            "properties": {
                "circular_id": {"type": "string"},
                "circular_date": {"type": ["string", "null"]},
                "section": {"type": ["string", "null"]},
                "page": {"type": ["integer", "null"]},
                "clause_text_original": {"type": "string"},
                "clause_text_simplified": {"type": ["string", "null"]},
            },
            "required": ["circular_id", "clause_text_original"]
        },
        "rule_meta": {
            "type": "object",
            "properties": {
                "rule_name": {"type": "string"},
                "domain": {"type": "string"},
                "rule_type": {"type": "string"},
                "severity": {"type": "string", "enum": ["LOW", "MEDIUM", "HIGH"]},
                "actor": {"type": ["string", "null"]},
                "obligation_target": {"type": ["string", "null"]},
                "applies_to_loan_types": {
                    "type": ["array", "null"],
                    "items": {"type": "string"}
                }
            },
            "required": ["rule_name", "domain", "rule_type", "severity"]
        },
        "logic": {
            "type": "object",
            "properties": {
                "threshold_field": {"type": ["string", "null"]},
                "threshold_value": {"type": ["number", "null"]},
                "threshold_currency": {"type": ["string", "null"]},
                "applicability_condition": {"type": ["string", "null"]},
                "violation_condition": {"type": ["string", "null"]},
                "validator_type": {"type": "string", "enum": ["THRESHOLD_LOGICAL", "TEMPORAL", "PERMISSIBLE_ACTION"]},
                "evidence_fields": {
                    "type": ["array", "null"],
                    "items": {"type": "string"}
                }
            },
            "required": ["validator_type"]
        },
        "graph_relations": {
            "type": "object",
            "properties": {
                "supersedes": {"type": ["array", "null"], "items": {"type": "string"}},
                "requires_also_check": {"type": ["array", "null"], "items": {"type": "string"}},
                "exempted_by": {"type": ["array", "null"], "items": {"type": "string"}},
                "conflicts_with": {"type": ["array", "null"], "items": {"type": "string"}}
            }
        },
        "explainability": {
            "type": "object",
            "properties": {
                "violation_explanation_template": {"type": ["string", "null"]},
                "remediation_template": {"type": ["string", "null"]},
                "compliance_explanation_template": {"type": ["string", "null"]}
            }
        }
    },
    "required": ["rule_id", "version", "status", "source", "rule_meta", "logic"]
}

# ----------------------------------------------------------------------
# Rule Sanitization Function - Handles all type conversions
# ----------------------------------------------------------------------

def sanitize_rule(rule: Dict, circular_metadata: Dict) -> Dict:
    """
    Sanitize and fix all type issues in the extracted rule.
    Converts null to appropriate default values and ensures all required fields exist.
    """
    sanitized = {}
    
    # 1. Handle rule_id
    sanitized["rule_id"] = rule.get("rule_id", "R000")
    if not isinstance(sanitized["rule_id"], str):
        sanitized["rule_id"] = "R000"
    
    # 2. Handle version
    sanitized["version"] = rule.get("version", "1.0")
    if not isinstance(sanitized["version"], str):
        sanitized["version"] = "1.0"
    
    # 3. Handle status
    status = rule.get("status", "ACTIVE")
    if status not in ["ACTIVE", "SUPERSEDED", "DRAFT"]:
        status = "ACTIVE"
    sanitized["status"] = status
    
    # 4. Handle source
    source = rule.get("source", {})
    if not isinstance(source, dict):
        source = {}
    
    sanitized["source"] = {
        "circular_id": source.get("circular_id", circular_metadata.get("circular_id", "UNKNOWN")),
        "circular_date": source.get("circular_date", circular_metadata.get("circular_date")),
        "section": source.get("section") if isinstance(source.get("section"), str) else None,
        "page": source.get("page") if isinstance(source.get("page"), (int, float)) and not isinstance(source.get("page"), bool) else None,
        "clause_text_original": source.get("clause_text_original", ""),
        "clause_text_simplified": source.get("clause_text_simplified") if isinstance(source.get("clause_text_simplified"), str) else None,
    }
    
    # Ensure clause_text_original is a string
    if not isinstance(sanitized["source"]["clause_text_original"], str):
        sanitized["source"]["clause_text_original"] = ""
    
    # 5. Handle rule_meta
    rule_meta = rule.get("rule_meta", {})
    if not isinstance(rule_meta, dict):
        rule_meta = {}
    
    # Handle applies_to_loan_types - ensure it's a list
    applies_to = rule_meta.get("applies_to_loan_types")
    if applies_to is None or not isinstance(applies_to, list):
        applies_to = []
    elif isinstance(applies_to, str):
        applies_to = [applies_to]
    
    sanitized["rule_meta"] = {
        "rule_name": rule_meta.get("rule_name", "Unnamed Rule"),
        "domain": rule_meta.get("domain", "GENERAL"),
        "rule_type": rule_meta.get("rule_type", "MANDATE"),
        "severity": rule_meta.get("severity", "MEDIUM") if rule_meta.get("severity") in ["LOW", "MEDIUM", "HIGH"] else "MEDIUM",
        "actor": rule_meta.get("actor") if isinstance(rule_meta.get("actor"), str) else None,
        "obligation_target": rule_meta.get("obligation_target") if isinstance(rule_meta.get("obligation_target"), str) else None,
        "applies_to_loan_types": applies_to
    }
    
    # 6. Handle logic
    logic = rule.get("logic", {})
    if not isinstance(logic, dict):
        logic = {}
    
    # Handle evidence_fields - ensure it's a list
    evidence_fields = logic.get("evidence_fields")
    if evidence_fields is None or not isinstance(evidence_fields, list):
        evidence_fields = []
    elif isinstance(evidence_fields, str):
        evidence_fields = [evidence_fields]
    
    # Handle threshold_value - convert string to number if needed
    threshold_value = logic.get("threshold_value")
    if threshold_value is not None:
        try:
            if isinstance(threshold_value, str):
                # Handle lakhs, crores, etc.
                threshold_value = convert_indian_number(threshold_value)
            elif not isinstance(threshold_value, (int, float)):
                threshold_value = None
        except:
            threshold_value = None
    
    sanitized["logic"] = {
        "threshold_field": logic.get("threshold_field") if isinstance(logic.get("threshold_field"), str) else None,
        "threshold_value": threshold_value,
        "threshold_currency": logic.get("threshold_currency") if isinstance(logic.get("threshold_currency"), str) else None,
        "applicability_condition": logic.get("applicability_condition") if isinstance(logic.get("applicability_condition"), str) else None,
        "violation_condition": logic.get("violation_condition") if isinstance(logic.get("violation_condition"), str) else None,
        "validator_type": logic.get("validator_type", "THRESHOLD_LOGICAL"),
        "evidence_fields": evidence_fields
    }
    
    # Ensure validator_type is valid
    valid_types = ["THRESHOLD_LOGICAL", "TEMPORAL", "PERMISSIBLE_ACTION"]
    if sanitized["logic"]["validator_type"] not in valid_types:
        sanitized["logic"]["validator_type"] = "THRESHOLD_LOGICAL"
    
    # 7. Handle graph_relations - ensure all are lists
    graph_relations = rule.get("graph_relations", {})
    if not isinstance(graph_relations, dict):
        graph_relations = {}
    
    sanitized["graph_relations"] = {
        "supersedes": ensure_list(graph_relations.get("supersedes")),
        "requires_also_check": ensure_list(graph_relations.get("requires_also_check")),
        "exempted_by": ensure_list(graph_relations.get("exempted_by")),
        "conflicts_with": ensure_list(graph_relations.get("conflicts_with"))
    }
    
    # 8. Handle explainability - ensure all are strings
    explainability = rule.get("explainability", {})
    if not isinstance(explainability, dict):
        explainability = {}
    
    sanitized["explainability"] = {
        "violation_explanation_template": explainability.get("violation_explanation_template") if isinstance(explainability.get("violation_explanation_template"), str) else "",
        "remediation_template": explainability.get("remediation_template") if isinstance(explainability.get("remediation_template"), str) else "",
        "compliance_explanation_template": explainability.get("compliance_explanation_template") if isinstance(explainability.get("compliance_explanation_template"), str) else ""
    }
    
    return sanitized


def ensure_list(value: Any) -> List:
    """Convert any value to a list safely."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if item]
    if isinstance(value, str):
        return [value] if value else []
    return []


def convert_indian_number(text: str) -> Optional[float]:
    """
    Convert Indian number format (lakh, crore) to float.
    Examples: "10 lakh" -> 1000000, "1.5 crore" -> 15000000
    """
    if not isinstance(text, str):
        return None
    
    text = text.lower().strip()
    
    # Handle lakh
    if "lakh" in text:
        number = re.search(r"[\d.]+", text)
        if number:
            value = float(number.group())
            return value * 100000
    
    # Handle crore
    elif "crore" in text:
        number = re.search(r"[\d.]+", text)
        if number:
            value = float(number.group())
            return value * 10000000
    
    # Handle regular number
    else:
        try:
            # Remove commas and convert
            clean = text.replace(",", "")
            return float(clean)
        except:
            return None
    
    return None


# ----------------------------------------------------------------------
# Helper Functions
# ----------------------------------------------------------------------

def extract_text_from_pdf(pdf_path: str) -> str:
    """Extract text from a PDF file using pdfplumber."""
    text = ""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page_num, page in enumerate(pdf.pages, 1):
                page_text = page.extract_text()
                if page_text:
                    text += f"\n--- Page {page_num} ---\n{page_text}\n"
    except Exception as e:
        logger.error(f"Error extracting text from PDF: {e}")
        return ""
    return text


def chunk_text(text: str, max_chunk_size: int = MAX_CHUNK_SIZE) -> List[str]:
    """Split text into chunks of roughly max_chunk_size characters, preserving paragraphs."""
    # Split by double newlines (paragraphs)
    paragraphs = text.split("\n\n")
    chunks = []
    current_chunk = []
    current_size = 0
    
    for para in paragraphs:
        para_size = len(para)
        if current_size + para_size > max_chunk_size and current_chunk:
            chunks.append("\n\n".join(current_chunk))
            current_chunk = []
            current_size = 0
        current_chunk.append(para)
        current_size += para_size
    
    if current_chunk:
        chunks.append("\n\n".join(current_chunk))
    
    return chunks


def get_gemini_client() -> genai.Client:
    """Initialize Gemini client using new google.genai package."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError(
            "GEMINI_API_KEY not found. Please set it in .env file or as environment variable.\n"
            "Example: export GEMINI_API_KEY='your-key-here'"
        )
    return genai.Client(api_key=api_key)


def build_extraction_prompt(chunk_text: str, circular_metadata: Dict) -> str:
    """Build the prompt for extracting rules from a chunk."""
    prompt = f"""You are an expert in extracting regulatory rules from RBI banking circulars. Given a chunk of text and metadata, extract ALL compliance rules present in that chunk. Output a JSON array of rule objects.

**Circular Metadata**:
- Circular ID: {circular_metadata.get('circular_id', 'UNKNOWN')}
- Date: {circular_metadata.get('circular_date', 'UNKNOWN')}

**IMPORTANT INSTRUCTIONS**:
1. ALWAYS output a JSON array. Even if no rules found, output []
2. For array fields (applies_to_loan_types, evidence_fields, etc.), always use empty arrays [] if not applicable
3. For string fields, use empty string "" if not applicable
4. For number fields, use null if not applicable
5. Extract numeric values from Indian format (convert "10 lakh" to 1000000, "1 crore" to 10000000)
6. Each rule must have all required fields even if null/empty

**Output Format**:
[
  {{
    "rule_id": "R000",
    "version": "1.0",
    "status": "ACTIVE",
    "source": {{
      "circular_id": "RBI/2024-25/012",
      "circular_date": "2024-06-15",
      "section": "4.2.1",
      "page": null,
      "clause_text_original": "No bank shall require collateral security for loans up to Rs.10 lakh extended to MSE units.",
      "clause_text_simplified": "Banks cannot demand collateral for loans under ₹10 lakh for MSE units."
    }},
    "rule_meta": {{
      "rule_name": "Collateral Prohibition for MSE Loans",
      "domain": "MSME_LENDING",
      "rule_type": "PROHIBITION",
      "severity": "HIGH",
      "actor": "bank",
      "obligation_target": "MSE units",
      "applies_to_loan_types": ["MSE", "MSME"]
    }},
    "logic": {{
      "threshold_field": "loan_amount",
      "threshold_value": 1000000,
      "threshold_currency": "INR",
      "applicability_condition": "loan_amount <= 1000000 AND loan_category in ['MSE', 'MSME']",
      "violation_condition": "collateral_provided == true AND loan_amount <= 1000000 AND loan_category in ['MSE', 'MSME']",
      "validator_type": "THRESHOLD_LOGICAL",
      "evidence_fields": ["loan_amount", "collateral_provided", "loan_category"]
    }},
    "graph_relations": {{
      "supersedes": [],
      "requires_also_check": [],
      "exempted_by": [],
      "conflicts_with": []
    }},
    "explainability": {{
      "violation_explanation_template": "Loan {{loan_id}} of ₹{{loan_amount}} had collateral demanded. Under RBI/2024-25/012, collateral cannot be required for loans ≤ ₹10 lakh for MSE units.",
      "remediation_template": "Remove collateral requirement for loan {{loan_id}}.",
      "compliance_explanation_template": "Loan {{loan_id}} of ₹{{loan_amount}} correctly has no collateral demanded."
    }}
  }}
]

**Chunk Text**:
{chunk_text}

**Output**: Return a JSON array of rule objects. If no rules, return []"""
    
    return prompt


def extract_rules_from_chunk(client: genai.Client, chunk: str, circular_metadata: Dict) -> List[Dict]:
    """Call Gemini to extract rules from a single text chunk."""
    prompt = build_extraction_prompt(chunk, circular_metadata)
    
    try:
        # Using the new google.genai API
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.1,
                response_mime_type="application/json",
            )
        )
        
        raw = response.text.strip()
        
        # Clean the response
        if raw.startswith("```json"):
            raw = raw[7:]
        if raw.startswith("```"):
            raw = raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]
        
        # Handle empty responses
        if not raw or raw == "":
            logger.warning("Empty response from Gemini")
            return []
        
        rules = json.loads(raw)
        if not isinstance(rules, list):
            rules = [rules]
        
        # Sanitize each rule
        validated = []
        for rule in rules:
            try:
                # Sanitize the rule to fix type issues
                sanitized = sanitize_rule(rule, circular_metadata)
                
                # Validate against schema
                validate(instance=sanitized, schema=RULE_SCHEMA)
                validated.append(sanitized)
                
            except jsonschema.ValidationError as e:
                logger.warning(f"Rule validation failed after sanitization: {e.message}")
                # Log the problematic rule for debugging
                logger.debug(f"Problematic rule: {json.dumps(rule, indent=2)}")
                continue
            except Exception as e:
                logger.warning(f"Unexpected error processing rule: {e}")
                continue
                
        return validated
        
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error: {e}")
        logger.debug(f"Raw response (first 500 chars): {raw[:500]}...")
        return []
    except Exception as e:
        logger.error(f"Error calling Gemini: {e}")
        return []


def generate_rule_id(rule_dict: Dict, existing_ids: set) -> str:
    """Generate a new rule ID based on domain and next available number."""
    domain = rule_dict.get("rule_meta", {}).get("domain", "GEN").upper()
    # Take first 3 characters of domain, ensure it's alphanumeric
    prefix = ''.join(c for c in domain[:3] if c.isalnum())
    if not prefix:
        prefix = "GEN"
    
    pattern = re.compile(rf"{prefix}(\d+)")
    max_num = 0
    for rid in existing_ids:
        m = pattern.match(rid)
        if m:
            max_num = max(max_num, int(m.group(1)))
    new_num = max_num + 1
    new_id = f"{prefix}{new_num:03d}"
    return new_id


def generate_filename(rule_id: str, rule_dict: Dict) -> str:
    """Generate a filename based on rule_id and rule name."""
    name = rule_dict.get("rule_meta", {}).get("rule_name", "rule")
    # Slugify name: lowercase, replace spaces with underscores, remove special chars
    slug = re.sub(r"[^a-z0-9_]+", "", name.lower().replace(" ", "_"))
    if not slug or len(slug) > 50:
        slug = "rule"
    return f"{rule_id}_{slug}.json"


def load_existing_rules(base_dir: Path) -> Tuple[Dict[str, Dict], set]:
    """Load all existing rules from active/ and superseded/ directories."""
    rules = {}
    all_ids = set()
    for subdir in ["active", "superseded"]:
        dir_path = base_dir / subdir
        if dir_path.exists():
            for file in dir_path.glob("*.json"):
                try:
                    with open(file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        rid = data.get("rule_id")
                        if rid:
                            rules[rid] = data
                            all_ids.add(rid)
                except Exception as e:
                    logger.warning(f"Could not load rule from {file}: {e}")
    return rules, all_ids


def compute_rule_fingerprint(rule_dict: Dict) -> str:
    """Create a fingerprint for duplicate detection based on core fields."""
    core = {
        "domain": rule_dict.get("rule_meta", {}).get("domain"),
        "rule_type": rule_dict.get("rule_meta", {}).get("rule_type"),
        "threshold_field": rule_dict.get("logic", {}).get("threshold_field"),
        "threshold_value": rule_dict.get("logic", {}).get("threshold_value"),
        "applicability_condition": rule_dict.get("logic", {}).get("applicability_condition"),
        "violation_condition": rule_dict.get("logic", {}).get("violation_condition"),
    }
    core_str = json.dumps(core, sort_keys=True)
    return hashlib.sha256(core_str.encode()).hexdigest()


def find_duplicates(new_rule: Dict, existing_rules: Dict[str, Dict]) -> Optional[str]:
    """Check if new_rule is duplicate of an existing rule based on fingerprint."""
    new_fp = compute_rule_fingerprint(new_rule)
    for rid, existing in existing_rules.items():
        if compute_rule_fingerprint(existing) == new_fp:
            return rid
    return None


def update_index(index_path: Path, rule_id: str, filename: str, status: str, domain: str):
    """Update the index.json file with the new rule."""
    if index_path.exists():
        with open(index_path, "r", encoding="utf-8") as f:
            index = json.load(f)
    else:
        index = {"total_rules": 0, "active": 0, "superseded": 0, "last_updated": "", "rules": []}
    
    # Check if rule already in index
    found = False
    for r in index["rules"]:
        if r["rule_id"] == rule_id:
            r["file"] = filename
            r["status"] = status
            found = True
            break
    
    if not found:
        index["rules"].append({
            "rule_id": rule_id,
            "file": filename,
            "domain": domain,
            "status": status
        })
    
    # Recalculate counts
    active_count = sum(1 for r in index["rules"] if r.get("status") == "ACTIVE")
    superseded_count = sum(1 for r in index["rules"] if r.get("status") == "SUPERSEDED")
    index["total_rules"] = len(index["rules"])
    index["active"] = active_count
    index["superseded"] = superseded_count
    index["last_updated"] = datetime.now().isoformat()
    
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2)


def save_rule(rule_dict: Dict, base_dir: Path, existing_rules: Dict[str, Dict], all_ids: set) -> str:
    """Save a rule to the appropriate folder."""
    # Check for duplicate
    dup_id = find_duplicates(rule_dict, existing_rules)
    if dup_id:
        logger.info(f"Rule is duplicate of {dup_id}, skipping save.")
        return dup_id
    
    # Generate rule_id if not present or placeholder
    if not rule_dict.get("rule_id") or rule_dict["rule_id"] == "R000":
        rule_dict["rule_id"] = generate_rule_id(rule_dict, all_ids)
    
    rule_id = rule_dict["rule_id"]
    filename = generate_filename(rule_id, rule_dict)
    
    # Save to active directory
    target_dir = base_dir / "active"
    target_dir.mkdir(parents=True, exist_ok=True)
    file_path = target_dir / filename
    
    # Save rule
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(rule_dict, f, indent=2, ensure_ascii=False)
    
    logger.info(f"Saved rule {rule_id} to {file_path}")
    return rule_id


def process_circular(pdf_path: str, output_dir: Path, circular_metadata: Dict = None):
    """Main processing function."""
    if circular_metadata is None:
        circular_metadata = {
            "circular_id": Path(pdf_path).stem,
            "circular_date": None
        }
    
    # Extract text from PDF
    logger.info(f"Extracting text from {pdf_path}")
    full_text = extract_text_from_pdf(pdf_path)
    if not full_text:
        logger.error("No text extracted from PDF")
        return
    
    # Chunk text
    chunks = chunk_text(full_text)
    logger.info(f"Split text into {len(chunks)} chunks")
    
    # Initialize Gemini client
    client = get_gemini_client()
    
    # Load existing rules for duplicate detection
    existing_rules, all_ids = load_existing_rules(output_dir)
    
    # Process each chunk
    all_extracted_rules = []
    for i, chunk in enumerate(chunks):
        logger.info(f"Processing chunk {i+1}/{len(chunks)}")
        rules = extract_rules_from_chunk(client, chunk, circular_metadata)
        all_extracted_rules.extend(rules)
        logger.info(f"Extracted {len(rules)} rules from chunk {i+1}")
    
    # Save each rule
    saved_count = 0
    for rule in all_extracted_rules:
        rule_id = save_rule(rule, output_dir, existing_rules, all_ids)
        if rule_id and rule_id not in [r.get("rule_id") for r in existing_rules.values()]:
            saved_count += 1
            # Update index
            index_path = output_dir / "index.json"
            domain = rule.get("rule_meta", {}).get("domain", "GENERAL")
            filename = generate_filename(rule_id, rule)
            update_index(index_path, rule_id, filename, "ACTIVE", domain)
    
    logger.info(f"Extracted {len(all_extracted_rules)} rules, saved {saved_count} new rules from circular.")


# ----------------------------------------------------------------------
# Main entry point
# ----------------------------------------------------------------------
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Extract rules from RBI circular PDF using Gemini.")
    parser.add_argument("pdf", help="Path to the PDF file")
    parser.add_argument("--output-dir", default="./rules", help="Directory to store rules (default: ./rules)")
    parser.add_argument("--circular-id", help="Circular ID (if not inferred from filename)")
    parser.add_argument("--circular-date", help="Circular date (YYYY-MM-DD)")
    args = parser.parse_args()
    
    output_dir = Path(args.output_dir)
    circular_metadata = {
        "circular_id": args.circular_id or Path(args.pdf).stem,
        "circular_date": args.circular_date or None,
    }
    
    process_circular(args.pdf, output_dir, circular_metadata)
