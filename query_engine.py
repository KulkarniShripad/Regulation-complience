#!/usr/bin/env python3
"""
Rule Query Chatbot Backend with Hybrid Intelligence
- Uses graph to find relevant rules
- If rules found, uses them as context for Gemini
- If no rules found, sends query directly to Gemini for general RBI knowledge
"""

import os
import json
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple, Set
import argparse
from datetime import datetime
import re

import networkx as nx
from google import genai
from google.genai import types
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Configuration
MODEL_NAME = "gemini-flash-latest"
MAX_RULES_IN_CONTEXT = 10  # Maximum rules to include in prompt context

# ----------------------------------------------------------------------
# Rule Query Engine
# ----------------------------------------------------------------------

class RuleQueryEngine:
    """Main class for querying rules using graph structure with hybrid intelligence"""
    
    def __init__(self, rules_dir: Path, graph_path: Optional[Path] = None):
        """
        Initialize the query engine.
        
        Args:
            rules_dir: Directory containing the rules (with active/ subfolder)
            graph_path: Optional path to pre-built graph (if None, builds from rules)
        """
        self.rules_dir = Path(rules_dir)
        self.rules_dict = {}
        self.graph = None
        self.circular_map = {}
        
        # Load rules and build graph
        self._load_rules()
        if graph_path and graph_path.exists():
            self._load_graph(graph_path)
        else:
            self._build_graph()
        
        # Initialize Gemini client
        self.gemini_client = self._init_gemini()
        
        # Cache for frequently accessed data
        self.domain_cache = {}
        self.rule_type_cache = {}
        
        logger.info(f"RuleQueryEngine initialized with {len(self.rules_dict)} rules")
    
    def _init_gemini(self) -> genai.Client:
        """Initialize Gemini client."""
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY not found. Please set it in .env file")
        return genai.Client(api_key=api_key)
    
    def _load_rules(self):
        """Load all active rules from the rules directory."""
        active_dir = self.rules_dir / "active"
        if not active_dir.exists():
            raise ValueError(f"Active rules directory not found: {active_dir}")
        
        for rule_file in active_dir.glob("*.json"):
            try:
                with open(rule_file, "r", encoding="utf-8") as f:
                    rule = json.load(f)
                    rule_id = rule.get("rule_id")
                    if rule_id and rule.get("status") == "ACTIVE":
                        self.rules_dict[rule_id] = rule
                        
                        # Map circular to rules
                        circular_id = rule.get("source", {}).get("circular_id", "UNKNOWN")
                        if circular_id not in self.circular_map:
                            self.circular_map[circular_id] = []
                        self.circular_map[circular_id].append(rule_id)
                        
            except Exception as e:
                logger.warning(f"Error loading rule {rule_file}: {e}")
        
        logger.info(f"Loaded {len(self.rules_dict)} active rules")
    
    def _build_graph(self):
        """Build a directed graph from the rules."""
        self.graph = nx.DiGraph()
        
        # Add nodes
        for rule_id, rule in self.rules_dict.items():
            node_attrs = {
                "rule_id": rule_id,
                "rule_name": rule.get("rule_meta", {}).get("rule_name", "Unknown"),
                "domain": rule.get("rule_meta", {}).get("domain", "GENERAL"),
                "rule_type": rule.get("rule_meta", {}).get("rule_type", "MANDATE"),
                "severity": rule.get("rule_meta", {}).get("severity", "MEDIUM"),
                "circular_id": rule.get("source", {}).get("circular_id", "UNKNOWN"),
                "section": rule.get("source", {}).get("section", ""),
                "threshold_value": rule.get("logic", {}).get("threshold_value"),
                "threshold_field": rule.get("logic", {}).get("threshold_field", ""),
                "validator_type": rule.get("logic", {}).get("validator_type", "UNKNOWN")
            }
            self.graph.add_node(rule_id, **node_attrs)
        
        # Add edges
        for rule_id, rule in self.rules_dict.items():
            relations = rule.get("graph_relations", {})
            
            for sup in relations.get("supersedes", []):
                if sup in self.rules_dict:
                    self.graph.add_edge(rule_id, sup, relation="SUPERSEDES")
            
            for req in relations.get("requires_also_check", []):
                if req in self.rules_dict:
                    self.graph.add_edge(rule_id, req, relation="REQUIRES")
            
            for exc in relations.get("exempted_by", []):
                if exc in self.rules_dict:
                    self.graph.add_edge(exc, rule_id, relation="EXEMPTS")
            
            for conf in relations.get("conflicts_with", []):
                if conf in self.rules_dict:
                    self.graph.add_edge(rule_id, conf, relation="CONFLICTS")
        
        logger.info(f"Built graph with {self.graph.number_of_nodes()} nodes and {self.graph.number_of_edges()} edges")
    
    def _load_graph(self, graph_path: Path):
        """Load pre-built graph from file."""
        try:
            self.graph = nx.read_graphml(graph_path)
            logger.info(f"Loaded graph from {graph_path}")
        except Exception as e:
            logger.warning(f"Could not load graph from {graph_path}: {e}")
            self._build_graph()
    
    def save_graph(self, output_path: Path):
        """Save the graph to a file."""
        try:
            # Create a copy with None values replaced
            G_clean = nx.DiGraph()
            for node, attrs in self.graph.nodes(data=True):
                cleaned_attrs = {k: (v if v is not None else "") for k, v in attrs.items()}
                G_clean.add_node(node, **cleaned_attrs)
            
            for u, v, attrs in self.graph.edges(data=True):
                cleaned_attrs = {k: (v if v is not None else "") for k, v in attrs.items()}
                G_clean.add_edge(u, v, **cleaned_attrs)
            
            nx.write_graphml(G_clean, output_path)
            logger.info(f"Saved graph to {output_path}")
        except Exception as e:
            logger.error(f"Could not save graph: {e}")
    
    # ------------------------------------------------------------------
    # Search Functions
    # ------------------------------------------------------------------
    
    def search_by_keyword(self, keyword: str) -> List[Dict]:
        """
        Search rules by keyword in rule name, description, and original text.
        """
        keyword_lower = keyword.lower()
        results = []
        
        for rule_id, rule in self.rules_dict.items():
            # Search in rule name
            rule_name = rule.get("rule_meta", {}).get("rule_name", "").lower()
            if keyword_lower in rule_name:
                results.append(rule)
                continue
            
            # Search in original text
            original_text = rule.get("source", {}).get("clause_text_original", "").lower()
            if keyword_lower in original_text:
                results.append(rule)
                continue
            
            # Search in simplified text
            simplified_text = rule.get("source", {}).get("clause_text_simplified", "")
            if simplified_text and keyword_lower in simplified_text.lower():
                results.append(rule)
                continue
            
            # Search in applicability condition
            applicability = rule.get("logic", {}).get("applicability_condition", "").lower()
            if keyword_lower in applicability:
                results.append(rule)
                continue
            
            # Search in violation condition
            violation = rule.get("logic", {}).get("violation_condition", "").lower()
            if keyword_lower in violation:
                results.append(rule)
                continue
        
        return results
    
    def search_by_domain(self, domain: str) -> List[Dict]:
        """
        Search rules by domain.
        """
        domain_upper = domain.upper()
        results = []
        
        for rule_id, rule in self.rules_dict.items():
            rule_domain = rule.get("rule_meta", {}).get("domain", "").upper()
            if domain_upper in rule_domain:
                results.append(rule)
        
        return results
    
    def search_by_rule_type(self, rule_type: str) -> List[Dict]:
        """
        Search rules by rule type (PROHIBITION, MANDATE, etc.).
        """
        rule_type_upper = rule_type.upper()
        results = []
        
        for rule_id, rule in self.rules_dict.items():
            if rule.get("rule_meta", {}).get("rule_type", "").upper() == rule_type_upper:
                results.append(rule)
        
        return results
    
    def search_by_severity(self, severity: str) -> List[Dict]:
        """
        Search rules by severity (HIGH, MEDIUM, LOW).
        """
        severity_upper = severity.upper()
        results = []
        
        for rule_id, rule in self.rules_dict.items():
            if rule.get("rule_meta", {}).get("severity", "").upper() == severity_upper:
                results.append(rule)
        
        return results
    
    def search_by_threshold(self, field: str, value: Optional[float] = None) -> List[Dict]:
        """
        Search rules by threshold field and optional value.
        """
        results = []
        
        for rule_id, rule in self.rules_dict.items():
            logic = rule.get("logic", {})
            threshold_field = logic.get("threshold_field", "")
            
            if threshold_field and field.lower() in threshold_field.lower():
                if value is not None:
                    threshold_value = logic.get("threshold_value")
                    if threshold_value and threshold_value <= value:
                        results.append(rule)
                else:
                    results.append(rule)
        
        return results
    
    def get_related_rules(self, rule_id: str, relation_type: Optional[str] = None) -> List[Dict]:
        """
        Get rules related to a given rule.
        
        Args:
            rule_id: The rule ID to find relations for
            relation_type: Optional filter for specific relation type
                           (SUPERSEDES, REQUIRES, EXEMPTS, CONFLICTS)
        """
        if rule_id not in self.graph:
            return []
        
        related = []
        
        # Get outgoing edges
        for neighbor, data in self.graph[rule_id].items():
            if relation_type is None or data.get("relation") == relation_type:
                if neighbor in self.rules_dict:
                    related.append(self.rules_dict[neighbor])
        
        # Get incoming edges
        for neighbor, data in self.graph.pred[rule_id].items():
            if relation_type is None or data.get("relation") == relation_type:
                if neighbor in self.rules_dict:
                    related.append(self.rules_dict[neighbor])
        
        return related
    
    def get_rule_chain(self, rule_id: str) -> List[Dict]:
        """
        Get the chain of superseded versions for a rule.
        """
        chain = []
        current = rule_id
        
        # Follow supersedes chain backwards
        while current in self.graph:
            # Find predecessors that supersede current
            predecessors = [u for u, v, data in self.graph.in_edges(current, data=True)
                           if data.get("relation") == "SUPERSEDES"]
            
            if not predecessors:
                break
            
            current = predecessors[0]
            if current in self.rules_dict:
                chain.append(self.rules_dict[current])
        
        return chain
    
    # ------------------------------------------------------------------
    # Query Understanding with Gemini
    # ------------------------------------------------------------------
    
    def understand_query(self, query: str) -> Dict:
        """
        Use Gemini to understand the intent of the query and extract search parameters.
        """
        prompt = f"""
You are a query understanding system for RBI circular rules. Analyze the following query and determine if it's asking about specific rules or general RBI information.

Query: "{query}"

Determine:
1. If the query is asking about specific RBI rules, regulations, or circulars
2. If it's a general question about RBI policies, banking, or financial regulations
3. Extract any search parameters if it's a rule-specific query

Output a JSON object with the following structure:
{{
    "is_rule_query": true/false,
    "intent": "search" or "explain" or "compare" or "list" or "general",
    "search_type": "keyword" or "domain" or "rule_type" or "severity" or "threshold" or "related" or "none",
    "parameters": {{
        "keyword": "...",
        "domain": "...",
        "rule_type": "...",
        "severity": "...",
        "threshold_field": "...",
        "threshold_value": null,
        "rule_id": "..."
    }},
    "filters": {{
        "domain": "...",
        "severity": "..."
    }},
    "confidence": "high" or "medium" or "low"
}}

Examples:
- "Show me all rules about KYC" -> {{"is_rule_query": true, "intent": "list", "search_type": "domain", "parameters": {{"domain": "KYC"}}, "confidence": "high"}}
- "What does rule MSM001 say?" -> {{"is_rule_query": true, "intent": "explain", "search_type": "rule_id", "parameters": {{"rule_id": "MSM001"}}, "confidence": "high"}}
- "Rules related to collateral" -> {{"is_rule_query": true, "intent": "list", "search_type": "keyword", "parameters": {{"keyword": "collateral"}}, "confidence": "high"}}
- "What is the current repo rate?" -> {{"is_rule_query": false, "intent": "general", "search_type": "none", "parameters": {{}}, "confidence": "high"}}
- "Explain the concept of priority sector lending" -> {{"is_rule_query": false, "intent": "general", "search_type": "none", "parameters": {{}}, "confidence": "medium"}}
- "What are the penalties for non-compliance?" -> {{"is_rule_query": true, "intent": "search", "search_type": "keyword", "parameters": {{"keyword": "penalty non-compliance"}}, "confidence": "medium"}}

Return only the JSON object.
"""
        
        try:
            response = self.gemini_client.models.generate_content(
                model=MODEL_NAME,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.1,
                    response_mime_type="application/json",
                )
            )
            
            result = json.loads(response.text.strip())
            return result
        except Exception as e:
            logger.error(f"Error understanding query: {e}")
            # Default to rule query with keyword search
            return {
                "is_rule_query": True,
                "intent": "search",
                "search_type": "keyword",
                "parameters": {"keyword": query},
                "confidence": "low"
            }
    
    # ------------------------------------------------------------------
    # Search Execution
    # ------------------------------------------------------------------
    
    def execute_search(self, query_params: Dict) -> List[Dict]:
        """
        Execute search based on query parameters.
        """
        search_type = query_params.get("search_type")
        params = query_params.get("parameters", {})
        
        results = []
        
        if search_type == "keyword":
            keyword = params.get("keyword", "")
            results = self.search_by_keyword(keyword)
        
        elif search_type == "domain":
            domain = params.get("domain", "")
            results = self.search_by_domain(domain)
        
        elif search_type == "rule_type":
            rule_type = params.get("rule_type", "")
            results = self.search_by_rule_type(rule_type)
        
        elif search_type == "severity":
            severity = params.get("severity", "")
            results = self.search_by_severity(severity)
        
        elif search_type == "threshold":
            field = params.get("threshold_field", "")
            value = params.get("threshold_value")
            results = self.search_by_threshold(field, value)
        
        elif search_type == "rule_id":
            rule_id = params.get("rule_id", "")
            if rule_id in self.rules_dict:
                results = [self.rules_dict[rule_id]]
        
        elif search_type == "related":
            rule_id = params.get("rule_id", "")
            relation = params.get("relation_type")
            results = self.get_related_rules(rule_id, relation)
        
        return results
    
    # ------------------------------------------------------------------
    # Response Generation with Gemini (Hybrid Approach)
    # ------------------------------------------------------------------
    
    def generate_response_with_rules(self, query: str, query_params: Dict, rules: List[Dict]) -> str:
        """
        Generate response using rules as context.
        """
        # Limit number of rules in context
        rules_context = rules[:MAX_RULES_IN_CONTEXT]
        
        # Prepare rules context for Gemini
        rules_text = []
        for i, rule in enumerate(rules_context, 1):
            rule_text = f"""
Rule {i} (ID: {rule.get('rule_id')}):
- Name: {rule.get('rule_meta', {}).get('rule_name', 'N/A')}
- Domain: {rule.get('rule_meta', {}).get('domain', 'N/A')}
- Type: {rule.get('rule_meta', {}).get('rule_type', 'N/A')}
- Severity: {rule.get('rule_meta', {}).get('severity', 'N/A')}
- Circular: {rule.get('source', {}).get('circular_id', 'N/A')}
- Section: {rule.get('source', {}).get('section', 'N/A')}
- Original Text: {rule.get('source', {}).get('clause_text_original', 'N/A')[:300]}
- Simplified: {rule.get('source', {}).get('clause_text_simplified', 'N/A')}
- Applicability: {rule.get('logic', {}).get('applicability_condition', 'N/A')}
- Violation: {rule.get('logic', {}).get('violation_condition', 'N/A')}
- Evidence Fields: {', '.join(rule.get('logic', {}).get('evidence_fields', []))}
"""
            rules_text.append(rule_text)
        
        rules_context_str = "\n---\n".join(rules_text)
        
        prompt = f"""
You are a helpful assistant explaining RBI circular rules to bank compliance officers. You have access to specific rules from RBI circulars.

User Query: "{query}"

Found {len(rules)} rules matching the query (showing first {len(rules_context)} if more):

{rules_context_str}

Please provide a comprehensive response that:
1. Summarizes the key rules found
2. Explains each rule in simple, actionable terms
3. Highlights important details:
   - Thresholds and limits (amounts, timeframes)
   - Applicability conditions (who/what it applies to)
   - Violation conditions (what would be non-compliant)
   - Evidence requirements
4. Mentions any relationships between rules if applicable
5. Provides practical compliance recommendations
6. Lists any important exceptions or exemptions

If there are more rules than shown, mention that and suggest how to narrow down the search.

Make the response professional, clear, and actionable for compliance officers. Use bullet points for better readability when appropriate.
"""
        
        try:
            response = self.gemini_client.models.generate_content(
                model=MODEL_NAME,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.3,
                )
            )
            return response.text
        except Exception as e:
            logger.error(f"Error generating response: {e}")
            return self._generate_fallback_response(rules)
    
    def generate_general_response(self, query: str) -> str:
        """
        Generate response for general RBI-related questions without specific rules.
        Uses Gemini's general knowledge about RBI policies and banking regulations.
        """
        prompt = f"""
You are a helpful assistant specializing in RBI (Reserve Bank of India) regulations, circulars, and banking policies. 

User Query: "{query}"

The user is asking about general RBI policies or concepts. While you may not have specific circulars in the database for this query, you can provide helpful information based on your knowledge of RBI regulations.

Please provide a comprehensive response that:
1. Addresses the query with accurate information about RBI policies and regulations
2. Explains key concepts clearly
3. Mentions relevant RBI circulars or guidelines if you know them
4. If the query is about a specific rule that might exist, suggest what keywords the user could use to find it
5. Indicate that for specific rule details, they can ask about particular circulars or use more specific terms

Make the response informative, professional, and helpful. If you're uncertain about specific details, acknowledge that and suggest where the user might find authoritative information.
"""
        
        try:
            response = self.gemini_client.models.generate_content(
                model=MODEL_NAME,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.4,
                )
            )
            return response.text
        except Exception as e:
            logger.error(f"Error generating general response: {e}")
            return f"I'm having trouble processing your request. Please try rephrasing your question or ask about specific RBI circulars and rules."
    
    def _generate_fallback_response(self, rules: List[Dict]) -> str:
        """
        Generate a simple fallback response if Gemini is unavailable.
        """
        response = f"Found {len(rules)} rules matching your query:\n\n"
        
        for i, rule in enumerate(rules[:5], 1):
            response += f"{i}. {rule.get('rule_id')} - {rule.get('rule_meta', {}).get('rule_name', 'Unknown')}\n"
            response += f"   Type: {rule.get('rule_meta', {}).get('rule_type', 'N/A')}\n"
            response += f"   Severity: {rule.get('rule_meta', {}).get('severity', 'N/A')}\n"
            response += f"   {rule.get('source', {}).get('clause_text_simplified', rule.get('source', {}).get('clause_text_original', 'No description'))[:150]}\n\n"
        
        if len(rules) > 5:
            response += f"\n... and {len(rules) - 5} more rules.\n"
        
        return response
    
    # ------------------------------------------------------------------
    # Main Query Interface (Hybrid)
    # ------------------------------------------------------------------
    
    def query(self, query: str) -> Dict[str, Any]:
        """
        Main interface for querying rules with hybrid approach.
        
        Steps:
        1. Understand if query is about rules or general information
        2. If rule query, search for matching rules
        3. If rules found, generate response with rules as context
        4. If no rules found but it's a rule query, suggest alternatives
        5. If general query, send directly to Gemini
        """
        # Step 1: Understand the query
        query_params = self.understand_query(query)
        logger.info(f"Query understanding: {query_params}")
        
        is_rule_query = query_params.get("is_rule_query", True)
        confidence = query_params.get("confidence", "medium")
        
        # Step 2: Handle based on query type
        if is_rule_query:
            # Search for rules
            results = self.execute_search(query_params)
            logger.info(f"Found {len(results)} matching rules")
            
            if results:
                # Rules found - use rules as context
                response = self.generate_response_with_rules(query, query_params, results)
                response_type = "rule_based"
            else:
                # No rules found but it was a rule query
                if confidence == "high":
                    # High confidence but no results - suggest alternatives
                    response = f"I couldn't find any specific rules matching '{query}'. "
                    response += "Try using different keywords or ask about specific RBI circulars. "
                    response += "You can also ask general questions about RBI policies."
                else:
                    # Low confidence - treat as general question
                    response = self.generate_general_response(query)
                    response_type = "general_fallback"
                
                results = []
                response_type = "no_rules_found"
        else:
            # General query - send directly to Gemini
            response = self.generate_general_response(query)
            results = []
            response_type = "general"
        
        return {
            "response": response,
            "rules": results[:MAX_RULES_IN_CONTEXT] if results else [],
            "total_found": len(results),
            "query_params": query_params,
            "response_type": response_type
        }
    
    def get_rule_details(self, rule_id: str) -> Optional[Dict]:
        """
        Get detailed information about a specific rule.
        """
        if rule_id in self.rules_dict:
            rule = self.rules_dict[rule_id]
            
            # Add related rules information
            related = {
                "requires": self.get_related_rules(rule_id, "REQUIRES"),
                "exempts": self.get_related_rules(rule_id, "EXEMPTS"),
                "supersedes": self.get_related_rules(rule_id, "SUPERSEDES"),
                "conflicts": self.get_related_rules(rule_id, "CONFLICTS")
            }
            
            return {
                "rule": rule,
                "related": related,
                "chain": self.get_rule_chain(rule_id)
            }
        
        return None
    
    def get_statistics(self) -> Dict:
        """
        Get statistics about the rule set.
        """
        stats = {
            "total_rules": len(self.rules_dict),
            "domains": {},
            "rule_types": {},
            "severities": {},
            "circulars": len(self.circular_map),
            "relations": self.graph.number_of_edges()
        }
        
        for rule in self.rules_dict.values():
            domain = rule.get("rule_meta", {}).get("domain", "GENERAL")
            stats["domains"][domain] = stats["domains"].get(domain, 0) + 1
            
            rule_type = rule.get("rule_meta", {}).get("rule_type", "MANDATE")
            stats["rule_types"][rule_type] = stats["rule_types"].get(rule_type, 0) + 1
            
            severity = rule.get("rule_meta", {}).get("severity", "MEDIUM")
            stats["severities"][severity] = stats["severities"].get(severity, 0) + 1
        
        return stats


