from pydantic import BaseModel, Field


class ZAPIWebhookPayload(BaseModel):
    """
    Payload do webhook Z-API.
    Campos opcionais pois o schema varia conforme o tipo de mensagem.
    """
    instanceId: str = ""
    messageId: str | None = None
    phone: str | None = None
    fromMe: bool = False
    momment: int | None = None  # timestamp UNIX (sic — typo da Z-API)
    status: str | None = None
    chatName: str | None = None
    senderName: str | None = None
    senderPhoto: str | None = None
    broadcast: bool = False
    participantPhone: str | None = None
    type: str | None = None  # "ReceivedCallback", "MessageStatusCallback", etc.

    # Conteúdo da mensagem — apenas um estará preenchido por vez
    text: dict | None = None       # {"message": "conteudo"}
    audio: dict | None = None      # {"audioUrl": "..."}
    image: dict | None = None      # {"imageUrl": "...", "caption": "..."}
    document: dict | None = None   # {"documentUrl": "...", "fileName": "..."}

    model_config = {"extra": "allow"}  # aceita campos extras da Z-API


# ── Evolution API ─────────────────────────────────────────────────────────────

class EvolutionMessageKey(BaseModel):
    """Identificador único da mensagem na Evolution API."""
    model_config = {"extra": "allow", "populate_by_name": True}

    remote_jid: str = Field(alias="remoteJid", default="")
    from_me: bool = Field(alias="fromMe", default=False)
    id: str = ""


class EvolutionData(BaseModel):
    """Campo `data` do payload da Evolution API."""
    model_config = {"extra": "allow"}

    key: EvolutionMessageKey = Field(default_factory=EvolutionMessageKey)
    message: dict = Field(default_factory=dict)
    message_type: str = Field(alias="messageType", default="")
    message_timestamp: int | None = Field(alias="messageTimestamp", default=None)
    push_name: str = Field(alias="pushName", default="")


class EvolutionWebhookPayload(BaseModel):
    """Payload completo do webhook da Evolution API."""
    model_config = {"extra": "allow"}

    event: str = ""
    instance: str = ""
    data: EvolutionData = Field(default_factory=EvolutionData)
