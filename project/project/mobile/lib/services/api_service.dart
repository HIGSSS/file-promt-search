import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:file_picker/file_picker.dart';
import 'package:http/http.dart' as http;
import 'package:path_provider/path_provider.dart';

import '../models/index_status.dart';
import '../models/search_result.dart';
import 'settings_service.dart';

/// Типизированная ошибка API: UI отличает «сервер недоступен» от
/// «индекс не построен», чтобы показать понятное сообщение пользователю.
class ApiException implements Exception {
  final String message;
  final int? statusCode;

  const ApiException(this.message, {this.statusCode});

  @override
  String toString() => message;
}

/// Клиент REST API backend'а.
///
/// URL сервера читается из SharedPreferences при каждом запросе —
/// это позволяет менять URL в настройках без пересоздания сервиса.
/// Оверхед SharedPreferences минимальный (in-memory кеш после первого чтения).
class ApiService {
  // Таймауты из §5.7 ТЗ. /search долгий из-за inference моделей,
  // /status лёгкий и должен быстро падать, если сервер не отвечает.
  static const _searchTimeout = Duration(seconds: 30);
  static const _statusTimeout = Duration(seconds: 5);
  static const _indexTimeout = Duration(seconds: 10);
  static const _uploadTimeout = Duration(minutes: 10);
  static const _downloadTimeout = Duration(minutes: 2);
  static const _uploadBatchSize = 20;

  static Future<Uri> _uri(String path) async {
    final base = await SettingsService.getServerUrl();
    return Uri.parse('$base$path');
  }

  /// Единая точка обработки сетевых ошибок.
  /// SocketException = нет сети / неверный хост / сервер не запущен.
  /// TimeoutException = сервер висит.
  static Future<T> _withErrorHandling<T>(Future<T> Function() op) async {
    try {
      return await op();
    } on SocketException {
      throw const ApiException('Сервер недоступен. Проверьте подключение.');
    } on TimeoutException {
      throw const ApiException('Таймаут запроса. Сервер не отвечает.');
    } on FormatException {
      throw const ApiException('Некорректный ответ сервера (не JSON).');
    } on HttpException catch (e) {
      throw ApiException('HTTP ошибка: ${e.message}');
    }
  }

  /// POST /index — запуск индексации.
  ///
  /// Возвращает сразу; дальнейший прогресс отслеживается через /status.
  /// Статус 'busy' = индексация уже идёт (валидный ответ, не ошибка).
  static Future<void> startIndexing(String path) async {
    await _withErrorHandling(() async {
      final uri = await _uri('/index');
      final response = await http
          .post(
            uri,
            headers: {'Content-Type': 'application/json'},
            body: jsonEncode({'path': path}),
          )
          .timeout(_indexTimeout);

      if (response.statusCode != 200) {
        final detail =
            _extractDetail(response.body) ?? 'Ошибка ${response.statusCode}';
        throw ApiException(detail, statusCode: response.statusCode);
      }
      // Сохраняем путь для быстрой переиндексации в Settings.
      await SettingsService.setLastIndexedPath(path);
    });
  }

  /// POST /upload-index — загрузка выбранных на телефоне файлов и запуск
  /// индексации backend-копий. Это запасной ручной сценарий для Android.
  static Future<void> uploadAndIndex(List<PlatformFile> files) async {
    if (files.isEmpty) {
      throw const ApiException('Файлы не выбраны.');
    }

    await _withErrorHandling(() async {
      final uri = await _uri('/upload-index');
      final request = http.MultipartRequest('POST', uri);

      for (final file in files) {
        final stream = file.readStream;
        if (stream != null) {
          request.files.add(
            http.MultipartFile(
              'files',
              stream,
              file.size,
              filename: file.name,
            ),
          );
        } else if (file.path != null) {
          request.files.add(
            await http.MultipartFile.fromPath(
              'files',
              file.path!,
              filename: file.name,
            ),
          );
        } else if (file.bytes != null) {
          request.files.add(
            http.MultipartFile.fromBytes(
              'files',
              file.bytes!,
              filename: file.name,
            ),
          );
        }
      }

      if (request.files.isEmpty) {
        throw const ApiException('Не удалось прочитать выбранные файлы.');
      }

      final streamed = await request.send().timeout(_uploadTimeout);
      final response = await http.Response.fromStream(streamed);

      if (response.statusCode != 200) {
        final detail =
            _extractDetail(response.body) ?? 'Ошибка ${response.statusCode}';
        throw ApiException(detail, statusCode: response.statusCode);
      }

      await SettingsService.setLastIndexedPath(
        'Загружено файлов: ${request.files.length}',
      );
    });
  }

