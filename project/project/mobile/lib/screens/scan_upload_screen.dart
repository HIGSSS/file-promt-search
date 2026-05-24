import 'dart:io';

import 'package:flutter/material.dart';

import '../services/api_service.dart';
import '../services/device_file_scanner.dart';
import 'indexing_screen.dart';

enum _Stage { scanning, confirming, uploading, error }

class ScanUploadScreen extends StatefulWidget {
  const ScanUploadScreen({super.key});

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

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _run());
  }

  Future<void> _run() async {
    try {
      final files = await DeviceFileScanner.scanSupportedFiles(
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

      setState(() => _stage = _Stage.confirming);
      final confirmed = await _confirmUpload(files);
      if (!mounted) return;
      if (confirmed != true) {
        Navigator.pop(context);
        return;
      }

      setState(() {
        _stage = _Stage.uploading;
        _sentBytes = 0;
        _totalBytes = files.fold<int>(
          0,
          (sum, file) => sum + file.lengthSync(),
        );
        _currentPath = '';
      });

      await ApiService.uploadPathsAndIndexBatched(
        files,
        onProgress: (sent, total, path) {
          if (!mounted) return;
          setState(() {
            _stage = _Stage.uploading;
            _sentBytes = sent;
            _totalBytes = total;
            _currentPath = path;
          });
        },
      );

      if (!mounted) return;
      Navigator.pushReplacement(
        context,
        MaterialPageRoute(builder: (_) => const IndexingScreen()),
      );
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() {
        _stage = _Stage.error;
        _error = e.message;
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

  Future<bool?> _confirmUpload(List<File> files) {
    final totalBytes = files.fold<int>(0, (sum, file) => sum + file.lengthSync());
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

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Сканирование'),
        automaticallyImplyLeading: _stage == _Stage.error,
      ),
      body: Padding(
        padding: const EdgeInsets.all(24),
        child: Center(child: _buildContent()),
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

  const _ProgressBlock({
    required this.title,
    required this.progress,
    required this.primary,
    required this.secondary,
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
      ],
    );
  }
}
