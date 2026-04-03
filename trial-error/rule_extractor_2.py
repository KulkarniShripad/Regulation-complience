import os
import uuid
from pathlib import Path
from tqdm import tqdm

import pdfplumber
from sentence_transformers import SentenceTransformer
from qdrant_client import QdrantClient
from qdrant_client.models import VectorParams, Distance, PointStruct

# =========================
# CONFIG
# =========================
PDF_FOLDER = "./circulars"  # folder containing PDFs
COLLECTION_NAME = "pdf_embeddings"
CHUNK_SIZE = 500     # characters
CHUNK_OVERLAP = 50

# =========================
# INIT MODELS & DB
# =========================
print("Loading embedding model...")
model = SentenceTransformer("all-MiniLM-L6-v2")

print("Connecting to Qdrant...")
qdrant = QdrantClient(path="./qdrant_data")  # local storage

# Create collection if not exists
if COLLECTION_NAME not in [c.name for c in qdrant.get_collections().collections]:
    qdrant.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=VectorParams(
            size=model.get_sentence_embedding_dimension(),
            distance=Distance.COSINE,
        ),
    )

# =========================
# FUNCTIONS
# =========================

def extract_text_from_pdf(pdf_path):
    text = ""
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text += page.extract_text() or ""
            text += "\n"
    return text


def chunk_text(text, chunk_size=500, overlap=50):
    chunks = []
    start = 0

    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        chunks.append(chunk)
        start += chunk_size - overlap

    return chunks


def process_pdf(file_path):
    text = extract_text_from_pdf(file_path)
    chunks = chunk_text(text)

    embeddings = model.encode(chunks, show_progress_bar=False)

    points = []
    for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
        point = PointStruct(
            id=str(uuid.uuid4()),
            vector=embedding.tolist(),
            payload={
                "text": chunk,
                "source": file_path.name,
                "chunk_id": i,
            },
        )
        points.append(point)

    return points


# =========================
# MAIN PIPELINE
# =========================

def main():
    pdf_files = [ 
        p for p in Path(PDF_FOLDER).rglob("*") 
        if p.suffix.lower() == ".pdf"
    ]

    print(f"Found {len(pdf_files)} PDFs")

    for pdf_file in tqdm(pdf_files, desc="Processing PDFs"):
        points = process_pdf(pdf_file)

        # Upload to Qdrant
        qdrant.upsert(
            collection_name=COLLECTION_NAME,
            points=points
        )

    print("✅ All PDFs processed and stored in Qdrant!")


if __name__ == "__main__":
    main()