  /// Загружает файлы батчами и запускает индексацию на сервере.
  ///
  /// [precomputedTotalBytes] — суммарный размер файлов, посчитанный заранее
  /// в UI-изоляте. Если передан, пре-скан не делается: это важно в фоновом
  /// изоляте, где тысячи последовательных file.exists()/file.length()
  /// занимают много минут и дают ложный «0 байт» на прогресс-баре.
  static Future<void> uploadPathsAndIndexBatched(
    List<File> files, {
    int precomputedTotalBytes = 0,
    void Function(int sentBytes, int totalBytes, String currentFile)?
        onProgress,
  }) async {
    if (files.isEmpty) {
      throw const ApiException('Файлы не выбраны.');
    }

    await _withErrorHandling(() async {
      // Используем precomputedTotalBytes если он передан, иначе считаем сами.
      // lengthSync() допустим здесь: метод вызывается из фонового изолята.
      final totalBytes = precomputedTotalBytes > 0
          ? precomputedTotalBytes
          : files.fold<int>(0, (s, f) {
              try { return s + f.lengthSync(); } catch (_) { return s; }
            });

      var sentBytes = 0;
      for (var start = 0; start < files.length; start += _uploadBatchSize) {
        final batch = files.skip(start).take(_uploadBatchSize).toList();
        final batchTotalBytes =
            batch.fold<int>(0, (s, f) {
              try { return s + f.lengthSync(); } catch (_) { return s; }
            });
        final uri = (await _uri('/upload-index')).replace(queryParameters: {
          'append': (start != 0).toString(),
          'index_after': 'false',
        });

        // До 3 попыток на батч. При обрыве соединения (фон, плохой Wi-Fi)
        // пересоздаём запрос со свежими потоками и пробуем снова.
        const maxAttempts = 3;
        for (var attempt = 1; ; attempt++) {
          var batchSentBytes = 0;
          try {
            await _sendBatch(
              uri: uri,
              batchFiles: batch,
              onChunk: (delta, path) {
                batchSentBytes += delta;
                onProgress?.call(sentBytes + batchSentBytes, totalBytes, path);
              },
            );
            sentBytes += batchTotalBytes;
            break;
          } on SocketException {
            if (attempt >= maxAttempts) rethrow;
            await Future.delayed(Duration(seconds: 2 * attempt));
          } on TimeoutException {
            if (attempt >= maxAttempts) rethrow;
            await Future.delayed(Duration(seconds: 2 * attempt));
          }
        }
      }

      await reindexUploaded();
      await SettingsService.setLastIndexedPath(
        'Автоматически найдено файлов: ${files.length}',
      );
    });
  }

  /// Отправляет один батч файлов. Создаёт запрос с нуля, поэтому
  /// метод можно вызывать повторно при обрыве соединения.
  static Future<void> _sendBatch({
    required Uri uri,
    required List<File> batchFiles,
    required void Function(int delta, String path) onChunk,
  }) async {
    final request = http.MultipartRequest('POST', uri);
    for (final file in batchFiles) {
      final length = await file.length();
      final stream = file.openRead().transform(
        StreamTransformer<List<int>, List<int>>.fromHandlers(
          handleData: (data, sink) {
            onChunk(data.length, file.path);
            sink.add(data);
          },
        ),
      );
      request.files.add(
        http.MultipartFile(
          'files',
          http.ByteStream(stream),
          length,
          filename: file.uri.pathSegments.last,
        ),
      );
    }
    final streamed = await request.send().timeout(_uploadTimeout);
    final response = await http.Response.fromStream(streamed);
    if (response.statusCode != 200) {
      final detail =
          _extractDetail(response.body) ?? 'Ошибка загрузки ${response.statusCode}';
      throw ApiException(detail, statusCode: response.statusCode);
    }
  }

