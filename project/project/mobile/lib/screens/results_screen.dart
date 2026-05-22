import 'package:flutter/material.dart';

import '../models/search_result.dart';
import '../widgets/file_card.dart';

/// Экран результатов поиска: список FileCard или сообщение о пустом результате.
class ResultsScreen extends StatelessWidget {
  final List<SearchResult> results;
  final String query;

  const ResultsScreen({
    super.key,
    required this.results,
    required this.query,
  });

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text('Результаты: $query', overflow: TextOverflow.ellipsis),
        // Показываем количество справа: пользователь сразу видит, сколько нашлось.
        actions: [
          Center(
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16),
              child: Text(
                '${results.length}',
                style: const TextStyle(fontSize: 16),
              ),
            ),
          ),
        ],
      ),
      body: results.isEmpty
          ? const Center(
              child: Text(
                'Ничего не найдено',
                style: TextStyle(fontSize: 16, color: Colors.grey),
              ),
            )
          : ListView.builder(
              // padding сверху/снизу, чтобы первая/последняя карточка
              // не прилипали к краям экрана.
              padding: const EdgeInsets.symmetric(vertical: 8),
              itemCount: results.length,
              itemBuilder: (_, i) => FileCard(result: results[i]),
            ),
    );
  }
}
