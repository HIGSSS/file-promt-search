import 'package:shared_preferences/shared_preferences.dart';

/// Хранилище пользовательских настроек.
///
/// SharedPreferences — асинхронный, но быстрый. Не кешируем значения
/// в памяти, чтобы изменения из других частей приложения сразу
/// подхватывались (например, правка URL в Settings → сразу применяется
/// в home_screen при следующем запросе).
class SettingsService {
  static const _keyServerUrl = 'server_url';
  static const _keyLastIndexedPath = 'last_indexed_path';

  /// Значение по умолчанию: 10.0.2.2 — это адрес хоста из Android-эмулятора.
  /// Для физического устройства через adb reverse — 'http://localhost:8000'.
  static const defaultServerUrl = 'http://10.0.2.2:8000';

  static Future<String> getServerUrl() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString(_keyServerUrl) ?? defaultServerUrl;
  }

  static Future<void> setServerUrl(String url) async {
    final prefs = await SharedPreferences.getInstance();
    // Обрезаем пробелы и завершающий слеш: пользователи часто
    // копипастят URL с пробелами или со слешем на конце, из-за чего
    // склейка с путём эндпоинта ломается (http://x/ + /index = http://x//index).
    final normalized = url.trim().replaceAll(RegExp(r'/+$'), '');
    await prefs.setString(_keyServerUrl, normalized);
  }

  static Future<String?> getLastIndexedPath() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString(_keyLastIndexedPath);
  }

  static Future<void> setLastIndexedPath(String path) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_keyLastIndexedPath, path);
  }
}
