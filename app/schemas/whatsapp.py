from pydantic import BaseModel


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
