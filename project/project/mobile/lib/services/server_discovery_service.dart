import 'dart:async';
import 'dart:io';

import 'package:http/http.dart' as http;

/// Автопоиск backend-сервера в локальной Wi-Fi сети.
///
/// Раньше пользователю приходилось вручную узнавать IP компьютера
/// (ipconfig/ifconfig) и вбивать его в Settings. Вместо этого определяем
/// собственный IP телефона в Wi-Fi (через dart:io, без доп. разрешений —
/// это не WiFi SSID/BSSID, для которых на Android нужна геолокация),
/// берём из него подсеть /24 и параллельно опрашиваем GET /health
/// на каждом адресе. Первый ответивший — и есть сервер.
class ServerDiscoveryService {
  static const _port = 8000;
  static const _probeTimeout = Duration(milliseconds: 400);
  static const _batchSize = 32;

  /// Возвращает 'http://<ip>:8000', если сервер найден в подсети, иначе null.
  static Future<String?> discover({void Function(int checked, int total)? onProgress}) async {
    final localIps = await _localIPv4Addresses();
    if (localIps.isEmpty) return null;

    // Подсеть берём из первого адреса: для обычной домашней Wi-Fi
    // телефон и ПК почти всегда в одной /24-сети (например, 192.168.1.x).
    final prefix = _subnetPrefix(localIps.first);
    if (prefix == null) return null;

    final candidates = [for (var i = 1; i <= 254; i++) '$prefix.$i'];
    var checked = 0;
    final completer = Completer<String?>();

    for (var start = 0; start < candidates.length; start += _batchSize) {
      if (completer.isCompleted) break;
      final batch = candidates.skip(start).take(_batchSize);
      await Future.wait(batch.map((ip) async {
        if (completer.isCompleted) return;
        final found = await _probe(ip);
        checked++;
        onProgress?.call(checked, candidates.length);
        if (found && !completer.isCompleted) {
          completer.complete('http://$ip:$_port');
        }
      }));
    }

    if (!completer.isCompleted) completer.complete(null);
    return completer.future;
  }

  static Future<bool> _probe(String ip) async {
    try {
      final uri = Uri.parse('http://$ip:$_port/health');
      final response = await http.get(uri).timeout(_probeTimeout);
      return response.statusCode == 200;
    } catch (_) {
      return false;
    }
  }

  static Future<List<String>> _localIPv4Addresses() async {
    try {
      final interfaces = await NetworkInterface.list(
        type: InternetAddressType.IPv4,
        includeLoopback: false,
        includeLinkLocal: false,
      );
      return [
        for (final iface in interfaces)
          for (final addr in iface.addresses) addr.address,
      ];
    } on SocketException {
      return [];
    }
  }

  /// '192.168.1.42' → '192.168.1'. null для нестандартных/публичных диапазонов,
  /// где сканирование 254 адресов бессмысленно или слишком тяжело.
  static String? _subnetPrefix(String ip) {
    final parts = ip.split('.');
    if (parts.length != 4) return null;
    final isPrivate = parts[0] == '10' ||
        (parts[0] == '172' && (int.tryParse(parts[1]) ?? 0) >= 16 && (int.tryParse(parts[1]) ?? 0) <= 31) ||
        (parts[0] == '192' && parts[1] == '168');
    if (!isPrivate) return null;
    return '${parts[0]}.${parts[1]}.${parts[2]}';
  }
}
