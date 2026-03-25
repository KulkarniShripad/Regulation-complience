### Installation

### 1. Create and Setup Project
mkdir rbi-rule-system
cd rbi-rule-system

# Create virtual environment
python -m venv venv

# Activate virtual environment
# On Linux/Mac:
source venv/bin/activate
# On Windows:
venv\Scripts\activat

# Install dependencies
pip install google-genai pdfplumber jsonschema python-dotenv networkx matplotlib numpy plotly pyvis lxml

# .env
echo "GEMINI_API_KEY=your-actual-api-key-here" > .env

# 1 extract rules from pdf 
python rule_extractor.py path/to/circular.pdf --output-dir ./my_rules --circular-id "RBI/2024-25/012" --circular-date "2024-06-15"

# 2 Visualize rules on graph
python graph_creator.py --rules-dir ./my_rules --output-dir ./graph_output --format all

# 3 Query engine
python query_engine.py --rules-dir ./my_rules --graph-file ./graph_output/rule_graph.graphml
