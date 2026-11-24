import uuid

from django.db import connection, transaction
from django.db.models import Count
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .authentication import create_jwt_token, hash_password, verify_password
from .models import Document, DocumentChunk, Query, User
from .rag import (
    EmbeddingRateLimitError,
    chunk_text,
    extract_text_from_pdf,
    generate_embeddings,
    generate_grounded_answer,
    generate_query_embedding,
    search_similar_chunks,
)
from .serializers import (
    DocumentSerializer,
    LoginSerializer,
    QueryCreateSerializer,
    QuerySerializer,
    UserRegisterSerializer,
    UserSerializer,
)
from .storage import build_s3_key, delete_pdf, save_pdf

MAX_PDF_SIZE_BYTES = 20 * 1024 * 1024  # 20 MB


def _get_owned_document(document_id: str, user: User):
    try:
        parsed_id = uuid.UUID(str(document_id))
    except ValueError:
        return None, Response(
            {"detail": "Documento não encontrado."},
            status=status.HTTP_404_NOT_FOUND,
        )

    document = (
        Document.objects.annotate(chunks_count=Count("chunks"))
        .filter(id=parsed_id)
        .first()
    )
    if document is None:
        return None, Response(
            {"detail": "Documento não encontrado."},
            status=status.HTTP_404_NOT_FOUND,
        )

    if document.user_id != user.id:
        return None, Response(
            {"detail": "Você não tem permissão para acessar este documento."},
            status=status.HTTP_403_FORBIDDEN,
        )

    return document, None


class HealthCheckView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT extname FROM pg_extension WHERE extname = 'vector';"
            )
            pgvector_enabled = cursor.fetchone() is not None

        return Response(
            {
                "status": "ok",
                "database": "connected",
                "pgvector": pgvector_enabled,
            }
        )


class UserRegisterView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = UserRegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data
        if User.objects.filter(email=data["email"]).exists():
            return Response(
                {"detail": "Já existe um usuário cadastrado com este e-mail."},
                status=status.HTTP_409_CONFLICT,
            )

        user = User.objects.create(
            name=data["name"],
            email=data["email"],
            password_hash=hash_password(data["password"]),
        )
        return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)


class LoginView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data
        user = User.objects.filter(email=data["email"]).first()
        if user is None or not verify_password(data["password"], user.password_hash):
            return Response(
                {"detail": "E-mail ou senha inválidos."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        token = create_jwt_token(user)
        return Response(
            {
                "access_token": token,
                "token_type": "Bearer",
                "user": UserSerializer(user).data,
            },
            status=status.HTTP_200_OK,
        )


class DocumentListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        documents = Document.objects.filter(user=request.user).annotate(
            chunks_count=Count("chunks")
        )
        return Response(
            DocumentSerializer(documents, many=True).data,
            status=status.HTTP_200_OK,
        )

    def post(self, request):
        uploaded_file = request.FILES.get("file")
        if uploaded_file is None:
            return Response(
                {"detail": "Envie um arquivo PDF no campo 'file'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if uploaded_file.size > MAX_PDF_SIZE_BYTES:
            return Response(
                {"detail": "O arquivo excede o limite máximo de 20 MB."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not uploaded_file.name.lower().endswith(".pdf"):
            return Response(
                {"detail": "Apenas arquivos com extensão .pdf são aceitos."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        file_bytes = uploaded_file.read()
        if not file_bytes.startswith(b"%PDF-"):
            return Response(
                {"detail": "O arquivo enviado não é um PDF válido."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            extracted_text = extract_text_from_pdf(file_bytes)
        except Exception as exc:
            return Response(
                {"detail": f"Não foi possível ler o PDF: {exc}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        chunks = chunk_text(extracted_text, chunk_size=1000, overlap=150)
        if not chunks:
            return Response(
                {"detail": "O PDF não possui texto selecionável para indexação."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            embeddings = generate_embeddings(chunks, task_type="RETRIEVAL_DOCUMENT")
        except EmbeddingRateLimitError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        except Exception as exc:
            return Response(
                {"detail": f"Erro ao gerar embeddings na API Gemini: {exc}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        document_id = uuid.uuid4()
        s3_key = build_s3_key(request.user.id, document_id, uploaded_file.name)

        try:
            save_pdf(s3_key, file_bytes)
        except Exception as exc:
            return Response(
                {"detail": f"Erro ao armazenar o PDF: {exc}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        try:
            with transaction.atomic():
                document = Document.objects.create(
                    id=document_id,
                    user=request.user,
                    filename=uploaded_file.name,
                    s3_key=s3_key,
                )
                chunk_objects = [
                    DocumentChunk(
                        document=document,
                        content=content,
                        embedding=embedding,
                    )
                    for content, embedding in zip(chunks, embeddings)
                ]
                DocumentChunk.objects.bulk_create(chunk_objects)
        except Exception as exc:
            delete_pdf(s3_key)
            return Response(
                {"detail": f"Erro ao salvar documento no banco de dados: {exc}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        document.chunks_count = len(chunk_objects)
        return Response(
            DocumentSerializer(document).data,
            status=status.HTTP_201_CREATED,
        )


class DocumentDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, document_id):
        document, error_response = _get_owned_document(document_id, request.user)
        if error_response:
            return error_response
        return Response(DocumentSerializer(document).data, status=status.HTTP_200_OK)

    def delete(self, request, document_id):
        document, error_response = _get_owned_document(document_id, request.user)
        if error_response:
            return error_response

        try:
            delete_pdf(document.s3_key)
        except Exception as exc:
            return Response(
                {"detail": f"Erro ao remover o arquivo PDF do armazenamento: {exc}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        document.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class DocumentQueryListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, document_id):
        document, error_response = _get_owned_document(document_id, request.user)
        if error_response:
            return error_response

        queries = Query.objects.filter(document=document, user=request.user)
        return Response(
            QuerySerializer(queries, many=True).data,
            status=status.HTTP_200_OK,
        )

    def post(self, request, document_id):
        document, error_response = _get_owned_document(document_id, request.user)
        if error_response:
            return error_response

        serializer = QueryCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        question = serializer.validated_data["question"]

        try:
            query_embedding = generate_query_embedding(question)
        except EmbeddingRateLimitError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        except Exception as exc:
            return Response(
                {"detail": f"Erro ao gerar embedding da pergunta: {exc}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        top_chunks = search_similar_chunks(
            document_id=document.id,
            user_id=request.user.id,
            query_embedding=query_embedding,
            top_k=3,
        )

        try:
            answer = generate_grounded_answer(question, top_chunks)
        except Exception as exc:
            return Response(
                {"detail": f"Erro ao gerar resposta na API Gemini: {exc}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        query_record = Query.objects.create(
            document=document,
            user=request.user,
            question=question,
            answer=answer,
        )

        sources = [
            {
                "chunk_id": chunk.id,
                "similarity": round(max(0.0, 1.0 - float(chunk.distance)), 4),
                "content": chunk.content,
            }
            for chunk in top_chunks
        ]

        response_data = QuerySerializer(query_record).data
        response_data["sources"] = sources
        return Response(response_data, status=status.HTTP_200_OK)