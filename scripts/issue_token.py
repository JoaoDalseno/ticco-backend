"""
Emite um JWT pro agrônomo informado, lendo as settings locais (.env).

Útil pra:
  - Gerar o primeiro token sem precisar do servidor rodando
  - Debugar autenticação localmente
  - Emitir token de operação manual

Uso:
  python scripts/issue_token.py <agronomo_id>
  python scripts/issue_token.py --telefone +5516999990001
  python scripts/issue_token.py --listar              # mostra agrônomos
"""
import argparse
import asyncio
import sys
import uuid
from pathlib import Path

# Permite rodar do diretório raiz: `python scripts/issue_token.py ...`
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.config import settings  # noqa: E402
from app.core.security import criar_access_token  # noqa: E402
from app.database import AsyncSessionLocal  # noqa: E402
from app.models.agronomo import Agronomo  # noqa: E402


async def _listar() -> None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Agronomo).order_by(Agronomo.created_at.desc()).limit(20)
        )
        agronomos = result.scalars().all()

    if not agronomos:
        print("Nenhum agrônomo cadastrado.")
        return

    print(f"\nÚltimos {len(agronomos)} agrônomos:\n")
    for a in agronomos:
        print(f"  {a.id}  {a.telefone_wpp:18}  {a.nome}")
    print()


async def _emitir_por_id(agronomo_id: uuid.UUID) -> None:
    async with AsyncSessionLocal() as db:
        agronomo = await db.get(Agronomo, agronomo_id)
        if agronomo is None:
            print(f"❌ Agrônomo {agronomo_id} não encontrado.", file=sys.stderr)
            sys.exit(1)
        _imprimir(agronomo)


async def _emitir_por_telefone(telefone: str) -> None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Agronomo).where(Agronomo.telefone_wpp == telefone)
        )
        agronomo = result.scalar_one_or_none()
        if agronomo is None:
            print(f"❌ Nenhum agrônomo com telefone {telefone}.", file=sys.stderr)
            sys.exit(1)
        _imprimir(agronomo)


def _imprimir(agronomo: Agronomo) -> None:
    token = criar_access_token(agronomo.id)
    print()
    print(f"Agrônomo:  {agronomo.nome}  ({agronomo.telefone_wpp})")
    print(f"ID:        {agronomo.id}")
    print(f"Validade:  {settings.jwt_expire_minutes} minutos")
    print()
    print("Token (Bearer):")
    print(token)
    print()
    print("Exemplo de uso:")
    print(f'  curl -H "Authorization: Bearer {token}" \\')
    print(f"       {settings.app_base_url}/v1/fazendas")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    grupo = parser.add_mutually_exclusive_group(required=True)
    grupo.add_argument("agronomo_id", nargs="?", help="UUID do agrônomo")
    grupo.add_argument("--telefone", help="Telefone do agrônomo em E.164 (+5516...)")
    grupo.add_argument("--listar", action="store_true", help="Lista agrônomos recentes")

    args = parser.parse_args()

    if args.listar:
        asyncio.run(_listar())
    elif args.telefone:
        asyncio.run(_emitir_por_telefone(args.telefone))
    else:
        try:
            agronomo_id = uuid.UUID(args.agronomo_id)
        except ValueError:
            print(f"❌ UUID inválido: {args.agronomo_id}", file=sys.stderr)
            sys.exit(1)
        asyncio.run(_emitir_por_id(agronomo_id))


if __name__ == "__main__":
    main()
