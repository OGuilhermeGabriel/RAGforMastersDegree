import io
import math
import re
import time

from django.conf import settings
from google import genai
from google.genai import types
from pgvector.django import CosineDistance
from pypdf import PdfReader

from .models import DocumentChunk

SYSTEM_INSTRUCTION = (
    "Você é um assistente acadêmico especialista em consulta de documentos PDF. "
    "Responda à pergunta do usuário utilizando EXCLUSIVAMENTE as informações "
    "presentes nos trechos recuperados do documento fornecidos abaixo. "
    "Não invente dados, não use conhecimento externo e não faça suposições. "
    "Se a informação solicitada não estiver nos trechos fornecidos, diga claramente "
    "que não encontrou essa informação nos trechos recuperados do documento. "
    "Responda em português de forma clara, objetiva e, quando houver indicação de "
    "página nos trechos, cite a página correspondente."
)


class EmbeddingRateLimitError(Exception):
    """Erro disparado quando a cota por minuto de embeddings da API Gemini é excedida."""


def _get_genai_client() -> genai.Client:
    if not settings.GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY não está configurada no ambiente.")
    return genai.Client(
        api_key=settings.GEMINI_API_KEY,
        http_options={"timeout": 25000},
    )


def _is_rate_limit_error(error_text: str) -> bool:
    return any(
        token in error_text
        for token in ("429", "RESOURCE_EXHAUSTED", "Quota exceeded")
    )


def _extract_retry_delay_seconds(error_text: str, default: float = 15.0) -> float:
    match = re.search(r"retry in\s+([0-9]+(?:\.[0-9]+)?)s", error_text, re.IGNORECASE)
    if not match:
        match = re.search(r"retryDelay['\"]?\s*:\s*['\"]?([0-9]+)s", error_text)
    if match:
        return math.ceil(float(match.group(1))) + 1.0
    return default


def extract_text_from_pdf(file_bytes: bytes) -> str:
    reader = PdfReader(io.BytesIO(file_bytes))
    if reader.is_encrypted:
        raise ValueError("PDF protegido por senha não é suportado.")

    pages_text = []
    for page_number, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        if text:
            pages_text.append(f"[Página {page_number}] {text}")

    return "\n\n".join(pages_text)


def chunk_text(text: str, chunk_size: int = 1000, overlap: int = 150) -> list[str]:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if not cleaned:
        return []

    if len(cleaned) <= chunk_size:
        return [cleaned]

    chunks = []
    start = 0
    text_len = len(cleaned)

    while start < text_len:
        end = min(start + chunk_size, text_len)

        if end < text_len:
            last_space = cleaned.rfind(" ", start + int(chunk_size * 0.7), end)
            if last_space > start:
                end = last_space

        chunk = cleaned[start:end].strip()
        if chunk:
            chunks.append(chunk)

        if end >= text_len:
            break

        next_start = end - overlap
        if next_start <= start:
            next_start = end
        start = next_start

    return chunks


def generate_embeddings(
    texts: list[str],
    task_type: str = "RETRIEVAL_DOCUMENT",
    batch_size: int = 25,
    max_total_wait_seconds: float = 65.0,
) -> list[list[float]]:
    client = _get_genai_client()
    all_embeddings: list[list[float]] = []
    total_waited = 0.0
    total_chunks = len(texts)

    for i in range(0, total_chunks, batch_size):
        batch = texts[i : i + batch_size]

        while True:
            try:
                response = client.models.embed_content(
                    model=settings.GEMINI_EMBEDDING_MODEL,
                    contents=batch,
                    config=types.EmbedContentConfig(
                        task_type=task_type,
                        output_dimensionality=768,
                    ),
                )
                all_embeddings.extend(list(item.values) for item in response.embeddings)
                break
            except Exception as exc:
                error_text = str(exc)
                if not _is_rate_limit_error(error_text):
                    raise

                remaining_chunks = total_chunks - i
                retry_delay = _extract_retry_delay_seconds(error_text)

                if (
                    remaining_chunks > 100
                    or (total_waited + retry_delay) > max_total_wait_seconds
                ):
                    if task_type == "RETRIEVAL_QUERY":
                        raise EmbeddingRateLimitError(
                            "Limite da cota gratuita da API Gemini atingido no momento "
                            "(30.000 tokens/min para embeddings). Aguarde alguns segundos "
                            "e tente enviar a pergunta novamente."
                        ) from exc

                    estimated_tokens = sum(len(chunk) for chunk in texts) // 3
                    tokens_br = f"{estimated_tokens:,}".replace(",", ".")
                    raise EmbeddingRateLimitError(
                        "Limite da cota gratuita da API Gemini excedido "
                        "(30.000 tokens/min para embeddings). "
                        f"Este documento possui {total_chunks} trechos "
                        f"(~{tokens_br} tokens estimados), excedendo o limite "
                        "por minuto do plano gratuito para indexação síncrona. "
                        "Aguarde 1 minuto ou envie um PDF menor (ou apenas as páginas desejadas)."
                    ) from exc

                time.sleep(retry_delay)
                total_waited += retry_delay

    return all_embeddings


def generate_query_embedding(question: str) -> list[float]:
    return generate_embeddings([question], task_type="RETRIEVAL_QUERY")[0]


def search_similar_chunks(
    document_id,
    user_id,
    query_embedding: list[float],
    top_k: int = 3,
) -> list[DocumentChunk]:
    return list(
        DocumentChunk.objects.filter(
            document_id=document_id,
            document__user_id=user_id,
        )
        .annotate(distance=CosineDistance("embedding", query_embedding))
        .order_by("distance")[:top_k]
    )


FALLBACK_GENERATION_MODELS = [
    "gemini-flash-lite-latest",
    "gemini-3.1-flash-lite",
    "gemini-3.8-flash",
]


def generate_grounded_answer(question: str, chunks: list[DocumentChunk]) -> str:
    if not chunks:
        return "Não foram encontrados trechos indexados neste documento para responder à pergunta."

    context_blocks = [
        f"--- Trecho {index} ---\n{chunk.content}"
        for index, chunk in enumerate(chunks, start=1)
    ]
    context = "\n\n".join(context_blocks)

    prompt = (
        f"Trechos recuperados do documento:\n\n{context}\n\n"
        f"Pergunta do usuário:\n{question}"
    )

    client = _get_genai_client()
    models_to_try = [settings.GEMINI_GENERATION_MODEL] + [
        m for m in FALLBACK_GENERATION_MODELS if m != settings.GEMINI_GENERATION_MODEL
    ]

    last_error = None
    for model_name in models_to_try:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION,
                    temperature=0.2,
                ),
            )
            return (response.text or "").strip()
        except Exception as exc:
            last_error = exc
            error_text = str(exc)
            if any(
                code in error_text
                for code in ("503", "504", "429", "UNAVAILABLE", "DEADLINE_EXCEEDED", "404")
            ):
                continue
            raise

    raise last_error
