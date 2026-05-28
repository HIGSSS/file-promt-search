import 'dart:async';
import 'dart:io';

import 'package:flutter/material.dart';

import '../services/device_file_scanner.dart';
import '../services/upload_background_service.dart';
import 'indexing_screen.dart';

enum _Stage { scanning, confirming, uploading, error }

class ScanUploadScreen extends StatefulWidget {
  final String rootPath;

  const ScanUploadScreen({
    super.key,
    required this.rootPath,
  });

  @override
  State<ScanUploadScreen> createState() => _ScanUploadScreenState();
}

class _ScanUploadScreenState extends State<ScanUploadScreen> {
  _Stage _stage = _Stage.scanning;
  int _scannedDirs = 0;
  int _foundFiles = 0;
  int _sentBytes = 0;
  int _totalBytes = 0;
  String _currentPath = '';
  String? _error;

  StreamSubscription<Map<String, dynamic>?>? _progressSub;
  StreamSubscription<Map<String, dynamic>?>? _doneSub;
  // Таймер для обнаружения зависшего сервиса (0 байт за 60 с).
  Timer? _stallTimer;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _run());
  }

  @override
  void dispose() {
    _progressSub?.cancel();
    _doneSub?.cancel();
    _stallTimer?.cancel();
    super.dispose();
  }

  Future<void> _run() async {
    try {
      final files = await DeviceFileScanner.scanSupportedFiles(
        rootPath: widget.rootPath,
        onProgress: (dirs, found, path) {
          if (!mounted) return;
          setState(() {
            _stage = _Stage.scanning;
            _scannedDirs = dirs;
            _foundFiles = found;
            _currentPath = path;
          });
        },
      );

      if (!mounted) return;
      if (files.isEmpty) {
        setState(() {
          _stage = _Stage.error;
          _error = 'Поддерживаемые файлы не найдены.';
        });
        return;
      }

      // Считаем суммарный размер один раз — передаём в диалог и на прогресс-бар.
      final totalBytes = files.fold<int>(0, (s, f) => s + f.lengthSync());

      setState(() => _stage = _Stage.confirming);
      final confirmed = await _confirmUpload(files, totalBytes);
      if (!mounted) return;
      if (confirmed != true) {
        Navigator.pop(context);
        return;
      }

      // Подписываемся на события ДО старта сервиса, чтобы не пропустить
      // первый прогресс-ивент, который может прийти очень быстро.
      _progressSub = uploadProgressStream.listen((data) {
        if (!mounted || data == null) return;
        _stallTimer?.cancel(); // первый байт — сервис работает
        setState(() {
          _sentBytes = (data['sentBytes'] as num).toInt();
          _totalBytes = (data['totalBytes'] as num).toInt();
          _currentPath = data['currentFile'] as String? ?? '';
        });
      });

      _doneSub = uploadDoneStream.listen((data) {
        if (!mounted || data == null) return;
        _progressSub?.cancel();
        _doneSub?.cancel();
        if (data['success'] == true) {
          Navigator.pushReplacement(
            context,
            MaterialPageRoute(builder: (_) => const IndexingScreen()),
          );
        } else {
          setState(() {
            _stage = _Stage.error;
            _error = data['error'] as String? ?? 'Неизвестная ошибка';
          });
        }
      });

      setState(() {
        _stage = _Stage.uploading;
        _sentBytes = 0;
        _totalBytes = totalBytes;
        _currentPath = '';
      });

      // Запускаем Foreground Service. Он продолжает работу, даже если
      // пользователь свернёт приложение или откроет другое.
      await startUpload(files.map((f) => f.path).toList(), totalBytes: totalBytes);

      // Если за 60 секунд не пришло ни байта — скорее всего неверный URL сервера
      // или фоновый сервис не запустился. Показываем понятную ошибку.
      _stallTimer = Timer(const Duration(seconds: 60), () {
        if (!mounted || _sentBytes > 0) return;
        _progressSub?.cancel();
        _doneSub?.cancel();
        setState(() {
          _stage = _Stage.error;
          _error = 'Загрузка не началась за 60 секунд.\n\n'
              'Проверьте:\n'
              '• URL сервера в Настройках (сейчас используется адрес по умолчанию)\n'
              '• Сервер запущен и доступен с телефона\n'
              '• Для физического устройства через USB: adb reverse tcp:8000 tcp:8000';
        });
      });
    } on FileSystemException catch (e) {
      if (!mounted) return;
      setState(() {
        _stage = _Stage.error;
        _error = e.message;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _stage = _Stage.error;
        _error = e.toString();
      });
    }
  }

  Future<bool?> _confirmUpload(List<File> files, int totalBytes) {
    return showDialog<bool>(
      context: context,
      barrierDismissible: false,
      builder: (ctx) => AlertDialog(
        title: const Text('Файлы найдены'),
        content: Text(
          'Найдено файлов: ${files.length}\n'
          'Общий размер: ${_formatBytes(totalBytes)}\n\n'
          'Загрузить их на backend и построить индекс?',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Отмена'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Загрузить'),
          ),
        ],
      ),
    );
  }

  void _showLeaveWarning() {
    showDialog<void>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Загрузка идёт'),
        content: const Text(
          'Загрузка продолжится в фоне, даже если открыть другое приложение.\n\n'
          'Если выйти с этого экрана — автоматический переход к следующему '
          'шагу не сработает, придётся вернуться сюда вручную.',
        ),
        actions: [
          FilledButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Остаться'),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return PopScope(
      // Во время загрузки блокируем системную кнопку «Назад»,
      // чтобы обрыв соединения не воспринимался как потеря сервера.
      canPop: _stage != _Stage.uploading,
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop) _showLeaveWarning();
      },
      child: Scaffold(
        appBar: AppBar(
          title: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text('Сканирование'),
              Text(
                _shortPath(widget.rootPath),
                style: const TextStyle(fontSize: 11, fontWeight: FontWeight.normal),
                overflow: TextOverflow.ellipsis,
              ),
            ],
          ),
          automaticallyImplyLeading: _stage == _Stage.error,
        ),
        body: Padding(
          padding: const EdgeInsets.all(24),
          child: Center(child: _buildContent()),
        ),
      ),
    );
  }

  Widget _buildContent() {
    if (_stage == _Stage.error) {
      return Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(Icons.error_outline, size: 64, color: Colors.red.shade700),
          const SizedBox(height: 16),
          Text(
            _error ?? 'Неизвестная ошибка',
            textAlign: TextAlign.center,
            style: TextStyle(color: Colors.red.shade700),
          ),
          const SizedBox(height: 24),
          FilledButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Назад'),
          ),
        ],
      );
    }

    if (_stage == _Stage.uploading) {
      final progress = _totalBytes > 0 ? _sentBytes / _totalBytes : null;
      return _ProgressBlock(
        title: 'Загрузка файлов',
        progress: progress,
        primary: '${_formatBytes(_sentBytes)} / ${_formatBytes(_totalBytes)}',
        secondary: _currentPath,
        warning: 'Можно открывать другие приложения — загрузка продолжится',
      );
    }

    if (_stage == _Stage.confirming) {
      return _ProgressBlock(
        title: 'Подтверждение',
        progress: null,
        primary: 'Найдено файлов: $_foundFiles',
        secondary: 'Ожидание решения',
      );
    }

    return _ProgressBlock(
      title: 'Сканирование устройства',
      progress: null,
      primary: 'Папок: $_scannedDirs · файлов: $_foundFiles',
      secondary: _currentPath,
    );
  }

  /// Показывает последние два сегмента пути, чтобы заголовок не был слишком длинным.
  /// /storage/emulated/0/DCIM → …/DCIM
  static String _shortPath(String path) {
    final parts = path.split('/').where((p) => p.isNotEmpty).toList();
    if (parts.length <= 2) return path;
    return '…/${parts.skip(parts.length - 2).join('/')}';
  }

  static String _formatBytes(int bytes) {
    if (bytes < 1024) return '$bytes Б';
    final kb = bytes / 1024;
    if (kb < 1024) return '${kb.toStringAsFixed(1)} КБ';
    final mb = kb / 1024;
    if (mb < 1024) return '${mb.toStringAsFixed(1)} МБ';
    final gb = mb / 1024;
    return '${gb.toStringAsFixed(1)} ГБ';
  }
}