# ----------------------------------------------------------------------
# Interactive CLI Interface
# ----------------------------------------------------------------------

def interactive_mode(engine: RuleQueryEngine):
    """
    Run an interactive command-line interface.
    """
    print("\n" + "="*70)
    print("RBI RULES QUERY CHATBOT - HYBRID INTELLIGENCE")
    print("="*70)
    print("\nFeatures:")
    print("  ✓ Rule-specific queries → Uses RBI circular rules as context")
    print("  ✓ General RBI questions → Answered directly by AI")
    print("  ✓ Smart fallback when no rules match")
    print("\nCommands:")
    print("  - Type your query in natural language")
    print("  - Type 'stats' to see rule statistics")
    print("  - Type 'list domains' to see all domains")
    print("  - Type 'list types' to see all rule types")
    print("  - Type 'help' for this message")
    print("  - Type 'exit' or 'quit' to exit")
    print("\nExample queries:")
    print("  • Show me all KYC rules")
    print("  • What does rule MSM001 say?")
    print("  • Rules about collateral for MSME loans")
    print("  • What is the current repo rate? (general)")
    print("  • Explain priority sector lending (general)")
    print("\n" + "="*70 + "\n")
    
    while True:
        try:
            user_input = input("\n🔍 You: ").strip()
            
            if not user_input:
                continue
            
            if user_input.lower() in ['exit', 'quit', 'q']:
                print("\nGoodbye!")
                break
            
            elif user_input.lower() == 'help':
                print("\n" + "="*70)
                print("HELP - How to use the chatbot")
                print("="*70)
                print("\n📌 Rule-Specific Queries (uses RBI circulars):")
                print("  • Ask about specific rules: 'Show KYC rules', 'What is rule MSM001?'")
                print("  • Search by keyword: 'Collateral requirements', 'Loan limits'")
                print("  • Filter by domain: 'AML rules', 'Capital adequacy norms'")
                print("  • Filter by severity: 'High severity rules', 'Critical compliance rules'")
                print("\n📌 General RBI Questions (direct AI answers):")
                print("  • Ask about concepts: 'What is priority sector lending?'")
                print("  • Ask about current rates: 'What is the repo rate?'")
                print("  • Ask about policies: 'Explain Basel III norms'")
                print("\n📌 Commands:")
                print("  • stats - Show rule statistics")
                print("  • list domains - Show all available domains")
                print("  • list types - Show all rule types")
                print("  • help - Show this help")
                print("  • exit - Quit the chatbot")
                print("="*70 + "\n")
                continue
            
            elif user_input.lower() == 'stats':
                stats = engine.get_statistics()
                print("\n📊 RULE STATISTICS")
                print("-" * 50)
                print(f"Total Rules: {stats['total_rules']}")
                print(f"Total Relations: {stats['relations']}")
                print(f"Circulars: {stats['circulars']}")
                print("\n📁 Domains:")
                for domain, count in sorted(stats['domains'].items(), key=lambda x: x[1], reverse=True):
                    print(f"  • {domain}: {count}")
                print("\n🏷️ Rule Types:")
                for rtype, count in sorted(stats['rule_types'].items(), key=lambda x: x[1], reverse=True):
                    print(f"  • {rtype}: {count}")
                print("\n⚠️ Severities:")
                for severity, count in sorted(stats['severities'].items(), key=lambda x: x[1], reverse=True):
                    print(f"  • {severity}: {count}")
                continue
            
            elif user_input.lower() == 'list domains':
                stats = engine.get_statistics()
                print("\n📁 Available Domains:")
                for domain in sorted(stats['domains'].keys()):
                    print(f"  • {domain}")
                continue
            
            elif user_input.lower() == 'list types':
                stats = engine.get_statistics()
                print("\n🏷️ Available Rule Types:")
                for rtype in sorted(stats['rule_types'].keys()):
                    print(f"  • {rtype}")
                continue
            
            # Process query
            print("\n🤔 Processing your query...")
            result = engine.query(user_input)
            
            print("\n" + "="*70)
            print("RESPONSE:")
            print("="*70)
            print(result['response'])
            
            # Show response type indicator
            response_type = result.get('response_type', 'unknown')
            if response_type == 'rule_based':
                print("\n" + "🔵 " + "-"*67)
                print(f"📌 Based on {result['total_found']} matching rule(s) from RBI circulars")
                print("💡 This response uses actual RBI circular rules as context")
            elif response_type == 'general':
                print("\n" + "🟢 " + "-"*67)
                print("📌 General RBI Information (based on AI knowledge)")
                print("💡 For specific rules, try: 'Show me rules about [topic]'")
            elif response_type == 'no_rules_found':
                print("\n" + "🟡 " + "-"*67)
                print("⚠️ No specific rules found. Try different keywords or ask a general question.")
            
            if result['total_found'] > 0:
                print("\n📋 Related Rules:")
                for i, rule in enumerate(result['rules'][:5], 1):
                    rule_id = rule.get('rule_id', 'Unknown')
                    rule_name = rule.get('rule_meta', {}).get('rule_name', '')
                    severity = rule.get('rule_meta', {}).get('severity', 'MEDIUM')
                    severity_icon = "🔴" if severity == "HIGH" else "🟡" if severity == "MEDIUM" else "🟢"
                    print(f"  {i}. {severity_icon} {rule_id} - {rule_name}")
                
                if result['total_found'] > 5:
                    print(f"  ... and {result['total_found'] - 5} more")
            
            print("\n" + "="*70)
            
        except KeyboardInterrupt:
            print("\n\nGoodbye!")
            break
        except Exception as e:
            logger.error(f"Error processing query: {e}")
            print(f"\n❌ Error: {e}")
            print("Please try rephrasing your question or ask a different query.")


