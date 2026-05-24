import 'dart:async';
import 'dart:io';

import 'package:flutter/services.dart';

/// Поиск поддерживаемых файлов в общем хранилище Android.
///
/// На Android 11+ для полного обхода нужен MANAGE_EXTERNAL_STORAGE. Само
/// разрешение выдаётся пользователем на системном экране настроек, который
/// открывает нативная часть через MethodChannel.
class DeviceFileScanner {
  static const _channel = MethodChannel('intelligent_file_search/storage');
  static const _rootPath = '/storage/emulated/0';

  static const _supportedExtensions = {
    '.jpg',
    '.jpeg',
    '.png',
    '.bmp',
    '.webp',
    '.gif',
    '.mp4',
    '.avi',
    '.mov',
    '.mkv',
    '.wmv',
    '.pdf',
    '.docx',
    '.doc',
    '.txt',
    '.csv',
    '.xlsx',
    '.xls',
  };

  static final _ignoredPathParts = {
    '/Android/data/',
    '/Android/obb/',
    '/Android/media/',
  };

  static Future<bool> hasAllFilesAccess() async {
    if (!Platform.isAndroid) return false;
    try {
      return await _channel.invokeMethod<bool>('hasAllFilesAccess') ?? false;
    } on MissingPluginException {
      return false;
    }
  }

  static Future<bool> openAllFilesAccessSettings() async {
    if (!Platform.isAndroid) return false;
    try {
      await _channel.invokeMethod<void>('openAllFilesAccessSettings');
      return true;
    } on MissingPluginException {
      // Android-обвязка могла быть ещё не восстановлена через flutter create.
      // UI покажет пользователю понятную ошибку на следующей проверке доступа.
      return false;
    } on PlatformException {
      return false;
    }
  }

  static Future<List<File>> scanSupportedFiles({
    void Function(int scannedDirs, int foundFiles, String currentPath)?
        onProgress,
  }) async {
    final root = Directory(_rootPath);
    if (!await root.exists()) {
      return const [];
    }

    final files = <File>[];
    final counters = _ScanCounters();
    await _walk(root, files, counters, onProgress);
    files.sort((a, b) => a.path.compareTo(b.path));
    return files;
  }

  static Future<void> _walk(
    Directory directory,
    List<File> files,
    _ScanCounters counters,
    void Function(int scannedDirs, int foundFiles, String currentPath)?
        onProgress,
  ) async {
    if (_shouldIgnore(directory.path)) return;
    counters.scannedDirs += 1;
    onProgress?.call(counters.scannedDirs, counters.foundFiles, directory.path);

    Stream<FileSystemEntity> children;
    try {
      children = directory.list(followLinks: false);
    } on FileSystemException {
      return;
    }

    try {
      await for (final entity in children) {
        if (entity is Directory) {
          await _walk(entity, files, counters, onProgress);
        } else if (entity is File) {
          final path = entity.path;
          if (_shouldIgnore(path)) continue;
          if (!_supportedExtensions.contains(_extensionOf(path))) continue;
          files.add(entity);
          counters.foundFiles += 1;
          onProgress?.call(counters.scannedDirs, counters.foundFiles, path);
        }
      }
    } on FileSystemException {
      return;
    }
  }

  static bool _shouldIgnore(String path) {
    return _ignoredPathParts.any(path.contains);
  }

  static String _extensionOf(String path) {
    final name = path.split(Platform.pathSeparator).last.toLowerCase();
    final dot = name.lastIndexOf('.');
    if (dot < 0) return '';
    return name.substring(dot);
  }
}

class _ScanCounters {
  int scannedDirs = 0;
  int foundFiles = 0;
}
