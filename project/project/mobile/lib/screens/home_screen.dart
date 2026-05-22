import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';

import '../services/api_service.dart';
import '../services/device_file_scanner.dart';
import 'indexing_screen.dart';
import 'results_screen.dart';
import 'settings_screen.dart';

/// Главный экран: строка поиска, выбор типа файлов, запуск поиска
/// и индексации.
class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  final _queryController = TextEditingController();
  String _fileType = 'all';
  bool _isLoading = false;

  @override
  void dispose() {
    _queryController.dispose();
    super.dispose();
  }

  Future<void> _performSearch() async {
    final query = _queryController.text.trim();
    if (query.isEmpty) return;

    setState(() => _isLoading = true);
    try {
      final results = await ApiService.search(query, _fileType, topK: 10);
      if (!mounted) return;
      Navigator.push(
        context,
        MaterialPageRoute(
          builder: (_) => ResultsScreen(results: results, query: query),
        ),
      );
    } on ApiException catch (e) {
      if (!mounted) return;
      // 400 = индекс не построен → подсказка с переходом на индексацию.
      // Другие ошибки → просто SnackBar.
      if (e.statusCode == 400) {
        _showIndexPrompt(e.message);
      } else {
        _showError(e.message);
      }
    } finally {
      if (mounted) setState(() => _isLoading = false);
    }
  }

  Future<void> _startIndexing() async {
    // На телефоне backend не видит Android-пути. Поэтому выбираем файлы
    // через SAF/file_picker и отправляем их на сервер, где они сохраняются
    // локально и уже затем индексируются.
    final selection = await FilePicker.platform.pickFiles(
      allowMultiple: true,
      withReadStream: true,
      type: FileType.any,
    );
    if (selection == null || selection.files.isEmpty) return;

    setState(() => _isLoading = true);
    try {
      await ApiService.uploadAndIndex(selection.files);
      if (!mounted) return;
      Navigator.push(
        context,
        MaterialPageRoute(builder: (_) => const IndexingScreen()),
      );
    } on ApiException catch (e) {
      if (mounted) _showError(e.message);
    } finally {
      if (mounted) setState(() => _isLoading = false);
    }
  }

  Future<void> _scanDeviceAndIndex() async {
    setState(() => _isLoading = true);
    try {
      final hasAccess = await DeviceFileScanner.hasAllFilesAccess();
      if (!hasAccess) {
        if (!mounted) return;
        await _showAllFilesAccessPrompt();
        return;
      }

      final files = await DeviceFileScanner.scanSupportedFiles();
      if (files.isEmpty) {
        if (mounted) {
          _showError('На устройстве не найдены поддерживаемые файлы.');
        }
        return;
      }

      if (!mounted) return;
      final confirmed = await _confirmAutoIndex(files.length);
      if (confirmed != true) return;

      await ApiService.uploadPathsAndIndex(files);
      if (!mounted) return;
      Navigator.push(
        context,
        MaterialPageRoute(builder: (_) => const IndexingScreen()),
      );
    } on ApiException catch (e) {
      if (mounted) _showError(e.message);
    } finally {
      if (mounted) setState(() => _isLoading = false);
    }
  }

  void _showError(String message) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(message), backgroundColor: Colors.red.shade700),
    );
  }

  Future<void> _showAllFilesAccessPrompt() {
    return showDialog<void>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Нужен доступ к файлам'),
        content: const Text(
          'Чтобы искать по документам и медиа на устройстве, разрешите '
          'приложению доступ ко всем файлам в настройках Android.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Позже'),
          ),
          FilledButton(
            onPressed: () async {
              Navigator.pop(ctx);
              final opened =
                  await DeviceFileScanner.openAllFilesAccessSettings();
              if (!opened && mounted) {
                _showError(
                  'Откройте настройки приложения вручную и включите '
                  '"Доступ ко всем файлам". Разрешения фото/видео '
                  'недостаточно.',
                );
              }
            },
            child: const Text('Открыть настройки'),
          ),
        ],
      ),
    );
  }

  Future<bool?> _confirmAutoIndex(int count) {
    return showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Файлы найдены'),
        content: Text(
          'Приложение нашло $count поддерживаемых файлов. '
          'Загрузить их на backend и построить семантический индекс?',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Отмена'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Индексировать'),
          ),
        ],
      ),
    );
  }

  void _showIndexPrompt(String message) {
    showDialog<void>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Индекс не готов'),
        content: Text(
          '$message\n\nХотите просканировать устройство и построить индекс?',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Отмена'),
          ),
          FilledButton(
            onPressed: () {
              Navigator.pop(ctx);
              _scanDeviceAndIndex();
            },
            child: const Text('Сканировать устройство'),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Поиск файлов'),
        actions: [
          IconButton(
            icon: const Icon(Icons.settings),
            onPressed: () => Navigator.push(
              context,
              MaterialPageRoute(builder: (_) => const SettingsScreen()),
            ),
          ),
        ],
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          TextField(
            controller: _queryController,
            decoration: const InputDecoration(
              labelText: 'Что искать',
              hintText: 'например: котик у окна',
              prefixIcon: Icon(Icons.search),
              border: OutlineInputBorder(),
            ),
            textInputAction: TextInputAction.search,
            onSubmitted: (_) => _performSearch(),
            // Пересчёт состояния кнопки при каждом вводе: вынесено
            // как отдельный setState, чтобы не создавать лишние сборки
            // при опечатках. Stateful builder не нужен — экран не тяжёлый.
            onChanged: (_) => setState(() {}),
          ),
          const SizedBox(height: 16),
          SegmentedButton<String>(
            segments: const [
              ButtonSegment(value: 'all', label: Text('Все')),
              ButtonSegment(value: 'media', label: Text('Медиа')),
              ButtonSegment(value: 'documents', label: Text('Документы')),
              ButtonSegment(value: 'other', label: Text('Прочие')),
            ],
            selected: {_fileType},
            onSelectionChanged: (s) => setState(() => _fileType = s.first),
            // showSelectedIcon=false экономит место на узких экранах.
            showSelectedIcon: false,
          ),
          const SizedBox(height: 16),
          FilledButton.icon(
            onPressed: (_isLoading || _queryController.text.trim().isEmpty)
                ? null
                : _performSearch,
            icon: _isLoading
                ? const SizedBox(
                    width: 16,
                    height: 16,
                    child: CircularProgressIndicator(
                      strokeWidth: 2,
                      color: Colors.white,
                    ),
                  )
                : const Icon(Icons.search),
            label: const Text('Найти'),
          ),
          const SizedBox(height: 8),
          TextButton.icon(
            onPressed: _isLoading ? null : _scanDeviceAndIndex,
            icon: const Icon(Icons.manage_search),
            label: const Text('Просканировать устройство'),
          ),
          const SizedBox(height: 8),
          TextButton.icon(
            onPressed: _isLoading ? null : _startIndexing,
            icon: const Icon(Icons.folder_open),
            label: const Text('Выбрать файлы вручную'),
          ),
        ],
      ),
    );
  }
}
