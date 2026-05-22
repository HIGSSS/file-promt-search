"""Эксперимент Precision@K: семантический поиск vs подстрочный поиск по имени.

Использование:
    # 1. Сгенерировать датасет и проиндексировать его на backend'е:
    python generate_dataset.py --out ./test_dataset
    # запустить backend и вызвать /index с путём к ./test_dataset
    # дождаться state=='done' через /status

    # 2. Запустить эксперимент:
    python run_experiment.py --server http://localhost:8000

Запросы и ground truth берутся из queries.json. Скрипт вычисляет
Precision@5 для обоих методов и печатает сводную таблицу + по каждому
запросу отдельно.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import requests


def load_queries(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["queries"]


def semantic_search(server: str, query: str, top_k: int = 5) -> list[str]:
    """Отправляет запрос на backend и возвращает список filename'ов."""
    resp = requests.post(
        f"{server}/search",
        json={"query": query, "file_type": "all", "top_k": top_k},
        timeout=60,
    )
    resp.raise_for_status()
    return [r["filename"] for r in resp.json()["results"]]


def substring_search(
    dataset_dir: Path, query: str, top_k: int = 5
) -> list[str]:
    """Baseline: ищем подстроку query в имени файла (case-insensitive).

    Простая альтернатива, которую пользователь получил бы «из коробки» —
    например, стандартный поиск файлового менеджера.
    """
    needle = query.lower()
    matches: list[str] = []
    for name in sorted(os.listdir(dataset_dir)):
        if name.startswith("_"):
            continue  # пропускаем манифест
        if needle in name.lower():
            matches.append(name)
            if len(matches) >= top_k:
                break
    return matches


def precision_at_k(retrieved: list[str], relevant: list[str], k: int = 5) -> float:
    """Precision@K = (релевантных в топ-K) / K.

    Используется стандартное определение: знаменатель ВСЕГДА K,
    а не len(retrieved). Если результатов меньше K, «недобор» штрафует
    метрику — это корректно отражает факт, что пользователь не получил
    K хороших результатов.
    """
    if k <= 0:
        raise ValueError("k должен быть > 0")
    top = retrieved[:k]
    relevant_set = set(relevant)
    hits = sum(1 for item in top if item in relevant_set)
    return hits / k


def run_experiment(
    server: str,
    dataset_dir: Path,
    queries_file: Path,
    k: int = 5,
) -> dict[str, Any]:
    """Гоняет все запросы обоими методами, возвращает per-query + агрегаты."""
    queries = load_queries(queries_file)
    per_query: list[dict[str, Any]] = []
    for q in queries:
        retrieved_semantic = semantic_search(server, q["query"], top_k=k)
        retrieved_substring = substring_search(dataset_dir, q["query"], top_k=k)
        p_semantic = precision_at_k(retrieved_semantic, q["relevant"], k)
        p_substring = precision_at_k(retrieved_substring, q["relevant"], k)
        per_query.append({
            "id": q["id"],
            "query": q["query"],
            "kind": q["kind"],
            "relevant": q["relevant"],
            "semantic_top": retrieved_semantic,
            "substring_top": retrieved_substring,
            "p_semantic": p_semantic,
            "p_substring": p_substring,
        })

    # Агрегаты по всей выборке и по типу запроса.
    def mean(xs: list[float]) -> float:
        return sum(xs) / len(xs) if xs else 0.0

    all_sem = [r["p_semantic"] for r in per_query]
    all_sub = [r["p_substring"] for r in per_query]
    exact_sem = [r["p_semantic"] for r in per_query if r["kind"] == "exact"]
    exact_sub = [r["p_substring"] for r in per_query if r["kind"] == "exact"]
    sem_sem = [r["p_semantic"] for r in per_query if r["kind"] == "semantic"]
    sem_sub = [r["p_substring"] for r in per_query if r["kind"] == "semantic"]

    return {
        "k": k,
        "per_query": per_query,
        "summary": {
            "all": {"semantic": mean(all_sem), "substring": mean(all_sub)},
            "exact_queries": {"semantic": mean(exact_sem), "substring": mean(exact_sub)},
            "semantic_queries": {"semantic": mean(sem_sem), "substring": mean(sem_sub)},
        },
    }


def print_report(report: dict[str, Any]) -> None:
    k = report["k"]
    print()
    print("=" * 70)
    print(f" РЕЗУЛЬТАТЫ ЭКСПЕРИМЕНТА: Precision@{k}")
    print("=" * 70)

    summary = report["summary"]
    rows = [
        ("Все запросы (N=20)", summary["all"]),
        ("  из них точные (N=10)", summary["exact_queries"]),
        ("  из них семантические (N=10)", summary["semantic_queries"]),
    ]
    # Заголовок таблицы агрегатов.
    print(f"\n{'Набор':<32} {'Семантика':>12} {'Подстрока':>12}")
    print("-" * 60)
    for label, values in rows:
        print(
            f"{label:<32} "
            f"{values['semantic']*100:>10.1f}% "
            f"{values['substring']*100:>10.1f}%"
        )

    print("\n" + "-" * 70)
    print(" По каждому запросу:")
    print("-" * 70)
    print(f"{'ID':<4}{'Тип':<12}{'Запрос':<30}{'Сем.':>8}{'Подстр.':>10}")
    print("-" * 70)
    for r in report["per_query"]:
        query_short = r["query"][:28]
        print(
            f"{r['id']:<4}{r['kind']:<12}{query_short:<30}"
            f"{r['p_semantic']*100:>6.0f}%  {r['p_substring']*100:>6.0f}%"
        )
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Эксперимент Precision@K")
    parser.add_argument("--server", default="http://localhost:8000",
                        help="URL backend'а")
    parser.add_argument("--dataset", type=Path,
                        default=Path(__file__).parent / "test_dataset",
                        help="Директория с тестовыми файлами")
    parser.add_argument("--queries", type=Path,
                        default=Path(__file__).parent / "queries.json",
                        help="Файл с запросами и ground truth")
    parser.add_argument("--k", type=int, default=5, help="K для Precision@K")
    parser.add_argument("--out", type=Path, default=None,
                        help="Сохранить отчёт как JSON")
    args = parser.parse_args()

    if not args.dataset.is_dir():
        raise SystemExit(
            f"Датасет не найден: {args.dataset}. "
            f"Запустите: python generate_dataset.py --out {args.dataset}"
        )

    # Дружелюбная проверка подключения: /status быстрый и даёт понятное
    # сообщение пользователю, если сервер не запущен.
    try:
        requests.get(f"{args.server}/status", timeout=5).raise_for_status()
    except requests.RequestException as e:
        raise SystemExit(f"Не удалось подключиться к серверу {args.server}: {e}")

    report = run_experiment(args.server, args.dataset, args.queries, k=args.k)
    print_report(report)

    if args.out is not None:
        args.out.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"Отчёт сохранён в {args.out}")


if __name__ == "__main__":
    main()
