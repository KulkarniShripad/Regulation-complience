import os
import json
import uuid
from typing import List, Optional
from pathlib import Path
from pydantic import BaseModel, Field

# PDF & AI Imports
from pypdf import PdfReader
from google import genai
from google.genai import types
from sentence_transformers import SentenceTransformer, util

# --- 1. CONFIGURATION & SCHEMA ---
API_KEY = "AIzaSyCgwmhmn8XyzlRGOnXy01Xu8nXydMHDJwM"
RULES_FOLDER = "rbi_rules_db"
SIMILARITY_THRESHOLD = 0.85  # 0.85+ usually indicates a near-duplicate or modification

client = genai.Client(api_key=API_KEY)
# Initialize embedding model once for duplicate checking
embed_model = SentenceTransformer('all-MiniLM-L6-v2')

class RuleSchema(BaseModel):
    rule_name: str = Field(description="Short descriptive name of the rule")
    domain: str = Field(description="e.g., KYC, MSME Lending, AML")
    clause_text: str = Field(description="The original text from the circular")
    logic_condition: str = Field(description="The logical condition to check for compliance")
    violation_condition: str = Field(description="What specific data points indicate a violation")
    severity: str = Field(enum=["Low", "Medium", "High"])

class RuleExtractionResponse(BaseModel):
    circular_id: str
    date: str
    rules: List[RuleSchema]

# --- 2. CORE FUNCTIONS ---

def extract_text_from_pdf(pdf_path: str) -> str:
    reader = PdfReader(pdf_path)
    return "\n".join([page.extract_text() for page in reader.pages])

def get_existing_rules() -> List[dict]:
    """Loads all JSON files from the rules folder."""
    rules = []
    path = Path(RULES_FOLDER)
    if not path.exists():
        path.mkdir(parents=True)
        return []
    for file in path.glob("*.json"):
        with open(file, 'r') as f:
            rules.append(json.load(f))
    return rules

def check_duplicates_and_similar(new_rule: RuleSchema, existing_rules: List[dict]):
    """
    Uses semantic similarity to check if the new rule already exists 
    or modifies an existing one.
    """
    if not existing_rules:
        return None, 0.0

    new_text = new_rule.clause_text
    existing_texts = [r['clause_text'] for r in existing_rules]
    
    # Compute embeddings
    new_emb = embed_model.encode(new_text, convert_to_tensor=True)
    exist_embs = embed_model.encode(existing_texts, convert_to_tensor=True)
    
    # Compute cosine similarity
    cosine_scores = util.cos_sim(new_emb, exist_embs)[0]
    max_score, idx = cosine_scores.max().item(), cosine_scores.argmax().item()
    
    if max_score > SIMILARITY_THRESHOLD:
        return existing_rules[idx], max_score
    return None, max_score

def process_circular(pdf_path: str):
    print(f"--- Processing: {pdf_path} ---")
    raw_text = extract_text_from_pdf(pdf_path)
    
    # Gemini API Call with Structured Output
    prompt = """
    Extract all distinct compliance rules from this RBI circular. 
    Focus on actionable rules that a bank must follow.
    Ignore introductory greetings or history.
    """
    
    response = client.models.generate_content(
        model="gemini-flash-latest",
        contents=[prompt, raw_text],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=RuleExtractionResponse
        )
    )
    
    extracted_data = response.parsed
    existing_rules = get_existing_rules()
    
    for rule in extracted_data.rules:
        match, score = check_duplicates_and_similar(rule, existing_rules)
        
        # Create a safe filename based on context
        clean_name = rule.rule_name.lower().replace(" ", "_")[:30]
        filename = f"{extracted_data.circular_id.replace('/', '_')}_{clean_name}_{uuid.uuid4().hex[:4]}.json"
        save_path = os.path.join(RULES_FOLDER, filename)
        
        rule_dict = rule.dict()
        rule_dict["circular_metadata"] = {
            "id": extracted_data.circular_id,
            "date": extracted_data.date
        }

        if match:
            print(f"(!) Potential Duplicate/Update found for '{rule.rule_name}' (Similarity: {score:.2f})")
            rule_dict["relates_to_existing_id"] = match.get("rule_id", "unknown")
            # You could choose to archive the old one or save as a 'v2'
        
        with open(save_path, 'w') as f:
            json.dump(rule_dict, f, indent=4)
            print(f"Saved: {filename}")

# --- 3. EXECUTION ---
if __name__ == "__main__":
    # Example usage:
    print("System ready. Call process_circular(file_path) to begin.")
    process_circular("rbi.PDF")
