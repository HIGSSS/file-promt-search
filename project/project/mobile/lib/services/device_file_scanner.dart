import 'dart:async';
import 'dart:collection';
import 'dart:io';

import 'package:flutter/services.dart';

/// Поиск поддерживаемых файлов в общем хранилище Android.
class DeviceFileScanner {
  static const _channel = MethodChannel('intelligent_file_search/storage');
  static const _rootPath = '/storage/emulated/0';

  // Защита от OOM: не собираем больше этого числа файлов за один обход.
  static const _maxFiles = 20000;

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
      return false;
    } on PlatformException {
      return false;
    }
  }

  static Future<List<File>> scanSupportedFiles({
    String rootPath = _rootPath,
    void Function(int scannedDirs, int foundFiles, String currentPath)?
        onProgress,
  }) async {
    final root = Directory(rootPath);
    if (!await root.exists()) return const [];

    final files = <File>[];
    // Итеративный обход вместо рекурсивного — не накапливает async-контексты
    // на каждом уровне вложенности, что предотвращает OOM на глубоких деревьях.
    final queue = ListQueue<Directory>()..add(root);
    int scannedDirs = 0;
    int foundFiles = 0;

    outer:
    while (queue.isNotEmpty) {
      final dir = queue.removeFirst();
      if (_shouldIgnore(dir.path)) continue;
      scannedDirs++;

      Stream<FileSystemEntity> children;
      try {
        children = dir.list(followLinks: false);
      } on FileSystemException {
        continue;
      }

      try {
        await for (final entity in children) {
          if (entity is Directory) {
            if (!_shouldIgnore(entity.path)) queue.add(entity);
          } else if (entity is File) {
            final path = entity.path;
            if (_shouldIgnore(path)) continue;
            if (!_supportedExtensions.contains(_extensionOf(path))) continue;
            files.add(entity);
            foundFiles++;
            if (foundFiles >= _maxFiles) break outer;
          }
        }
      } on FileSystemException {
        continue;
      }

      // Отдаём управление event loop каждые 20 папок: даём GC шанс отработать
      // и не блокируем UI-поток надолго.
      if (scannedDirs % 20 == 0) {
        onProgress?.call(scannedDirs, foundFiles, dir.path);
        await Future<void>.delayed(Duration.zero);
      }
    }

    onProgress?.call(scannedDirs, foundFiles, '');
    files.sort((a, b) => a.path.compareTo(b.path));
    return files;
  }

  static bool _shouldIgnore(String path) =>
      _ignoredPathParts.any(path.contains);

  static String _extensionOf(String path) {
    final name = path.split(Platform.pathSeparator).last.toLowerCase();
    final dot = name.lastIndexOf('.');
    if (dot < 0) return '';
    return name.substring(dot);
  }
}
