from rest_framework import serializers

from .models import Document, Query, User


class UserRegisterSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=150)
    email = serializers.EmailField(max_length=255)
    password = serializers.CharField(write_only=True, min_length=6, max_length=72)

    def validate_name(self, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise serializers.ValidationError("O nome não pode ficar vazio.")
        return cleaned

    def validate_email(self, value: str) -> str:
        return value.strip().lower()


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "name", "email", "created_at"]


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField(max_length=255)
    password = serializers.CharField(write_only=True)

    def validate_email(self, value: str) -> str:
        return value.strip().lower()


class DocumentSerializer(serializers.ModelSerializer):
    chunks_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Document
        fields = ["id", "filename", "s3_key", "chunks_count", "created_at"]


class QueryCreateSerializer(serializers.Serializer):
    question = serializers.CharField(min_length=2, max_length=2000)

    def validate_question(self, value: str) -> str:
        cleaned = value.strip()
        if len(cleaned) < 2:
            raise serializers.ValidationError("A pergunta é muito curta.")
        return cleaned


class QuerySerializer(serializers.ModelSerializer):
    document_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = Query
        fields = ["id", "document_id", "question", "answer", "created_at"]
