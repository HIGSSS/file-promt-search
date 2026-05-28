import 'dart:io';

import 'package:flutter/material.dart';
import 'package:open_filex/open_filex.dart';

import '../models/search_result.dart';
import '../services/api_service.dart';

/// Карточка результата поиска.
///
/// - Для изображений скачивает превью с backend'а и показывает миниатюру 60×60.
///   Скачивание происходит один раз: повторные отображения берут файл из кеша.
/// - Для остальных типов — иконка.
/// - Score отображается как процент цветным бейджем (зелёный / жёлтый / серый).
/// - Тап по карточке открывает файл через нативное приложение.
class FileCard extends StatefulWidget {
  final SearchResult result;

  const FileCard({super.key, required this.result});

  @override
  State<FileCard> createState() => _FileCardState();
}

class _FileCardState extends State<FileCard> {
  String? _localImagePath;

  @override
  void initState() {
    super.initState();
    if (widget.result.type == 'image') {
      _loadThumbnail();
    }
  }

  Future<void> _loadThumbnail() async {
    try {
      final path = await ApiService.downloadFile(widget.result);
      if (mounted) setState(() => _localImagePath = path);
    } catch (_) {
      // Сеть недоступна или файл удалён — показываем иконку.
    }
  }

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
      child: InkWell(
        onTap: () => _openFile(context),
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              _buildPreview(),
              const SizedBox(width: 12),
              Expanded(child: _buildMeta()),
              const SizedBox(width: 8),
              _buildScoreBadge(),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildPreview() {
    const size = 60.0;
    if (widget.result.type == 'image') {
      final path = _localImagePath;
      if (path != null) {
        return SizedBox(
          width: size,
          height: size,
          child: ClipRRect(
            borderRadius: BorderRadius.circular(6),
            child: Image.file(
              File(path),
              width: size,
              height: size,
              fit: BoxFit.cover,
              errorBuilder: (_, __, ___) => _iconBox(Icons.broken_image),
            ),
          ),
        );
      }
      // Пока идёт загрузка — показываем плейсхолдер.
      return _iconBox(Icons.image, loading: true);
    }
    return _iconBox(_iconForType(widget.result.type));
  }

  Widget _iconBox(IconData icon, {bool loading = false}) {
    return Container(
      width: 60,
      height: 60,
      decoration: BoxDecoration(
        color: Colors.grey.shade200,
        borderRadius: BorderRadius.circular(6),
      ),
      child: loading
          ? const Padding(
              padding: EdgeInsets.all(18),
              child: CircularProgressIndicator(strokeWidth: 2),
            )
          : Icon(icon, size: 28, color: Colors.grey.shade700),
    );
  }

  IconData _iconForType(String type) {
    switch (type) {
      case 'video':
        return Icons.videocam;
      case 'pdf':
      case 'docx':
      case 'txt':
        return Icons.description;
      case 'xlsx':
      case 'csv':
        return Icons.table_chart;
      default:
        return Icons.insert_drive_file;
    }
  }

  Widget _buildMeta() {
    final preview = widget.result.textPreview;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          widget.result.filename,
          style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 14),
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
        ),
        const SizedBox(height: 4),
        if (preview != null && preview.isNotEmpty)
          Text(
            preview,
            style: TextStyle(fontSize: 12, color: Colors.grey.shade600),
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
          ),
      ],
    );
  }

  Widget _buildScoreBadge() {
    final percent = (widget.result.score * 100).round();
    final color = _colorForScore(widget.result.score);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(
        color: color,
        borderRadius: BorderRadius.circular(12),
      ),
      child: Text(
        '$percent%',
        style: const TextStyle(
          color: Colors.white,
          fontSize: 12,
          fontWeight: FontWeight.bold,
        ),
      ),
    );
  }

  Color _colorForScore(double score) {
    if (score > 0.7) return Colors.green;
    if (score > 0.5) return Colors.orange;
    return Colors.grey;
  }

  Future<void> _openFile(BuildContext context) async {
    try {
      // Если превью уже скачано — открываем его напрямую, не качаем снова.
      final localPath = _localImagePath ?? await ApiService.downloadFile(widget.result);
      final opened = await OpenFilex.open(localPath);
      if (opened.type != ResultType.done && context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Не удалось открыть файл: ${opened.message}')),
        );
      }
    } on ApiException catch (e) {
      if (!context.mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(e.message)),
      );
    }
  }
}
