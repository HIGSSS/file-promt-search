import 'dart:async';

import 'package:flutter/material.dart';

import '../models/index_status.dart';
import '../services/api_service.dart';

/// Экран прогресса индексации.
///
/// Опрашивает /status каждые 2 секунды. При state='done' автоматически
/// возвращает на предыдущий экран через 1 секунду. При state='error'
/// показывает текст ошибки и кнопку «Назад».
class IndexingScreen extends StatefulWidget {
  const IndexingScreen({super.key});

  @override
  State<IndexingScreen> createState() => _IndexingScreenState();
}

class _IndexingScreenState extends State<IndexingScreen> {
  static const _pollInterval = Duration(seconds: 2);

  Timer? _timer;
  IndexStatus? _status;
  String? _networkError;

  @override
  void initState() {
    super.initState();
    _poll(); // Сразу, без ожидания первого tick'а таймера.
    _timer = Timer.periodic(_pollInterval, (_) => _poll());
  }

  @override
  void dispose() {
    // КРИТИЧНО: отменить таймер до уничтожения State, иначе _poll
    // попытается вызвать setState на disposed-виджете → исключение.
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _poll() async {
    try {
      final status = await ApiService.getStatus();
      if (!mounted) return;
      setState(() {
        _status = status;
        _networkError = null;
      });

      if (status.state == IndexState.done) {
        _timer?.cancel();
        // Через секунду закрываем экран. Задержка даёт пользователю
        // увидеть финальное «N из N файлов», прежде чем экран уйдёт.
        Timer(const Duration(seconds: 1), _finish);
      } else if (status.state == IndexState.error) {
        _timer?.cancel();
      }
    } on ApiException catch (e) {
      // Потеря связи — показываем в UI, но таймер не останавливаем:
      // возможно, сервер на секунду ушёл, следующий опрос восстановит.
      if (mounted) setState(() => _networkError = e.message);
    }
  }

  void _finish() {
    if (!mounted) return;
    Navigator.pop(context);
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('Индексация завершена')),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Индексация'),
        automaticallyImplyLeading: false,
      ),
      body: Padding(
        padding: const EdgeInsets.all(24),
        child: Center(child: _buildContent()),
      ),
    );
  }

  Widget _buildContent() {
    if (_networkError != null && _status == null) {
      return _buildError(_networkError!);
    }

    final status = _status;
    if (status == null) {
      return const CircularProgressIndicator();
    }

    if (status.state == IndexState.error) {
      return _buildError(status.error ?? 'Неизвестная ошибка');
    }

    return Column(
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        // progress == null → indeterminate (total ещё не посчитан).
        LinearProgressIndicator(value: status.progress),
        const SizedBox(height: 16),
        Text(
          '${status.processed} / ${status.total} файлов',
          style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
        ),
        const SizedBox(height: 8),
        if (status.currentFile.isNotEmpty)
          Text(
            status.currentFile,
            style: TextStyle(color: Colors.grey.shade600),
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
          ),
        if (_networkError != null) ...[
          const SizedBox(height: 16),
          Text(
            'Связь с сервером потеряна, повтор...',
            style: TextStyle(color: Colors.orange.shade800, fontSize: 12),
          ),
        ],
      ],
    );
  }

  Widget _buildError(String message) {
    return Column(
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        Icon(Icons.error_outline, size: 64, color: Colors.red.shade700),
        const SizedBox(height: 16),
        Text(
          message,
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
}
