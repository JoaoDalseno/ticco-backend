import yaml
from pathlib import Path
from functools import lru_cache


class OntologiaLoader:

    @staticmethod
    @lru_cache(maxsize=1)
    def load() -> dict:
        """
        Carrega ontologia do café do arquivo YAML.
        Cache em memória — carrega só uma vez na startup.
        """
        path = Path(__file__).parent / "cafe.yaml"
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
