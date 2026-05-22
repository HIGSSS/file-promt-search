/// DTO результата поиска, приходящий с backend'а.
///
/// Поля соответствуют схеме SearchResult из backend/schemas.py.
/// Любое изменение этой модели должно быть синхронизировано с backend'ом.
class SearchResult {
  // Путь на стороне backend'а. На телефоне открывается не напрямую:
  // ApiService.downloadFile скачивает копию во временную папку Android.
  final String filepath;
  final String filename;
  final String type; // image | video | pdf | docx | txt | csv | xlsx | other
  final double score; // [0..1]
  final String? textPreview;

  const SearchResult({
    required this.filepath,
    required this.filename,
    required this.type,
    required this.score,
    this.textPreview,
  });

  /// Парсинг JSON с защитой от отсутствующих/неправильных типов.
  ///
  /// Используется `num.toDouble()` потому что JSON-декодер Dart
  /// возвращает целые как int, если число без дробной части (0, 1),
  /// а контракт требует double.
  factory SearchResult.fromJson(Map<String, dynamic> json) {
    return SearchResult(
      filepath: json['filepath'] as String,
      filename: json['filename'] as String,
      type: json['type'] as String? ?? 'other',
      score: (json['score'] as num).toDouble(),
      textPreview: json['text_preview'] as String?,
    );
  }
}
