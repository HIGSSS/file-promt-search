/// Состояние фоновой индексации на backend'е.
///
/// Соответствует схеме IndexStatus из backend/schemas.py.
enum IndexState { idle, indexing, done, error, unknown }

class IndexStatus {
  final IndexState state;
  final int processed;
  final int total;
  final String currentFile;
  final String? error;

  const IndexStatus({
    required this.state,
    required this.processed,
    required this.total,
    required this.currentFile,
    this.error,
  });

  /// Долей прогресса для LinearProgressIndicator.
  /// Возвращает null, если total ещё не известен (показать indeterminate).
  double? get progress {
    if (total <= 0) return null;
    final value = processed / total;
    // Защита от выхода за [0..1] на случай рассинхронизации state.
    return value.clamp(0.0, 1.0);
  }

  factory IndexStatus.fromJson(Map<String, dynamic> json) {
    return IndexStatus(
      state: _parseState(json['state'] as String?),
      processed: (json['processed'] as num?)?.toInt() ?? 0,
      total: (json['total'] as num?)?.toInt() ?? 0,
      currentFile: json['current_file'] as String? ?? '',
      error: json['error'] as String?,
    );
  }

  /// Парсер строкового state. Неизвестное значение маппится в `unknown` —
  /// это безопаснее, чем падать на future versions API.
  static IndexState _parseState(String? raw) {
    switch (raw) {
      case 'idle':
        return IndexState.idle;
      case 'indexing':
        return IndexState.indexing;
      case 'done':
        return IndexState.done;
      case 'error':
        return IndexState.error;
      default:
        return IndexState.unknown;
    }
  }
}
