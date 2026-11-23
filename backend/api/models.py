import uuid

from django.db import models
from pgvector.django import VectorField


class User(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=150)
    email = models.EmailField(max_length=255, unique=True)
    password_hash = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def is_authenticated(self):
        return True

    class Meta:
        db_table = "users"

    def __str__(self):
        return f"{self.name} <{self.email}>"


class Document(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="documents",
        db_column="user_id",
    )
    filename = models.CharField(max_length=255)
    s3_key = models.CharField(max_length=512, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "documents"
        ordering = ["-created_at"]

    def __str__(self):
        return self.filename


class DocumentChunk(models.Model):
    id = models.BigAutoField(primary_key=True)
    document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        related_name="chunks",
        db_column="document_id",
    )
    content = models.TextField()
    embedding = VectorField(dimensions=768)

    class Meta:
        db_table = "document_chunks"


class Query(models.Model):
    id = models.BigAutoField(primary_key=True)
    document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        related_name="queries",
        db_column="document_id",
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="queries",
        db_column="user_id",
    )
    question = models.TextField()
    answer = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "queries"
        ordering = ["created_at"]