  static Future<void> reindexUploaded() async {
    await _withErrorHandling(() async {
      final uri = await _uri('/index-uploads');
      final response = await http.post(uri).timeout(_indexTimeout);

      if (response.statusCode != 200) {
        final detail =
            _extractDetail(response.body) ?? 'Ошибка ${response.statusCode}';
        throw ApiException(detail, statusCode: response.statusCode);
      }
    });
  }

  /// GET /status — текущее состояние индексации.
  static Future<IndexStatus> getStatus() async {
    return _withErrorHandling(() async {
      final uri = await _uri('/status');
      final response = await http.get(uri).timeout(_statusTimeout);

      if (response.statusCode != 200) {
        throw ApiException(
          'Не удалось получить статус',
          statusCode: response.statusCode,
        );
      }
      final json =
          jsonDecode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>;
      return IndexStatus.fromJson(json);
    });
  }

  /// POST /search — семантический поиск.
  ///
  /// Возвращает все результаты с score >= minScore (обычно 0.5).
  /// Если таких меньше topK — дополняет лучшими результатами ниже порога.
  /// Бросает ApiException(statusCode=400), если индекс не построен.
  static Future<List<SearchResult>> search(
    String query,
    String fileType, {
    int topK = 20,
    double minScore = 0.5,
  }) async {
    return _withErrorHandling(() async {
      final uri = await _uri('/search');
      final response = await http
          .post(
            uri,
            headers: {'Content-Type': 'application/json'},
            body: jsonEncode({
              'query': query,
              'file_type': fileType,
              'top_k': topK,
              'min_score': minScore,
            }),
          )
          .timeout(_searchTimeout);

      if (response.statusCode != 200) {
        final detail =
            _extractDetail(response.body) ?? 'Ошибка ${response.statusCode}';
        throw ApiException(detail, statusCode: response.statusCode);
      }

      // utf8.decode на bodyBytes, а не на body: body пытается декодировать
      // как latin-1 при отсутствии явного charset в Content-Type, что ломает кириллицу.
      final json =
          jsonDecode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>;
      final rawResults = json['results'] as List<dynamic>;
      return rawResults
          .map((e) => SearchResult.fromJson(e as Map<String, dynamic>))
          .toList();
    });
  }

  /// GET /download — скачивает backend-копию результата во временную папку,
  /// чтобы Android мог открыть её локальным приложением.
  /// Повторные запросы для уже скачанного файла возвращают путь из кеша.
  static Future<String> downloadFile(SearchResult result) async {
    return _withErrorHandling(() async {
      final dir = await getTemporaryDirectory();
      final cacheDir = Directory('${dir.path}/intelligent_file_search');
      if (!await cacheDir.exists()) {
        await cacheDir.create(recursive: true);
      }

      final filename = _safeLocalFilename(result.filename);
      final file = File('${cacheDir.path}/$filename');

      // Возвращаем кешированный файл, если он уже был скачан ранее.
      if (await file.exists() && await file.length() > 0) {
        return file.path;
      }

      final uri = await _uri('/download').then(
        (u) => u.replace(queryParameters: {'path': result.filepath}),
      );
      final response = await http.get(uri).timeout(_downloadTimeout);

      if (response.statusCode != 200) {
        final detail =
            _extractDetail(response.body) ?? 'Ошибка ${response.statusCode}';
        throw ApiException(detail, statusCode: response.statusCode);
      }

      await file.writeAsBytes(response.bodyBytes, flush: true);
      return file.path;
    });
  }

  /// Пытается вытащить поле 'detail' из тела FastAPI-ошибки.
  /// FastAPI отдаёт 4xx/5xx как {"detail": "..."} по умолчанию.
  static String? _extractDetail(String body) {
    try {
      final parsed = jsonDecode(body);
      if (parsed is Map<String, dynamic> && parsed['detail'] is String) {
        return parsed['detail'] as String;
      }
    } catch (_) {
      // Тело не JSON — возвращаем null, вызывающий код подставит дефолт.
    }
    return null;
  }

  static String _safeLocalFilename(String raw) {
    final cleaned = raw.replaceAll(RegExp(r'[\\/:*?"<>|]'), '_').trim();
    return cleaned.isEmpty ? 'downloaded_file' : cleaned;
  }
}
