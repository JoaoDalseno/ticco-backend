#!/usr/bin/env python3
"""
Calcula o security score (0-100) baseado nos findings da auditoria.

Uso:
    python calculate_score.py findings.json

Formato esperado de findings.json:
[
    {
        "id": "TICCO-SEC-001",
        "category": "webhooks",
        "owasp": "A08",
        "severity": "critical",
        "title": "...",
        "file": "...",
        "status": "fixed"
    },
    ...
]

Saída: JSON com score, breakdown, classificação.
"""

import json
import sys
from pathlib import Path


SEVERITY_WEIGHTS = {
    "critical": 25,
    "high": 10,
    "medium": 3,
    "low": 1,
}

CLASSIFICATIONS = [
    (90, "A", "Production-ready. Postura de segurança excelente."),
    (75, "B", "Aceitável pra lançar com clientes-piloto. Hardening pendente."),
    (60, "C", "Lance APENAS com clientes muito próximos e supervisão diária."),
    (40, "D", "NÃO LANCE. Refator de segurança necessário antes."),
    (0, "F", "Risco crítico. Várias vulnerabilidades expostas."),
]


def classify(score: int) -> tuple[str, str]:
    for threshold, letter, description in CLASSIFICATIONS:
        if score >= threshold:
            return letter, description
    return "F", "Risco crítico."


def count_security_tests(test_dir: Path) -> int:
    if not test_dir.exists():
        return 0
    count = 0
    for py_file in test_dir.rglob("test_*.py"):
        content = py_file.read_text(encoding="utf-8")
        # conta funções/métodos que começam com test_
        count += content.count("def test_") + content.count("async def test_")
    # remove duplicação (async def é contado por "def test_" também)
    return count // 2


def has_ci_config() -> bool:
    return Path(".github/workflows/security.yml").exists()


def has_pre_commit() -> bool:
    return Path(".pre-commit-config.yaml").exists()


def calculate(findings_path: Path) -> dict:
    findings = json.loads(findings_path.read_text(encoding="utf-8"))
    
    # Penalidades por findings NÃO corrigidos (pending) + metade pros fixed
    pending = {sev: 0 for sev in SEVERITY_WEIGHTS}
    fixed = {sev: 0 for sev in SEVERITY_WEIGHTS}
    
    for f in findings:
        sev = f.get("severity", "low")
        status = f.get("status", "pending")
        if status == "fixed":
            fixed[sev] += 1
        else:
            pending[sev] += 1
    
    # Penalidade total — pending conta integral, fixed conta metade (ainda existiu)
    penalty = sum(
        pending[sev] * SEVERITY_WEIGHTS[sev] for sev in SEVERITY_WEIGHTS
    )
    penalty += sum(
        fixed[sev] * SEVERITY_WEIGHTS[sev] * 0.5 for sev in SEVERITY_WEIGHTS
    )
    
    # Bonus
    tests_count = count_security_tests(Path("tests/security"))
    bonus_tests = min(10, tests_count * 0.5)
    bonus_ci = 5 if has_ci_config() else 0
    bonus_precommit = 2 if has_pre_commit() else 0
    
    score = 100 - penalty + bonus_tests + bonus_ci + bonus_precommit
    score = max(0, min(100, round(score)))
    
    classification, interpretation = classify(score)
    
    return {
        "score": score,
        "classification": classification,
        "interpretation": interpretation,
        "breakdown": {
            "base": 100,
            "penalty_pending": -sum(
                pending[s] * SEVERITY_WEIGHTS[s] for s in SEVERITY_WEIGHTS
            ),
            "penalty_fixed_half": -sum(
                fixed[s] * SEVERITY_WEIGHTS[s] * 0.5 for s in SEVERITY_WEIGHTS
            ),
            "bonus_tests": bonus_tests,
            "bonus_ci": bonus_ci,
            "bonus_precommit": bonus_precommit,
        },
        "findings_summary": {
            "total": len(findings),
            "by_severity": {
                sev: {
                    "fixed": fixed[sev],
                    "pending": pending[sev],
                    "total": fixed[sev] + pending[sev],
                }
                for sev in SEVERITY_WEIGHTS
            },
        },
        "infrastructure": {
            "security_tests": tests_count,
            "ci_configured": has_ci_config(),
            "pre_commit_configured": has_pre_commit(),
        },
    }


def main():
    if len(sys.argv) < 2:
        print("Uso: calculate_score.py <findings.json>", file=sys.stderr)
        sys.exit(2)
    
    findings_file = Path(sys.argv[1])
    if not findings_file.exists():
        print(f"Arquivo não encontrado: {findings_file}", file=sys.stderr)
        sys.exit(2)
    
    result = calculate(findings_file)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