class _ProgressBlock extends StatelessWidget {
  final String title;
  final double? progress;
  final String primary;
  final String secondary;
  final String? warning;

  const _ProgressBlock({
    required this.title,
    required this.progress,
    required this.primary,
    required this.secondary,
    this.warning,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        Text(
          title,
          style: const TextStyle(fontSize: 20, fontWeight: FontWeight.bold),
        ),
        const SizedBox(height: 24),
        LinearProgressIndicator(value: progress),
        const SizedBox(height: 16),
        Text(primary, style: const TextStyle(fontSize: 16)),
        const SizedBox(height: 8),
        Text(
          secondary,
          maxLines: 2,
          overflow: TextOverflow.ellipsis,
          textAlign: TextAlign.center,
          style: TextStyle(color: Colors.grey.shade600, fontSize: 12),
        ),
        if (warning != null) ...[
          const SizedBox(height: 12),
          Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Icon(Icons.warning_amber_rounded,
                  size: 16, color: Colors.orange.shade700),
              const SizedBox(width: 4),
              Flexible(
                child: Text(
                  warning!,
                  textAlign: TextAlign.center,
                  style:
                      TextStyle(color: Colors.orange.shade700, fontSize: 12),
                ),
              ),
            ],
          ),
        ],
      ],
    );
  }
}
