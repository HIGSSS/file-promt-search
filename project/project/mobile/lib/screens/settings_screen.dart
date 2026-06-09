import 'package:flutter/material.dart';

import '../models/index_status.dart';
import '../services/api_service.dart';
import '../services/server_discovery_service.dart';
import '../services/settings_service.dart';
import 'indexing_screen.dart';

/// Настройки приложения: URL сервера, статус индекса, переиндексация.
class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  final _urlController = TextEditingController();
  IndexStatus? _status;
  String? _lastPath;
  bool _loading = true;
  bool _discovering = false;

  @override
  void initState() {
    super.initState();
    _loadAll();
  }

  @override
  void dispose() {
    _urlController.dispose();
    super.dispose();
  }

  Future<void> _loadAll() async {
    try {
      // Параллельные загрузки: все три независимы, ждём их через wait.
      final results = await Future.wait([
        SettingsService.getServerUrl(),
        SettingsService.getLastIndexedPath(),
        _fetchStatusOrNull(),
      ]);

      if (!mounted) return;
      setState(() {
        _urlController.text = results[0] as String;
        _lastPath = results[1] as String?;
        _status = results[2] as IndexStatus?;
      });
    } finally {
      // ВАЖНО: снимаем спиннер всегда, даже при неожиданной ошибке —
      // иначе экран Settings зависает в состоянии загрузки навсегда
      // (ровно это и происходило, когда _fetchStatusOrNull пропускал
      // исключения, не являющиеся ApiException).
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<IndexStatus?> _fetchStatusOrNull() async {
    try {
      return await ApiService.getStatus();
    } catch (_) {
      // Сервер недоступен или вернул что-то неожиданное — это ок для
      // settings-экрана, просто покажем «неизвестно». Ловим Exception
      // целиком, а не только ApiException: http-клиент на разных
      // платформах может бросать ClientException/HandshakeException/
      // TypeError при парсинге неожиданного ответа — всё это не должно
      // блокировать загрузку экрана настроек.
      return null;
    }
  }

  Future<void> _discoverServer() async {
    setState(() => _discovering = true);
    try {
      final found = await ServerDiscoveryService.discover();
      if (!mounted) return;
      if (found == null) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text(
              'Сервер не найден в локальной сети. Убедитесь, что телефон '
              'и компьютер в одном Wi-Fi и backend запущен, либо введите URL вручную.',
            ),
          ),
        );
        return;
      }
      _urlController.text = found;
      await _saveUrl(showSavedSnackBar: false);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Сервер найден и сохранён: $found')),
      );
    } finally {
      if (mounted) setState(() => _discovering = false);
    }
  }

  Future<void> _saveUrl({bool showSavedSnackBar = true}) async {
    await SettingsService.setServerUrl(_urlController.text);
    if (!mounted) return;
    if (showSavedSnackBar) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('URL сохранён')),
      );
    }
    // После смены URL имеет смысл перечитать статус с нового сервера.
    final status = await _fetchStatusOrNull();
    if (mounted) setState(() => _status = status);
  }

  Future<void> _reindex() async {
    final path = _lastPath;
    if (path == null) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Нет ранее загруженных файлов')),
      );
      return;
    }
    try {
      await ApiService.reindexUploaded();
      if (!mounted) return;
      Navigator.push(
        context,
        MaterialPageRoute(builder: (_) => const IndexingScreen()),
      );
    } on ApiException catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(e.message)),
        );
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Настройки')),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : ListView(
              padding: const EdgeInsets.all(16),
              children: [
                _buildServerUrlSection(),
                const Divider(height: 32),
                _buildStatusSection(),
                const Divider(height: 32),
                _buildReindexSection(),
              ],
            ),
    );
  }

  Widget _buildServerUrlSection() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const Text('URL сервера', style: TextStyle(fontWeight: FontWeight.bold)),
        const SizedBox(height: 8),
        TextField(
          controller: _urlController,
          decoration: const InputDecoration(
            hintText: 'http://10.0.2.2:8000',
            border: OutlineInputBorder(),
          ),
          keyboardType: TextInputType.url,
          autocorrect: false,
        ),
        const SizedBox(height: 8),
        Row(
          mainAxisAlignment: MainAxisAlignment.end,
          children: [
            TextButton.icon(
              onPressed: _discovering ? null : _discoverServer,
              icon: _discovering
                  ? const SizedBox(
                      width: 16,
                      height: 16,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Icon(Icons.wifi_find),
              label: Text(_discovering ? 'Ищем в сети...' : 'Найти в сети'),
            ),
            const SizedBox(width: 8),
            FilledButton(
              onPressed: _discovering ? null : () => _saveUrl(),
              child: const Text('Сохранить'),
            ),
          ],
        ),
        const SizedBox(height: 4),
        Text(
          'Телефон и компьютер должны быть в одной Wi-Fi сети. '
          '«Найти в сети» сам подберёт IP компьютера, на котором запущен backend.',
          style: TextStyle(fontSize: 12, color: Colors.grey.shade600),
        ),
      ],
    );
  }

  Widget _buildStatusSection() {
    final status = _status;
    final label = status == null
        ? 'сервер недоступен'
        : '${_stateLabel(status.state)} · ${status.total} файлов';
    return ListTile(
      contentPadding: EdgeInsets.zero,
      leading: const Icon(Icons.info_outline),
      title: const Text('Статус индекса'),
      subtitle: Text(label),
    );
  }

  String _stateLabel(IndexState state) {
    switch (state) {
      case IndexState.idle:
        return 'готов';
      case IndexState.indexing:
        return 'индексируется';
      case IndexState.done:
        return 'готов';
      case IndexState.error:
        return 'ошибка';
      case IndexState.unknown:
        return 'неизвестно';
    }
  }

  Widget _buildReindexSection() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const Text('Переиндексация',
            style: TextStyle(fontWeight: FontWeight.bold)),
        const SizedBox(height: 8),
        Text(
          _lastPath ?? 'нет ранее загруженных файлов',
          style: TextStyle(color: Colors.grey.shade600),
        ),
        const SizedBox(height: 8),
        FilledButton.icon(
          onPressed: _lastPath == null ? null : _reindex,
          icon: const Icon(Icons.refresh),
          label: const Text('Переиндексировать'),
        ),
      ],
    );
  }
}
