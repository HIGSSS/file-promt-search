import 'dart:io';

import 'package:flutter/material.dart';
import 'package:open_filex/open_filex.dart';

import '../models/search_result.dart';
import '../services/api_service.dart';

/// Карточка результата поиска.
///
/// - Для изображений показывает превью (Image.file) 60×60 с фолбэком на иконку.
/// - Для остальных типов — иконка.
/// - Score отображается как процент цветным бейджем (зелёный / жёлтый / серый).
/// - Тап по карточке открывает файл через нативное приложение.
class FileCard extends StatelessWidget {
  final SearchResult result;

  const FileCard({super.key, required this.result});

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
              Expanded(child: _buildMeta(context)),
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
    if (result.type == 'image' && File(result.filepath).existsSync()) {
      // Image.file может упасть на битых файлах или на файлах, к которым
      // потерян доступ (пользователь удалил после индексации). errorBuilder
      // ловит это и показывает иконку вместо крэша.
      return SizedBox(
        width: size,
        height: size,
        child: ClipRRect(
          borderRadius: BorderRadius.circular(6),
          child: Image.file(
            File(result.filepath),
            width: size,
            height: size,
            fit: BoxFit.cover,
            errorBuilder: (_, __, ___) => _iconBox(Icons.broken_image),
          ),
        ),
      );
    }
    return _iconBox(_iconForType(result.type));
  }

  Widget _iconBox(IconData icon) {
    return Container(
      width: 60,
      height: 60,
      decoration: BoxDecoration(
        color: Colors.grey.shade200,
        borderRadius: BorderRadius.circular(6),
      ),
      child: Icon(icon, size: 28, color: Colors.grey.shade700),
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

  Widget _buildMeta(BuildContext context) {
    final preview = result.textPreview;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          result.filename,
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
    final percent = (result.score * 100).round();
    final color = _colorForScore(result.score);
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
    // Пороги из §5.4 ТЗ.
    if (score > 0.7) return Colors.green;
    if (score > 0.5) return Colors.orange;
    return Colors.grey;
  }

  Future<void> _openFile(BuildContext context) async {
    try {
      final localPath = File(result.filepath).existsSync()
          ? result.filepath
          : await ApiService.downloadFile(result);
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