# ----------------------------------------------------------------------
# API Mode (for integration with web apps)
# ----------------------------------------------------------------------

def api_mode(engine: RuleQueryEngine, query: str, format: str = "json"):
    """
    API mode for programmatic access.
    """
    result = engine.query(query)
    
    if format == "json":
        # Return JSON response
        output = {
            "query": query,
            "response": result['response'],
            "response_type": result['response_type'],
            "total_found": result['total_found'],
            "rules": [
                {
                    "id": r.get('rule_id'),
                    "name": r.get('rule_meta', {}).get('rule_name'),
                    "type": r.get('rule_meta', {}).get('rule_type'),
                    "severity": r.get('rule_meta', {}).get('severity'),
                    "domain": r.get('rule_meta', {}).get('domain'),
                    "simplified_text": r.get('source', {}).get('clause_text_simplified'),
                    "original_text": r.get('source', {}).get('clause_text_original')[:200]
                }
                for r in result['rules']
            ]
        }
        print(json.dumps(output, indent=2))
    else:
        # Return plain text
        print(result['response'])
    
    return result


# ----------------------------------------------------------------------
# Main Entry Point
# ----------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="RBI Rules Query Chatbot with Hybrid Intelligence")
    parser.add_argument("--rules-dir", default="./my_rules",
                       help="Directory containing rules (default: ./my_rules)")
    parser.add_argument("--graph-file", default=None,
                       help="Path to pre-built graph file (optional)")
    parser.add_argument("--query", default=None,
                       help="Single query to process (if not provided, runs interactive mode)")
    parser.add_argument("--format", choices=["json", "text"], default="text",
                       help="Output format for API mode (default: text)")
    
    args = parser.parse_args()
    
    # Initialize engine
    rules_dir = Path(args.rules_dir)
    graph_file = Path(args.graph_file) if args.graph_file else None
    
    try:
        engine = RuleQueryEngine(rules_dir, graph_file)
        
        if args.query:
            # API mode
            api_mode(engine, args.query, args.format)
        else:
            # Interactive mode
            interactive_mode(engine)
            
    except Exception as e:
        logger.error(f"Failed to initialize: {e}")
        print(f"Error: {e}")
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())
