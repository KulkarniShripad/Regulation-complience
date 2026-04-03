### Installation

# Create virtual environment
python -m venv venv

# Activate virtual environment
# On Linux/Mac:
source venv/bin/activate
# On Windows:
venv\Scripts\activat

# Install dependencies
pip install pymupdf spacy tqdm colorama sentence-transformers qdrant-client pymongo

cd backend

# .env
echo "GEMINI_API_KEY=your-actual-api-key-here" > .env

# 1 Generate data from circulars (vector db and mongo db) 
python data_injestion.py

# 2 Run backend
uvicorn main:app --reload --port 8000   

# 3 Run Frontend
cd ..
cd frontend 

npm install 
npm start 
