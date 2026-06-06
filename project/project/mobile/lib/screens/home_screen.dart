import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';

import '../models/index_status.dart';
import '../services/api_service.dart';
import '../services/device_file_scanner.dart';
import 'indexing_screen.dart';
import 'results_screen.dart';
import 'scan_upload_screen.dart';
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
  void initState() {
    super.initState();
    // При старте проверяем статус сервера: если индексация уже идёт
    // (например, приложение перезапустили пока сервер работал), —
    // переходим сразу на IndexingScreen, не заставляя пользователя гадать.
    WidgetsBinding.instance.addPostFrameCallback((_) => _checkServerStatus());
  }

  Future<void> _checkServerStatus() async {
    try {
      final status = await ApiService.getStatus();
      if (!mounted) return;
      if (status.state == IndexState.indexing) {
        Navigator.push(
          context,
          MaterialPageRoute(builder: (_) => const IndexingScreen()),
        );
      }
    } catch (_) {
      // Сервер недоступен при старте — не показываем ошибку, просто ждём.
    }
  }

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
      final results = await ApiService.search(
        query, _fileType, topK: 20, minScore: 0.5,
      );
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
    final selection = await FilePicker.platform.pickFiles(
      allowMultiple: true,
      withReadStream: true,
      type: FileType.any,
    );
    if (selection == null || selection.files.isEmpty) return;
    if (!mounted) return;

    final append = await _askAppendOrReplace();
    if (append == null || !mounted) return;

    setState(() => _isLoading = true);
    try {
      await ApiService.uploadAndIndex(selection.files, append: append);
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

  Future<void> _pickFolderAndIndex() async {
    final dirPath = await FilePicker.platform.getDirectoryPath();
    if (dirPath == null || !mounted) return;
    Navigator.push(
      context,
      MaterialPageRoute(
        builder: (_) => ScanUploadScreen(rootPath: dirPath),
      ),
    );
  }

  Future<bool?> _askAppendOrReplace() {
    return showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Режим индексации'),
        content: const Text(
          'Добавить файлы к существующему индексу '
          'или заменить его новыми файлами?',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Отмена'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Заменить'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Добавить'),
          ),
        ],
      ),
    );
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

      if (!mounted) return;
      // Предлагаем выбрать папку перед сканированием.
      final rootPath = await showModalBottomSheet<String>(
        context: context,
        isScrollControlled: true,
        shape: const RoundedRectangleBorder(
          borderRadius: BorderRadius.vertical(top: Radius.circular(16)),
        ),
        builder: (_) => const _FolderPickerSheet(),
      );

      // null = пользователь закрыл шторку без выбора.
      if (rootPath == null || !mounted) return;

      Navigator.push(
        context,
        MaterialPageRoute(
          builder: (_) => ScanUploadScreen(rootPath: rootPath),
        ),
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

  void _showIndexPrompt(String message) {
    showDialog<void>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Индекс не готов'),
        content: Text(
          '$message\n\n'
          'Если файлы уже были загружены ранее — можно переиндексировать без повторной загрузки.\n'
          'Иначе — просканируйте устройство заново.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Отмена'),
          ),
          TextButton(
            onPressed: () async {
              Navigator.pop(ctx);
              await _reindexUploaded();
            },
            child: const Text('Переиндексировать'),
          ),
          FilledButton(
            onPressed: () {
              Navigator.pop(ctx);
              _scanDeviceAndIndex();
            },
            child: const Text('Сканировать заново'),
          ),
        ],
      ),
    );
  }

  Future<void> _reindexUploaded() async {
    setState(() => _isLoading = true);
    try {
      await ApiService.reindexUploaded();
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
            icon: const Icon(Icons.file_open),
            label: const Text('Выбрать файлы вручную'),
          ),
          const SizedBox(height: 4),
          TextButton.icon(
            onPressed: _isLoading ? null : _pickFolderAndIndex,
            icon: const Icon(Icons.folder_open),
            label: const Text('Выбрать папку'),
          ),
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Шторка выбора папки для сканирования
// ---------------------------------------------------------------------------

class _FolderOption {
  final String label;
  final String sublabel;
  final IconData icon;
  final String path;

  const _FolderOption({
    required this.label,
    required this.sublabel,
    required this.icon,
    required this.path,
  });
}

/// Предустановленные папки Android + ввод произвольного пути.
class _FolderPickerSheet extends StatefulWidget {
  const _FolderPickerSheet();

  @override
  State<_FolderPickerSheet> createState() => _FolderPickerSheetState();
}

class _FolderPickerSheetState extends State<_FolderPickerSheet> {
  static const _root = '/storage/emulated/0';

  static const _presets = <_FolderOption>[
    _FolderOption(
      label: 'Вся память',
      sublabel: 'Все поддерживаемые файлы на устройстве',
      icon: Icons.phone_android,
      path: _root,
    ),
    _FolderOption(
      label: 'Фото и видео (DCIM)',
      sublabel: 'Снимки камеры и скриншоты',
      icon: Icons.photo_camera,
      path: '$_root/DCIM',
    ),
    _FolderOption(
      label: 'Загрузки',
      sublabel: 'Файлы из браузера и мессенджеров',
      icon: Icons.download,
      path: '$_root/Download',
    ),
    _FolderOption(
      label: 'Изображения',
      sublabel: 'Папка Pictures',
      icon: Icons.image,
      path: '$_root/Pictures',
    ),
    _FolderOption(
      label: 'Документы',
      sublabel: 'Папка Documents',
      icon: Icons.description,
      path: '$_root/Documents',
    ),
    _FolderOption(
      label: 'Видео',
      sublabel: 'Папка Movies/Videos',
      icon: Icons.videocam,
      path: '$_root/Movies',
    ),
    _FolderOption(
      label: 'Музыка',
      sublabel: 'Папка Music',
      icon: Icons.music_note,
      path: '$_root/Music',
    ),
  ];

  // Когда пользователь хочет ввести произвольный путь.
  bool _showCustomInput = false;
  final _customController = TextEditingController();

  @override
  void dispose() {
    _customController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      child: Padding(
        padding: EdgeInsets.only(
          bottom: MediaQuery.of(context).viewInsets.bottom,
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            // Ручка шторки
            Center(
              child: Container(
                margin: const EdgeInsets.symmetric(vertical: 10),
                width: 40,
                height: 4,
                decoration: BoxDecoration(
                  color: Colors.grey.shade300,
                  borderRadius: BorderRadius.circular(2),
                ),
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
              child: Text(
                'Выберите папку для сканирования',
                style: Theme.of(context).textTheme.titleMedium,
              ),
            ),
            // Список предустановленных папок
            ...(_presets.map((opt) => ListTile(
                  leading: Icon(opt.icon, color: Theme.of(context).colorScheme.primary),
                  title: Text(opt.label),
                  subtitle: Text(
                    opt.sublabel,
                    style: TextStyle(fontSize: 12, color: Colors.grey.shade600),
                  ),
                  onTap: () => Navigator.pop(context, opt.path),
                ))),
            const Divider(height: 1),
            // Ввод произвольного пути
            if (_showCustomInput)
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 8, 16, 8),
                child: Row(
                  children: [
                    Expanded(
                      child: TextField(
                        controller: _customController,
                        autofocus: true,
                        decoration: const InputDecoration(
                          hintText: '/storage/emulated/0/...',
                          border: OutlineInputBorder(),
                          isDense: true,
                          contentPadding:
                              EdgeInsets.symmetric(horizontal: 12, vertical: 10),
                        ),
                        onSubmitted: _submitCustom,
                      ),
                    ),
                    const SizedBox(width: 8),
                    FilledButton(
                      onPressed: () => _submitCustom(_customController.text),
                      child: const Text('OK'),
                    ),
                  ],
                ),
              )
            else
              ListTile(
                leading: Icon(Icons.edit, color: Colors.grey.shade600),
                title: const Text('Указать путь вручную'),
                onTap: () => setState(() => _showCustomInput = true),
              ),
            const SizedBox(height: 8),
          ],
        ),
      ),
    );
  }

  void _submitCustom(String value) {
    final path = value.trim();
    if (path.isEmpty) return;
    Navigator.pop(context, path);
  }
}
