"""Central config, loaded from .env. Import this everywhere instead of
reading os.environ directly, so there's one place that knows the defaults."""
import os
from dotenv import load_dotenv

load_dotenv()

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:3b")

# ALL LLM-reasoning now runs on Claude via the Anthropic API: document
# drafting, conversational Q&A, summarization, and ingest-time document
# classification. Ollama/llama3.2 has been removed entirely (the OLLAMA_*
# settings above are retained only so an existing .env doesn't break; no
# code reads them any more). This reverses this project's original
# "fully local, no external API calls" architecture — an explicit user
# decision. What stays local and self-hosted: embeddings
# (multilingual-e5-large), vector search (Qdrant), and voice transcription
# (faster-whisper). See Memory.md for the RFP-compliance tradeoff this
# accepts — query and draft content now leaves the machine. Never hardcode
# the key: it comes from the environment (.env is gitignored) or from
# whatever secret manager actually deploys this.
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-opus-5")

TESSERACT_CMD = os.getenv("TESSERACT_CMD", r"C:\Program Files\Tesseract-OCR\tesseract.exe")

QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "qci_knowledge_hub")
# "local"  -> embedded, file-based Qdrant, no server/Docker needed (dev default,
#             used until the Docker restart is done)
# "server" -> talk to a real Qdrant container at QDRANT_HOST:QDRANT_PORT
QDRANT_MODE = os.getenv("QDRANT_MODE", "local")
QDRANT_LOCAL_PATH = os.getenv("QDRANT_LOCAL_PATH", "./qdrant_storage")

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "intfloat/multilingual-e5-large")

# Chunking
CHUNK_SIZE_CHARS = int(os.getenv("CHUNK_SIZE_CHARS", "1000"))
CHUNK_OVERLAP_CHARS = int(os.getenv("CHUNK_OVERLAP_CHARS", "150"))

# OCR fallback: if a PDF page yields fewer than this many characters of native
# text, treat it as scanned/image-based and re-extract via Tesseract instead.
OCR_FALLBACK_CHAR_THRESHOLD = int(os.getenv("OCR_FALLBACK_CHAR_THRESHOLD", "40"))

# RAG / guardrails
RETRIEVAL_TOP_K = int(os.getenv("RETRIEVAL_TOP_K", "5"))
# Below this top-1 cosine score, skip the LLM entirely and return the mandated
# "no information found" message. IMPORTANT: multilingual-e5 cosine scores are
# NOT a calibrated 0-1 relevance scale — on our 5-doc sample corpus, clearly
# relevant queries scored 0.80-0.87 and clearly irrelevant ones still scored
# 0.74-0.77 (see scripts/calibrate_threshold.py). 0.78 is fit to that narrow
# gap on a tiny corpus and WILL need re-calibration as the real corpus grows —
# treat this as a weak first-pass filter, not the primary defense (that's the
# LLM self-report check in guardrails/fallback.py + citation validation).
RETRIEVAL_SCORE_THRESHOLD = float(os.getenv("RETRIEVAL_SCORE_THRESHOLD", "0.78"))
NO_INFO_MESSAGE = "I could not find relevant information in the knowledge base to answer this question."
AUDIT_LOG_PATH = os.getenv("AUDIT_LOG_PATH", "./data/processed/audit_log.jsonl")

# Deliverables table, "Ingestion: Max file size per upload" — RFP spec is 200MB.
MAX_FILE_SIZE_BYTES = int(os.getenv("MAX_FILE_SIZE_BYTES", str(200 * 1024 * 1024)))

# Voice input (RFP: "Input modes: Text + voice, voice transcribed before
# processing"). RFP asks for English/Hindi/Hinglish, but Hindi/Hinglish was
# tried and dropped after real recordings transcribed as nonsense regardless
# of model tier, language hint, or domain prompt (see Memory.md) — English
# only, now genuinely validated at 97% accuracy rather than assumed. CPU +
# int8 by default — the GPU's already carrying Ollama on this machine's 4GB
# VRAM.
WHISPER_MODEL_SIZE = os.getenv("WHISPER_MODEL_SIZE", "small")
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cpu")
WHISPER_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "int8")
