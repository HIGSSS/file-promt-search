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


def semantic_search(server: str, query: str, file_type: str = "all", top_k: int = 5) -> list[str]:
    """Отправляет запрос на backend и возвращает список filename'ов."""
    # Маппинг типов из queries.json → типы API
    api_file_type = {
        "image": "media",
        "video": "media",
        "media": "media",
        "pdf": "documents",
        "docx": "documents",
        "documents": "documents",
        "txt": "other",
        "csv": "other",
        "xlsx": "other",
        "other": "other",
        "all": "all",
    }.get(file_type, "all")
    resp = requests.post(
        f"{server}/search",
        json={"query": query, "file_type": api_file_type, "top_k": top_k},
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
        file_type = q.get("file_type", "all")
        retrieved_semantic = semantic_search(server, q["query"], file_type=file_type, top_k=k)
        retrieved_substring = substring_search(dataset_dir, q["query"], top_k=k)
        p_semantic = precision_at_k(retrieved_semantic, q["relevant"], k)
        p_substring = precision_at_k(retrieved_substring, q["relevant"], k)
        per_query.append({
            "id": q["id"],
            "query": q["query"],
            "kind": q["kind"],
            "file_type": file_type,
            "relevant": q["relevant"],
            "semantic_top": retrieved_semantic,
            "substring_top": retrieved_substring,
            "p_semantic": p_semantic,
            "p_substring": p_substring,
        })

    # Агрегаты по всей выборке и по типу запроса.
    def mean(xs: list[float]) -> float:
        return sum(xs) / len(xs) if xs else 0.0

    n_total = len(per_query)
    all_sem = [r["p_semantic"] for r in per_query]
    all_sub = [r["p_substring"] for r in per_query]
    exact = [r for r in per_query if r["kind"] == "exact"]
    semantic = [r for r in per_query if r["kind"] == "semantic"]

    # Группировка по file_type
    ft_groups: dict[str, list[dict]] = {}
    for r in per_query:
        ft = r["file_type"]
        ft_groups.setdefault(ft, []).append(r)

    ft_summary = {
        ft: {
            "n": len(items),
            "semantic": mean([r["p_semantic"] for r in items]),
            "substring": mean([r["p_substring"] for r in items]),
        }
        for ft, items in ft_groups.items()
    }

    return {
        "k": k,
        "n_total": n_total,
        "per_query": per_query,
        "summary": {
            "all": {"n": n_total, "semantic": mean(all_sem), "substring": mean(all_sub)},
            "exact_queries": {"n": len(exact), "semantic": mean([r["p_semantic"] for r in exact]), "substring": mean([r["p_substring"] for r in exact])},
            "semantic_queries": {"n": len(semantic), "semantic": mean([r["p_semantic"] for r in semantic]), "substring": mean([r["p_substring"] for r in semantic])},
            "by_file_type": ft_summary,
        },
    }


def print_report(report: dict[str, Any]) -> None:
    k = report["k"]
    n = report.get("n_total", len(report["per_query"]))
    print()
    print("=" * 74)
    print(f" РЕЗУЛЬТАТЫ ЭКСПЕРИМЕНТА: Precision@{k}  (запросов: {n})")
    print("=" * 74)

    summary = report["summary"]
    rows = [
        (f"Все запросы (N={summary['all']['n']})", summary["all"]),
        (f"  точные (N={summary['exact_queries']['n']})", summary["exact_queries"]),
        (f"  семантические (N={summary['semantic_queries']['n']})", summary["semantic_queries"]),
    ]
    print(f"\n{'Набор':<38} {'Семантика':>12} {'Подстрока':>12}")
    print("-" * 65)
    for label, values in rows:
        print(f"{label:<38} {values['semantic']*100:>10.1f}% {values['substring']*100:>10.1f}%")

    # По типам файлов
    ft_label = {
        "image": "Изображения",
        "video": "Видео",
        "media": "Медиа",
        "pdf": "PDF",
        "docx": "DOCX",
        "documents": "Документы",
        "txt": "TXT",
        "csv": "CSV",
        "xlsx": "XLSX",
        "other": "Прочее",
        "all": "Все типы",
    }
    by_ft = summary.get("by_file_type", {})
    if by_ft:
        print()
        print(f"{'По типу файла':<38} {'Семантика':>12} {'Подстрока':>12}")
        print("-" * 65)
        for ft, vals in sorted(by_ft.items()):
            label = f"  {ft_label.get(ft, ft)} (N={vals['n']})"
            print(f"{label:<38} {vals['semantic']*100:>10.1f}% {vals['substring']*100:>10.1f}%")

    print("\n" + "-" * 74)
    print(" По каждому запросу:")
    print("-" * 74)
    print(f"{'ID':<4}{'Тип файла':<12}{'Вид':<10}{'Запрос':<28}{'Сем.':>8}{'Подстр.':>10}")
    print("-" * 74)
    for r in report["per_query"]:
        ft = ft_label.get(r.get("file_type", "all"), r.get("file_type", ""))
        query_short = r["query"][:26]
        hit_sem = "✓" if r["p_semantic"] > 0 else " "
        hit_sub = "✓" if r["p_substring"] > 0 else " "
        print(
            f"{r['id']:<4}{ft:<12}{r['kind']:<10}{query_short:<28}"
            f"{r['p_semantic']*100:>5.0f}%{hit_sem} {r['p_substring']*100:>5.0f}%{hit_sub}"
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
