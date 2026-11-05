from pydantic import BaseModel, Field


class TicketClassification(BaseModel):

    ticket_id: str = Field(
        description="Identificador original del ticket."
    )

    category_key: str = Field(
        description=(
            "Categoría técnica estable en inglés y snake_case."
        )
    )

    specific_title: str = Field(
        description=(
            "Título específico de la incidencia en español."
        )
    )

    system: str = Field(
        description=(
            "Sistema, aplicación o componente afectado."
        )
    )

    symptom: str = Field(
        description=(
            "Síntoma concreto descrito en el ticket."
        )
    )

    likely_cause: str = Field(
        description=(
            "Posible causa. Vacío cuando no existe evidencia suficiente."
        )
    )

    confidence: float = Field(
        ge=0,
        le=1,
        description="Confianza de la clasificación entre 0 y 1."
    )

    requires_review: bool = Field(
        description=(
            "True cuando el ticket es ambiguo o contiene "
            "información insuficiente."
        )
    )


class BatchClassification(BaseModel):

    results: list[TicketClassification]